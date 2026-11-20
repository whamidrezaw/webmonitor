"""Regression and security tests for the 4-wave architecture & UI/UX overhaul."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import re
import shutil
import socket
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webmonitor import cli, netguard, report  # noqa: E402
from webmonitor.analyzer import Analysis  # noqa: E402
from webmonitor.bot import AdminBot, _Callback  # noqa: E402
from webmonitor.challenge import ChallengeManager, RATE_LIMIT_MAX_FAILURES  # noqa: E402
from webmonitor.config import ConfigError, parse_config  # noqa: E402
from webmonitor.engine import Monitor  # noqa: E402
from webmonitor.extract import Snapshot  # noqa: E402
from webmonitor.fetchers import (  # noqa: E402
    FetchError,
    FetchResult,
    clear_watch_cookies,
    has_watch_cookies,
    import_watch_cookies,
    watch_cookie_paths,
)
from webmonitor.miniapp import USE_CASE_PROFILES  # noqa: E402
from webmonitor.miniapp_ui import MINIAPP_HTML  # noqa: E402
from webmonitor.storage import Store  # noqa: E402
import threading


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _FakeTelegram:
    def __init__(self):
        self.texts: list[tuple[str, str, dict | None]] = []
        self.edits: list[tuple[str, int, str, dict | None]] = []
        self.photos: list[tuple[str, str, str]] = []
        self.acks: list[tuple[str, str, bool]] = []

    async def send_text(self, chat_id: str, text: str, reply_markup: dict | None = None, **_kw):
        self.texts.append((str(chat_id), text, reply_markup))
        return {"message_id": len(self.texts)}

    async def edit_text(self, chat_id: str, message_id: int, text: str, reply_markup: dict | None = None):
        self.edits.append((str(chat_id), message_id, text, reply_markup))
        return {"message_id": message_id}

    async def send_photo(self, chat_id: str, filename: str, _data: bytes, caption: str = "", **_kw):
        self.photos.append((str(chat_id), filename, caption))
        return {"message_id": 100 + len(self.photos)}

    async def answer_callback(self, query_id: str, text: str = "", alert: bool = False):
        self.acks.append((query_id, text, alert))

    async def close(self):
        return None


class NetguardAndConfigAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_public_browser_url_blocks_internal_and_non_http_schemes(self):
        await netguard.ensure_public_browser_url("about:blank")
        await netguard.ensure_public_browser_url("data:image/png;base64,AAAA")
        await netguard.ensure_public_browser_url("https://93.184.216.34/visa")
        for bad in (
            "file:///etc/passwd",
            "chrome://settings",
            "javascript:alert(1)",
            "http://127.0.0.1:8899/health",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]:8080/",
        ):
            with self.subTest(bad=bad), self.assertRaises(netguard.UnsafeTarget):
                await netguard.ensure_public_browser_url(bad)

    def test_is_direct_loopback_rejects_proxied_or_external_requests(self):
        self.assertTrue(netguard.is_direct_loopback("127.0.0.1", {}))
        self.assertTrue(netguard.is_direct_loopback("::1", {}))
        self.assertTrue(netguard.is_direct_loopback("::ffff:127.0.0.1", {}))
        self.assertFalse(netguard.is_direct_loopback(None, {}))
        self.assertFalse(netguard.is_direct_loopback("203.0.113.9", {}))
        for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP"):
            with self.subTest(header=header):
                self.assertFalse(netguard.is_direct_loopback("127.0.0.1", {header: "203.0.113.9"}))

    def test_config_rejects_crlf_headers_and_accepts_side_by_side_style(self):
        cfg = parse_config(
            {
                "watches": [
                    {
                        "id": "sbs",
                        "url": "https://example.com/news",
                        "report_style": "side_by_side",
                    }
                ]
            },
            ROOT / "tmp-cfg.json",
        )
        self.assertEqual(cfg.watches[0].report_style, "side_by_side")

        with self.assertRaises(ConfigError):
            parse_config(
                {
                    "watches": [
                        {
                            "id": "bad_hdr",
                            "url": "https://example.com/a",
                            "headers": {"X-Test": "ok\r\nInjected: 1"},
                        }
                    ]
                },
                ROOT / "tmp-cfg.json",
            )


class CliAndStoreAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wm-audit-store-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_package_redact_secrets_strips_tokens_and_proxy_credentials(self):
        cfg_file = self.tmp / "monitor-config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "telegram": {
                        "token": "123456:SECRET_BOT_TOKEN",
                        "chat_ids": ["-100999"],
                        "admin_ids": ["77777"],
                    },
                    "global_proxy": "http://u:secretpass@1.2.3.4:8080",
                    "watches": [
                        {
                            "id": "w1",
                            "url": "https://example.com",
                            "proxy": "socks5://alice:topsecret@127.0.0.1:40000",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        redacted = json.loads(cli._redacted_config_bytes(cfg_file).decode("utf-8"))
        self.assertEqual(redacted["telegram"]["token"], "YOUR_TELEGRAM_BOT_TOKEN")
        self.assertEqual(redacted["telegram"]["chat_ids"], ["YOUR_CHAT_ID"])
        self.assertEqual(redacted["telegram"]["admin_ids"], [])
        self.assertIsNone(redacted.get("global_proxy"))
        self.assertNotIn("SECRET_BOT_TOKEN", json.dumps(redacted))
        self.assertNotIn("topsecret", json.dumps(redacted))

        out_zip = self.tmp / "deploy-redacted.zip"
        cfg_obj = parse_config({"data_dir": str(self.tmp / "data"), "watches": []}, cfg_file)
        args = argparse.Namespace(output=str(out_zip), redact_secrets=True)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.cmd_package(cfg_obj, args)
        self.assertEqual(rc, 0)
        with zipfile.ZipFile(out_zip) as zf:
            if "monitor-config.json" in zf.namelist():
                packaged_raw = zf.read("monitor-config.json").decode("utf-8")
                packaged_cfg = json.loads(packaged_raw)
                self.assertIn(packaged_cfg.get("telegram", {}).get("token", ""), ("", "YOUR_TELEGRAM_BOT_TOKEN"))

    def test_store_search_events_prune_and_orphan_settings_cleanup(self):
        store = Store(self.tmp / "monitor.db")
        try:
            store.record_page(
                "visa_de",
                "https://example.com/visa",
                digest="d1",
                snapshot="{}",
                changed=True,
                event=("change", "ظرفیت ۱۰۰% تکمیل شد — نوبت دهي کیک", {"blocks": ["نوبت جدید"]}, "sent"),
            )
            store.record_items(
                "news_de",
                ["item-1"],
                event=("new_items", "خبر فوری کنسولگری", {"blocks": ["اطلاعیه ویزا"]}, "sent"),
            )
            store.add_event("visa_de", None, "error", "HTTP 500", {"blocks": ["internal error"]}, status="sent")

            # Arabic Yeh/Kaf normalization ("نوبت دهی کیک" matches "نوبت دهي کیک")
            hits_fa = store.search_events("كيك")
            self.assertEqual([r["watch_id"] for r in hits_fa], ["visa_de"])

            # Literal '%' must not act as a SQL wildcard matching everything
            hits_pct = store.search_events("100%")
            self.assertEqual([r["watch_id"] for r in hits_pct], ["visa_de"])

            # Both 'change' and 'new_items' are searchable, while 'error' is excluded
            self.assertEqual(len(store.search_events("کنسولگری")), 1)
            self.assertEqual(len(store.search_events("HTTP 500")), 0)

            # Orphaned per-watch settings cleanup
            for prefix in (
                "timeout:",
                "exit_ip:",
                "rate_limit_since:",
                "rate_limit_notified:",
                "challenge_cooldown:",
                "tip:noisy:",
            ):
                store.set_setting(f"{prefix}visa_de", "123")
                store.set_setting(f"{prefix}ghost_watch", "456")

            store.reset_watch("visa_de")
            self.assertEqual(store.get_setting("rate_limit_notified:visa_de", ""), "")
            self.assertEqual(store.get_setting("timeout:visa_de", ""), "")

            stale = store.forget_unknown_watches(["news_de"])
            self.assertIn("ghost_watch", stale)
            self.assertEqual(store.get_setting("rate_limit_notified:ghost_watch", ""), "")

            # Prune removes old 'failed' events alongside 'sent', keeping 'pending'
            old_ts = time.time() - 40 * 86400
            ev_failed = store.add_event("news_de", None, "error", "old fail", {})
            store.finish_events([ev_failed], "failed", "permanent")
            with store.conn:
                store.conn.execute("UPDATE events SET created = ? WHERE id = ?", (old_ts, ev_failed))
            store.prune(history_days=30)
            self.assertIsNone(store.get_event(ev_failed))
        finally:
            store.close()


class CookieAndReportAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wm-audit-cookies-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cookie_import_formats_and_sync_across_engines(self):
        cfg = parse_config(
            {"data_dir": str(self.tmp), "watches": [{"id": "portal", "url": "https://portal.example.com/login"}]},
            self.tmp / "cfg.json",
        )
        watch = cfg.watches[0]

        # 1) Cookie-Editor JSON via Watch object
        editor_json = json.dumps(
            [
                {
                    "name": "cf_clearance",
                    "value": "tok_abc",
                    "domain": ".portal.example.com",
                    "path": "/",
                    "expirationDate": 1893456000,
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "no_restriction",
                }
            ]
        )
        self.assertEqual(import_watch_cookies(self.tmp, watch, editor_json), 1)
        self.assertTrue(has_watch_cookies(self.tmp, "portal"))
        pw_path, imp_path = watch_cookie_paths(self.tmp, "portal")
        saved_pw = json.loads(pw_path.read_text(encoding="utf-8"))
        self.assertEqual(saved_pw["cookies"][0]["sameSite"], "None")
        self.assertTrue(saved_pw["cookies"][0]["httpOnly"])
        self.assertEqual(json.loads(imp_path.read_text(encoding="utf-8")), {"cf_clearance": "tok_abc"})

        # 2) Netscape #HttpOnly_ format via (data_dir, watch_id, raw, url) signature
        netscape = (
            "# Netscape HTTP Cookie File\n"
            "#HttpOnly_.portal.example.com\tTRUE\t/\tTRUE\t1893456000\tsid\txyz987\n"
        )
        self.assertEqual(import_watch_cookies(self.tmp, "portal", netscape, watch.url), 1)
        saved_pw2 = json.loads(pw_path.read_text(encoding="utf-8"))
        self.assertTrue(saved_pw2["cookies"][0]["httpOnly"])
        self.assertEqual(json.loads(imp_path.read_text(encoding="utf-8")), {"sid": "xyz987"})

        # 3) Cookie: header format + clear
        self.assertEqual(import_watch_cookies(self.tmp, "portal", "Cookie: a=1; b=2", watch.url), 2)
        clear_watch_cookies(self.tmp, "portal")
        self.assertFalse(has_watch_cookies(self.tmp, "portal"))
        self.assertFalse(pw_path.exists())
        self.assertFalse(imp_path.exists())

    def test_side_by_side_telegram_hunk_and_interactive_html_document(self):
        hunk = report.Hunk("modify", old="Plätze: 0 frei", new="Plätze: 4 frei", context="Goethe B2")
        rendered = report.render_hunk(hunk, style="side_by_side")
        self.assertIn("⫷ <b>قبل:</b>", rendered)
        self.assertIn("⫸ <b>بعد:</b>", rendered)
        self.assertNotIn("<div", rendered)
        self.assertNotIn("<span", rendered)

        doc = report.render_document(
            "Goethe B2",
            "📊 <b>گزارش تغییرات Goethe B2</b>",
            [
                rendered,
                report.render_hunk(report.Hunk("add", new="Zusatztermin"), style="side_by_side"),
                report.render_hunk(report.Hunk("remove", old="Warteliste"), style="side_by_side"),
            ],
        )
        self.assertIn('id="btn-split"', doc)
        self.assertIn('id="btn-theme"', doc)
        self.assertIn('id="btn-prev"', doc)
        self.assertIn('id="btn-next"', doc)
        self.assertIn('id="btn-copy"', doc)
        self.assertIn('class="meter"', doc)
        self.assertIn("@media print", doc)
        self.assertIsNone(re.search(r"\bon(?:click|input|change)\s*=", doc, re.I))

    def test_design_system_contract_exists_and_covers_core_sections(self):
        design_md = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("Surface", design_md)
        self.assertIn("tabular-nums", design_md)
        self.assertIn("prefers-reduced-motion", design_md)
        self.assertIn("Content-Security-Policy", design_md)


class ChallengeSecurityAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.port = _free_port()
        self.mgr = ChallengeManager(host="127.0.0.1", port=self.port, ttl_seconds=120)
        await self.mgr.start()
        self.base = f"http://127.0.0.1:{self.port}"

    async def asyncTearDown(self):
        await self.mgr.close()

    async def test_challenge_csp_csrf_auto_and_rate_limit(self):
        auto_called = []
        sess = self.mgr.create(watch_id="w1", watch_label="Embassy", url="https://example.com")
        sess.click_fn = lambda x, y: asyncio.sleep(0)

        async def _auto():
            auto_called.append(True)
            return True

        sess.click_turnstile_fn = _auto

        async with aiohttp.ClientSession() as client:
            # Page carries strict CSP and zero inline onclick handlers
            async with client.get(f"{self.base}/c/{sess.token}") as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("default-src 'none'", resp.headers.get("Content-Security-Policy", ""))
                html_body = await resp.text()
                self.assertIsNone(re.search(r"\bonclick\s*=", html_body, re.I))

            # Cross-site POSTs are blocked (403)
            async with client.post(
                f"{self.base}/c/{sess.token}/click",
                json={"x": 100, "y": 100},
                headers={"Sec-Fetch-Site": "cross-site"},
            ) as resp:
                self.assertEqual(resp.status, 403)

            async with client.post(
                f"{self.base}/c/{sess.token}/click",
                json={"x": 100, "y": 100},
                headers={"Origin": "https://evil.example"},
            ) as resp:
                self.assertEqual(resp.status, 403)

            # Same-origin auto-click succeeds
            async with client.post(
                f"{self.base}/c/{sess.token}/auto",
                json={},
                headers={"Origin": f"http://127.0.0.1:{self.port}"},
            ) as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(data["clicked"])
                self.assertEqual(len(auto_called), 1)

            # Brute-force invalid tokens hit 429 rate limit
            for _ in range(RATE_LIMIT_MAX_FAILURES):
                async with client.get(f"{self.base}/c/00000000000000000000000000000000") as resp:
                    self.assertEqual(resp.status, 404)
            async with client.get(f"{self.base}/c/00000000000000000000000000000001") as resp:
                self.assertEqual(resp.status, 429)


class MiniAppBotAndEngineAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wm-audit-e2e-"))
        site_app = web.Application()

        async def handle_root(_req):
            return web.Response(
                text=(
                    "<html><head><title>Embassy News</title></head>"
                    "<body><main id='main'><h1>Appointments and Consular Announcements</h1>"
                    "<p>Visa appointment slots are updated every week for all student, family reunion, "
                    "and skilled worker visa applicants at the embassy portal. Please bring complete documents.</p>"
                    "<p>Additional registration dates are published every Monday morning at 09:00 local time.</p>"
                    "<a href='/sub'>Subpage</a></main></body></html>"
                ),
                content_type="text/html",
            )

        async def handle_sub(_req):
            return web.Response(
                text="<html><body><main id='main'><p>Subpage details here.</p></main></body></html>",
                content_type="text/html",
            )

        site_app.router.add_get("/embassy", handle_root)
        site_app.router.add_get("/embassy/", handle_root)
        site_app.router.add_get("/sub", handle_sub)
        self.site_runner = web.AppRunner(site_app)
        await self.site_runner.setup()
        tcp = web.TCPSite(self.site_runner, "127.0.0.1", 0)
        await tcp.start()
        self.site_port = tcp._server.sockets[0].getsockname()[1]

        self.cport = _free_port()
        cfg = parse_config(
            {
                "data_dir": str(self.tmp / "data"),
                "notify_startup": False,
                "daily_report_hour": None,
                "challenge_port": self.cport,
                "watches": [
                    {
                        "id": "embassy",
                        "name": "سفارت",
                        "url": f"http://127.0.0.1:{self.site_port}/embassy/",
                        "selector": "#main",
                        "engine": "auto",
                        "min_content_length": 10,
                    }
                ],
            },
            self.tmp / "cfg.json",
        )
        self.monitor = Monitor(cfg, dry_run=True)
        await self.monitor.start()
        self.base = f"http://127.0.0.1:{self.cport}"

    async def asyncTearDown(self):
        await self.monitor.close()
        await self.site_runner.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_miniapp_security_wizard_cookies_and_challenge_flow(self):
        self.assertIn("&#39;", MINIAPP_HTML)
        self.assertNotIn("watch_label)}')", MINIAPP_HTML)
        self.assertNotIn("s.label)}')", MINIAPP_HTML)

        async with aiohttp.ClientSession() as client:
            # 1) /app serves strict CSP
            async with client.get(f"{self.base}/app") as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("Content-Security-Policy", resp.headers)

            # 2) No-token mode rejects reverse-proxied requests
            async with client.get(
                f"{self.base}/api/app/state",
                headers={"X-Forwarded-For": "198.51.100.42"},
            ) as resp:
                self.assertEqual(resp.status, 403)

            # 3) CSRF guard blocks foreign Origin on state-changing POST
            async with client.post(
                f"{self.base}/api/app/check-all",
                json={},
                headers={"Origin": "https://attacker.example"},
            ) as resp:
                self.assertEqual(resp.status, 403)

            # 4) Add site normalizes @channel -> https://t.me/s/channel and defaults ignore_reorder=True
            with mock.patch("webmonitor.netguard.is_public_host", new=mock.AsyncMock(return_value=True)):
                async with client.post(
                    f"{self.base}/api/app/add",
                    json={"url": "@tehran_visa_news", "type": "headlines"},
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    added = await resp.json()
                    self.assertTrue(added["ok"])
                    rec = self.monitor.registry.get(key=added["key"])
                    self.assertEqual(rec.watch.url, "https://t.me/s/tehran_visa_news")
                    self.assertTrue(rec.watch.ignore_reorder)

            # 5) Smart URL analyze & site diagnose & cookie import endpoints
            embassy_key = self.monitor.registry.get(watch_id="embassy").key
            with mock.patch("webmonitor.netguard.is_public_host", new=mock.AsyncMock(return_value=True)):
                async with client.post(
                    f"{self.base}/api/app/analyze",
                    json={"url": f"http://127.0.0.1:{self.site_port}/embassy/"},
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    adata = await resp.json()
                    self.assertTrue(adata["ok"])
                    self.assertGreaterEqual(len(adata["choices"]), 1)

            async with client.post(f"{self.base}/api/app/site/{embassy_key}/diagnose", json={}) as resp:
                self.assertEqual(resp.status, 200)
                ddata = await resp.json()
                self.assertTrue(ddata["ok"])
                self.assertIsNotNone(ddata["recommended"])

            async with client.post(
                f"{self.base}/api/app/site/{embassy_key}/cookies",
                json={"cookies": "cf_clearance=ok123; session=s456"},
            ) as resp:
                self.assertEqual(resp.status, 200)
                cdata = await resp.json()
                self.assertEqual(cdata["count"], 2)
                self.assertTrue(has_watch_cookies(self.monitor.config.data_dir, "embassy"))

            # 6) Challenge 'done' checks detect_block before closing session (409 unless force=True)
            csess = self.monitor.challenge.create(
                watch_id="embassy", watch_label="سفارت", url="https://example.com"
            )
            csess.key_fn = lambda k: asyncio.sleep(0)
            csess.html_fn = mock.AsyncMock(
                return_value="<html><title>Just a moment...</title><body>cf-turnstile</body></html>"
            )
            async with client.post(
                f"{self.base}/api/app/challenge/{csess.token}/action",
                json={"action": "key", "key": "Enter"},
            ) as resp:
                self.assertEqual(resp.status, 200)

            async with client.post(
                f"{self.base}/api/app/challenge/{csess.token}/action",
                json={"action": "done"},
            ) as resp:
                self.assertEqual(resp.status, 409)
                bdata = await resp.json()
                self.assertTrue(bdata["still_blocked"])

            async with client.post(
                f"{self.base}/api/app/challenge/{csess.token}/action",
                json={"action": "done", "force": True},
            ) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIsNone(self.monitor.challenge.get(csess.token))

    async def test_bot_callbacks_search_and_no_hardcoded_miniapp_domain(self):
        fake_tg = _FakeTelegram()
        bot = AdminBot(self.monitor)
        bot.tg = fake_tg

        # No hardcoded DuckDNS domain when miniapp_url is unset
        with mock.patch.dict("os.environ", {"WEBMONITOR_MINIAPP_URL": ""}, clear=False):
            self.assertEqual(bot._miniapp_row("111"), [])

        rec = self.monitor.registry.get(watch_id="embassy")
        ctx = _Callback(fake_tg, "q1")
        # Callback rs:{key} asks confirmation, then rsy:{key} performs reset cleanly without TypeError
        await bot._handle_callback(ctx, "111", None, "111", f"rs:{rec.key}")
        self.assertTrue(any("پاک شود؟" in t[1] for t in fake_tg.texts))
        await bot._handle_callback(ctx, "111", None, "111", f"rsy:{rec.key}")
        self.assertTrue(any("حافظه و نشست" in t[1] for t in fake_tg.texts))

        # Cycle report_style covers all 3 styles: inline -> before_after -> side_by_side -> inline
        await bot.cycle_report_style("111", rec.key)
        self.assertEqual(self.monitor.registry.get(key=rec.key).watch.report_style, "before_after")
        await bot.cycle_report_style("111", rec.key)
        self.assertEqual(self.monitor.registry.get(key=rec.key).watch.report_style, "side_by_side")
        await bot.cycle_report_style("111", rec.key)
        self.assertEqual(self.monitor.registry.get(key=rec.key).watch.report_style, "inline")

        # Challenge callback ck:{token}:ok warns when still blocked, completes on ck:{token}:okf
        csess = self.monitor.challenge.create(watch_id="embassy", watch_label="سفارت", url="https://example.com")
        csess.html_fn = mock.AsyncMock(
            return_value="<html><title>Just a moment...</title><body>cf-turnstile</body></html>"
        )
        await bot._handle_callback(_Callback(fake_tg, "q2"), "111", None, "111", f"ck:{csess.token}:ok")
        self.assertIsNotNone(self.monitor.challenge.get(csess.token))
        await bot._handle_callback(_Callback(fake_tg, "q3"), "111", None, "111", f"ck:{csess.token}:okf")
        self.assertIsNone(self.monitor.challenge.get(csess.token))

        # Bot search finds 'change' and 'new_items' events
        self.monitor.store.record_page(
            "embassy",
            rec.watch.url,
            digest="d1",
            snapshot="{}",
            changed=True,
            event=("change", "ظرفیت جدید سفارت باز شد", "{}", "sent"),
        )
        fake_tg.texts.clear()
        await bot.run_search("111", "ظرفیت جدید")
        self.assertTrue(any("ظرفیت جدید سفارت" in t[1] for t in fake_tg.texts))

    async def test_engine_root_alias_clears_suggestion_and_crawl_escalates_engine(self):
        from dataclasses import replace
        from webmonitor.extract import page_snapshot, parse_html

        w = replace(self.monitor.watch("embassy"), url=f"http://127.0.0.1:{self.site_port}/embassy/#appointments")
        # w.url has a #fragment, while _root(w) is normalized without the fragment
        self.monitor._suggestions[w.id] = {"selector": "article", "cover": 0.9}
        root = self.monitor._root(w)
        self.assertNotEqual(root, w.url)
        html_doc = "<html><head><title>Embassy</title></head><body><main id='main'><p>Appointments open now</p></main></body></html>"
        snap = page_snapshot(parse_html(html_doc, root), root, selector="#main")
        res = FetchResult(w.url, w.url, 200, "text/html", html_doc, html_doc.encode("utf-8"), "http")
        await self.monitor._apply_snapshot(w, root, None, snap, res)
        self.assertNotIn(w.id, self.monitor._suggestions)

        # _crawl_fetch escalates from http -> impersonate when a subpage returns anti-bot HTTP 403
        sub_url = f"http://127.0.0.1:{self.site_port}/sub"
        expected = FetchResult(sub_url, sub_url, 200, "text/html", "<p>Subpage</p>", b"<p>Subpage</p>", "impersonate")
        calls = []

        async def fake_fetch(_target, url, engine, conditional=None):
            calls.append((engine, conditional))
            if engine == "http":
                raise FetchError("blocked", "HTTP 403 — looks like Cloudflare bot protection", 403)
            return expected

        with mock.patch.object(self.monitor, "_fetch", side_effect=fake_fetch):
            got = await self.monitor._crawl_fetch(w, sub_url, conditional={"etag": '"v1"'})
        self.assertEqual(got.engine, "impersonate")
        self.assertEqual([c[0] for c in calls], ["http", "impersonate"])
        self.assertIsNone(calls[1][1])

    async def test_miniapp_telemetry_preview_report_export_import_and_regex_serialization(self):
        # Configure watch with ignore_patterns + authenticated proxy + custom Authorization header
        embassy_rec = self.monitor.registry.get(watch_id="embassy")
        updated_spec = dict(
            embassy_rec.spec,
            ignore_patterns=[r"^Additional registration dates"],
            proxy="socks5://user1:supersecret@127.0.0.1:40000",
            headers={"Authorization": "Bearer TOP_SECRET_HDR", "Accept-Language": "de-DE"},
        )
        self.monitor.registry.update(embassy_rec.key, updated_spec)
        await self.monitor.apply_watch(self.monitor.registry.get(key=embassy_rec.key).watch)

        # Record sample change & error events across different days for 7-day telemetry
        now = time.time()
        ev_id = self.monitor.store.add_event(
            "embassy",
            embassy_rec.spec["url"],
            "change",
            "نوبت جدید ثبت شد",
            {
                "doc_title": "گزارش سفارت",
                "header": "🔔 <b>تغییر در سفارت</b>",
                "blocks": ["🟢 نوبت جدید برای ماه آینده"],
                "full_blocks": ["🟢 نوبت جدید برای ماه آینده"],
            },
            status="sent",
        )
        err_id = self.monitor.store.add_event("embassy", None, "error", "timeout", {}, status="sent")
        with self.monitor.store.conn:
            self.monitor.store.conn.execute(
                "UPDATE events SET created = ? WHERE id = ?", (now - 2 * 86400 - 60, err_id)
            )
        buckets = self.monitor.store.daily_activity(7, watch_id="embassy", now=now)
        self.assertEqual(len(buckets), 7)
        self.assertEqual(buckets[-1]["changes"], 1)
        self.assertEqual(buckets[-3]["errors"], 1)

        async with aiohttp.ClientSession() as client:
            # 1) /api/app/state serializes compiled ignore_patterns cleanly and includes activity_7d
            async with client.get(f"{self.base}/api/app/state") as resp:
                self.assertEqual(resp.status, 200)
                st = await resp.json()
                self.assertEqual(len(st["activity_7d"]), 7)
                emb_site = next(s for s in st["sites"] if s["id"] == "embassy")
                self.assertEqual(emb_site["ignore_patterns"], [r"^Additional registration dates"])
                self.assertEqual(emb_site["proxy"], "socks5://127.0.0.1:40000")
                self.assertNotIn("supersecret", json.dumps(st))

            # 2) Saving the unchanged masked proxy server string preserves stored proxy credentials
            async with client.post(
                f"{self.base}/api/app/site/{embassy_rec.key}/update",
                json={"proxy": "socks5://127.0.0.1:40000"},
            ) as resp:
                self.assertEqual(resp.status, 200)
                preserved = self.monitor.registry.get(key=embassy_rec.key)
                self.assertEqual(preserved.watch.proxy.username, "user1")
                self.assertEqual(preserved.watch.proxy.password, "supersecret")

            # Clear proxy so direct local preview fetch succeeds against self.site_port
            async with client.post(
                f"{self.base}/api/app/site/{embassy_rec.key}/update",
                json={"proxy": ""},
            ) as resp:
                self.assertEqual(resp.status, 200)

            # 3) Live dry-run extraction preview honors draft ignore_patterns & rejects invalid regex
            async with client.post(
                f"{self.base}/api/app/site/{embassy_rec.key}/preview",
                json={"selector": "#main", "ignore_patterns": "^Additional registration"},
            ) as resp:
                self.assertEqual(resp.status, 200)
                pdata = await resp.json()
                self.assertTrue(pdata["ok"])
                self.assertGreaterEqual(pdata["line_count"], 2)
                self.assertTrue(all("Additional registration" not in ln for ln in pdata["lines"]))

            async with client.post(
                f"{self.base}/api/app/site/{embassy_rec.key}/preview",
                json={"ignore_patterns": "[unclosed-regex"},
            ) as resp:
                self.assertEqual(resp.status, 400)

            # 4) Standalone HTML report endpoint renders full interactive document
            async with client.get(f"{self.base}/api/app/event/{ev_id}/report") as resp:
                self.assertEqual(resp.status, 200)
                rdata = await resp.json()
                self.assertTrue(rdata["ok"])
                self.assertIn("نوبت جدید برای ماه آینده", rdata["html"])
                self.assertIn('id="btn-split"', rdata["html"])

            # 5) Export redacts proxy and sensitive headers by default
            self.monitor.registry.update(embassy_rec.key, updated_spec)
            async with client.get(f"{self.base}/api/app/export") as resp:
                self.assertEqual(resp.status, 200)
                ex = await resp.json()
                raw_export = json.dumps(ex)
                self.assertNotIn("supersecret", raw_export)
                self.assertNotIn("TOP_SECRET_HDR", raw_export)
                emb_ex = next(w for w in ex["bundle"]["watches"] if w["id"] == "embassy")
                self.assertEqual(emb_ex["headers"]["Authorization"], "REDACTED")
                self.assertEqual(emb_ex["headers"]["Accept-Language"], "de-DE")

            # 6) Import blocks SSRF loopback targets, deduplicates existing watches, and adds new public watches
            async with client.post(
                f"{self.base}/api/app/import",
                json={
                    "watches": [
                        {"url": "http://127.0.0.1:8899/health", "name": "SSRF Probe"},
                        {"id": "embassy", "url": "https://93.184.216.34/dup"},
                        {"id": "new_public_watch", "url": "https://93.184.216.34/appointments", "name": "پرتال جدید"},
                    ]
                },
            ) as resp:
                self.assertEqual(resp.status, 200)
                imp = await resp.json()
                self.assertEqual(imp["added"], 1)
                self.assertEqual(imp["duplicates"], 1)
                self.assertEqual(imp["invalid"], 1)
                self.assertIsNotNone(self.monitor.registry.get(watch_id="new_public_watch"))

    def test_wave6_store_thread_concurrency_lock(self):
        """Store lock protects SQLite against multithreaded concurrent queries and transactions."""
        self.assertTrue(hasattr(self.monitor.store, "_lock"))
        errors: list[Exception] = []

        def worker(wid: int):
            try:
                for i in range(25):
                    self.monitor.store.add_event(f"w_{wid}", f"https://example.com/{i}", "change", f"msg {i}", {})
                    self.monitor.store.recent_events(limit=10)
                    self.monitor.store.record_page(f"w_{wid}", f"https://example.com/{i}", digest=f"d{i}", snapshot="{}")
                    self.monitor.store.touch_page(f"w_{wid}", f"https://example.com/{i}")
                    self.monitor.store.page_rows(f"w_{wid}")
            except Exception as ex:
                errors.append(ex)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    async def test_wave6_use_case_profiles_and_live_telemetry(self):
        """API serves progressive disclosure personas and live schedule telemetry."""
        self.assertEqual(len(USE_CASE_PROFILES), 6)
        profile_ids = [p["id"] for p in USE_CASE_PROFILES]
        self.assertEqual(profile_ids, ["embassy", "exam", "official", "news", "telegram", "price_api"])

        embassy_rec = self.monitor.registry.get(watch_id="embassy")
        self.assertIsNotNone(embassy_rec)
        sched = self.monitor.schedule_info("embassy")
        self.assertIn("checking", sched)
        self.assertIn("next_due_in", sched)
        self.assertFalse(sched["checking"])

        async with aiohttp.ClientSession() as client:
            async with client.get(f"{self.base}/api/app/state") as resp:
                self.assertEqual(resp.status, 200)
                st = await resp.json()
                self.assertIn("profiles", st)
                self.assertEqual(len(st["profiles"]), 6)
                emb_site = next(s for s in st["sites"] if s["id"] == "embassy")
                self.assertIn("checking", emb_site)
                self.assertIn("next_due_in", emb_site)

    async def test_wave6_events_feed_bulk_operations_and_clone(self):
        """API endpoints: /api/app/events, /api/app/bulk, /api/app/site/{key}/clone."""
        embassy_rec = self.monitor.registry.get(watch_id="embassy")
        self.monitor.store.add_event("embassy", embassy_rec.watch.url, "change", "تغییر تستی اول", {})
        self.monitor.store.add_event("embassy", None, "error", "خطای تستی سرور", {})

        async with aiohttp.ClientSession() as client:
            # 1) Events feed with filtering
            async with client.get(f"{self.base}/api/app/events?filter=all&limit=20") as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(data["ok"])
                self.assertGreaterEqual(len(data["events"]), 2)

            async with client.get(f"{self.base}/api/app/events?filter=changes&limit=20") as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(all("change" in ev["kind"] for ev in data["events"]))

            async with client.get(f"{self.base}/api/app/events?filter=errors&limit=20") as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(all("error" in ev["kind"] for ev in data["events"]))

            # 2) Site clone creates duplicated watch
            with mock.patch("webmonitor.netguard.is_public_host", new=mock.AsyncMock(return_value=True)):
                async with client.post(f"{self.base}/api/app/site/{embassy_rec.key}/clone") as resp:
                    self.assertEqual(resp.status, 200)
                    cdata = await resp.json()
                    self.assertTrue(cdata["ok"])
                    cloned_key = cdata["key"]
                    cloned_rec = self.monitor.registry.get(key=cloned_key)
                    self.assertIsNotNone(cloned_rec)
                    self.assertIn("(کپی)", cloned_rec.spec["name"])
                    self.assertEqual(cloned_rec.watch.url, embassy_rec.watch.url)

            # 3) Bulk operations on multiple keys
            keys = [embassy_rec.key, cloned_key]
            for action, field, expected in [
                ("pause", "enabled", False),
                ("resume", "enabled", True),
                ("silent_on", "silent", True),
                ("silent_off", "silent", False),
            ]:
                async with client.post(f"{self.base}/api/app/bulk", json={"keys": keys, "action": action}) as resp:
                    self.assertEqual(resp.status, 200)
                    bdata = await resp.json()
                    self.assertEqual(bdata["affected"], 2)
                    for k in keys:
                        w = self.monitor.registry.get(key=k).watch
                        self.assertEqual(getattr(w, field), expected)

            # Bulk delete removes cloned watch
            async with client.post(f"{self.base}/api/app/bulk", json={"keys": [cloned_key], "action": "delete"}) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIsNone(self.monitor.registry.get(key=cloned_key))

    def test_wave6_miniapp_ui_components_and_invariants(self):
        """MINIAPP_HTML contains all Wave 6 UI components, SVG icons, and strict group titles."""
        self.assertIn('id="view-tab-sites"', MINIAPP_HTML)
        self.assertIn('id="view-tab-events"', MINIAPP_HTML)
        self.assertIn('id="btn-bulk-mode"', MINIAPP_HTML)
        self.assertIn('id="events-feed-panel"', MINIAPP_HTML)
        self.assertIn('id="bulk-bar"', MINIAPP_HTML)
        self.assertIn('id="add-profiles-box"', MINIAPP_HTML)
        self.assertIn('id="gs-theme-pref"', MINIAPP_HTML)
        self.assertIn('id="set-profile-preset"', MINIAPP_HTML)
        self.assertIn('id="edit-name"', MINIAPP_HTML)
        self.assertIn('id="edit-url"', MINIAPP_HTML)

        # Invariant: EXACTLY 4 group-title headers in settings: ["پایش", "اعلان‌ها", "تشخیص تغییر", "منطقهٔ خطر"]
        group_titles = re.findall(r'<div class="group-title">([^<]+)</div>', MINIAPP_HTML)
        self.assertEqual(group_titles, ["پایش", "اعلان‌ها", "تشخیص تغییر", "منطقهٔ خطر"])

    async def test_wave7_proxy_error_failover_challenge_buttons_and_nonblocking_bot_cancel(self):
        """Verify SOCKS ProxyError conversion, WARP->direct failover, loopback challenge button strip, and op:cancel."""
        from webmonitor.notifier import NotifyError, _strip_url_buttons

        # 1) _strip_url_buttons preserves callback_data buttons while stripping invalid URL/web_app buttons
        raw_markup = {
            "inline_keyboard": [
                [{"text": "🖱 کلیک خودکار", "callback_data": "+ck:tok:cf"}],
                [{"text": "✅ حل شد", "callback_data": "+ck:tok:ok"}, {"text": "❌ لغو", "callback_data": "+cc:tok"}],
                [{"text": "🛡 باز کردن لینک چالش", "url": "http://127.0.0.1:8899/c/tok"}],
            ]
        }
        cleaned = _strip_url_buttons(raw_markup)
        self.assertIsNotNone(cleaned)
        self.assertEqual(len(cleaned["inline_keyboard"]), 2)
        self.assertTrue(all("url" not in btn for row in cleaned["inline_keyboard"] for btn in row))

        # 2) _notify_challenge does not include loopback 127.0.0.1 URL button in payload["buttons"]
        fake_tg = _FakeTelegram()
        self.monitor.notifier = fake_tg
        self.monitor.store.touch_admin("777", "Admin")
        w = self.monitor.watch("embassy")
        csess = self.monitor.challenge.create(watch_id=w.id, watch_label=w.label, url=w.page_url)
        await self.monitor._notify_challenge(csess, w)
        self.assertTrue(fake_tg.texts)
        sent_markup = fake_tg.texts[-1][2] or {}
        flat_btns = [btn for row in sent_markup.get("inline_keyboard", []) for btn in row]
        self.assertTrue(any(btn.get("callback_data") == f"+ck:{csess.token}:cf" for btn in flat_btns))
        self.assertFalse(any("127.0.0.1" in (btn.get("url") or "") for btn in flat_btns))
        await self.monitor.challenge.cancel(csess.token)

        # 3) Legacy WARP proxy watch or fallback route falls back to direct when WARP raises a network error
        embassy_rec = self.monitor.registry.get(watch_id="embassy")
        warp_spec = dict(embassy_rec.spec, proxy="socks5://127.0.0.1:40000")
        self.monitor.registry.update(embassy_rec.key, warp_spec)
        await self.monitor.apply_watch(self.monitor.registry.get(key=embassy_rec.key).watch)
        warp_watch = self.monitor.registry.get(key=embassy_rec.key).watch
        res = await self.monitor.check_watch(warp_watch)
        self.assertFalse(res.startswith("error:"), f"expected WARP->direct failover, got: {res}")

        # Restore direct spec
        self.monitor.registry.update(embassy_rec.key, dict(embassy_rec.spec, proxy=None))
        await self.monitor.apply_watch(self.monitor.registry.get(key=embassy_rec.key).watch)

        # 4) AdminBot is_admin does not lock out known admin in store.admin_ids() on transient NotifyError
        bot = AdminBot(self.monitor)
        bot.tg = fake_tg
        bot.cfg.chat_ids = ["-100999"]
        fake_tg.call = mock.AsyncMock(side_effect=NotifyError("temporary network timeout"))
        self.assertTrue(await bot.is_admin("777"))
        self.assertFalse(await bot.is_admin("999999"))
        self.assertNotIn("999999", bot._admin_cache)  # transient error must not cache False

        # 5) Non-blocking slow operation cancellation via op:cancel while check_now is in-flight
        slow_gate = asyncio.Event()

        async def slow_check(_w):
            await slow_gate.wait()
            return "no change"

        with mock.patch.object(self.monitor, "check_watch", side_effect=slow_check):
            check_task = asyncio.create_task(
                bot.handle_update(
                    {
                        "update_id": 10,
                        "callback_query": {
                            "id": "cb_slow",
                            "from": {"id": 777, "first_name": "Admin"},
                            "data": f"k:{embassy_rec.key}",
                            "message": {"message_id": 10, "chat": {"id": 777, "type": "private"}},
                        },
                    }
                )
            )
            await asyncio.sleep(0.05)
            # While slow_check is still awaiting slow_gate, pressing op:cancel cancels it immediately
            await asyncio.wait_for(
                bot.handle_update(
                    {
                        "update_id": 11,
                        "callback_query": {
                            "id": "cb_cancel",
                            "from": {"id": 777, "first_name": "Admin"},
                            "data": f"op:cancel:{embassy_rec.key}",
                            "message": {"message_id": 11, "chat": {"id": 777, "type": "private"}},
                        },
                    }
                ),
                timeout=2.0,
            )
            await asyncio.wait_for(check_task, timeout=2.0)
        self.assertTrue(any("عملیات قبلی لغو شد" in t[1] for t in fake_tg.texts) or
                        any("عملیات قبلی لغو شد" in e[2] for e in fake_tg.edits))

    async def test_wave8_secure_by_default_package_log_redaction_and_challenge_semaphore_guard(self):
        """Verify SEC-01 default package redaction, SEC-02 JsonFormatter scrubbing, REL-01 semaphore finally guard, PAR-09, and DATA-01."""
        import logging
        from webmonitor.logfmt import JsonFormatter

        # 1) SEC-01 & PAR-09: package command redacts by default and includes DESIGN.md + AGENTS.md
        self.assertIn("DESIGN.md", cli.PACKAGE_ITEMS)
        self.assertIn("AGENTS.md", cli.PACKAGE_ITEMS)
        parsed_default = cli.build_parser().parse_args(["package"])
        self.assertTrue(parsed_default.redact_secrets)
        self.assertFalse(parsed_default.include_secrets)
        parsed_include = cli.build_parser().parse_args(["package", "--include-secrets"])
        self.assertTrue(parsed_include.include_secrets)

        install_sh = (ROOT / "deploy" / "install_service.sh").read_text(encoding="utf-8")
        self.assertIn("DESIGN.md", install_sh)
        self.assertIn("diagnose URL", install_sh)
        self.assertIn("package [--include-secrets]", install_sh)

        # 2) SEC-02: JsonFormatter scrubs Telegram tokens and proxy credentials in msg, extra, and tracebacks
        fmt = JsonFormatter()
        fake_token = "123456789:AAH_super_secret_bot_token_value_99"
        fake_proxy = "socks5://user1:my_secret_pass@127.0.0.1:40000"
        try:
            raise RuntimeError(f"POST https://api.telegram.org/bot{fake_token}/sendMessage via {fake_proxy} failed")
        except RuntimeError:
            rec = logging.LogRecord(
                name="webmonitor.test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg=f"[embassy] error with token {fake_token} and proxy {fake_proxy}",
                args=(),
                exc_info=sys.exc_info(),
            )
            rec.endpoint = f"https://api.telegram.org/bot{fake_token}/getUpdates"
            formatted = fmt.format(rec)
        self.assertNotIn(fake_token, formatted)
        self.assertNotIn("my_secret_pass", formatted)
        self.assertIn("<REDACTED_TOKEN>", formatted)
        self.assertIn("socks5://user1:<REDACTED>@127.0.0.1:40000", formatted)

        # 3) REL-01: BrowserFetcher.open_challenge releases _challenge_sem and counters even on CancelledError
        bf = self.monitor.browser
        initial_active = bf._active
        initial_ch_active = bf._challenges_active
        initial_sem_val = bf._challenge_sem._value

        fake_context = mock.AsyncMock()
        fake_context.set_default_timeout = mock.MagicMock()
        fake_page = mock.AsyncMock()
        fake_page.url = "https://example.com/"
        fake_context.new_page = mock.AsyncMock(return_value=fake_page)
        fake_browser = mock.AsyncMock()
        fake_browser.new_context = mock.AsyncMock(return_value=fake_context)

        with mock.patch.object(bf, "_ensure", new=mock.AsyncMock(return_value=fake_browser)), \
             mock.patch("webmonitor.fetchers.is_public_host", new=mock.AsyncMock(return_value=False)), \
             mock.patch("webmonitor.fetchers.ChallengeBrowser.goto_and_settle", new=mock.AsyncMock(side_effect=asyncio.CancelledError())):
            with self.assertRaises(asyncio.CancelledError):
                await bf.open_challenge("http://127.0.0.1:8000/", self.monitor.watch("embassy"))

        self.assertEqual(bf._active, initial_active)
        self.assertEqual(bf._challenges_active, initial_ch_active)
        self.assertEqual(bf._challenge_sem._value, initial_sem_val)
        fake_context.close.assert_awaited()

        # 4) DATA-01: cmd_history --show uses store.get_event
        ev_id = self.monitor.store.add_event(
            "embassy",
            "https://example.com",
            "change",
            "تغییر تستی تاریخچه",
            {"header": "<b>گزارش تست</b>", "blocks": ["بخش اول"]},
        )
        hist_args = argparse.Namespace(show=ev_id, watch=None, limit=10)
        buf = io.StringIO()
        with mock.patch.object( Store, "get_event", wraps=self.monitor.store.get_event) as spy_get_event, \
             contextlib.redirect_stdout(buf):
            rc = cli.cmd_history(self.monitor.config, hist_args)
        self.assertEqual(rc, 0)
        spy_get_event.assert_called_once_with(ev_id)
        self.assertIn("گزارش تست", buf.getvalue())

    async def test_wave9_track2_compressed_telegram_backup_domain_crawl_cap_and_async_housekeeping(self):
        """Verify Track 2 (BUILDQUICKWINS): compressed .db.zip + export.json Telegram backup, <=2 per-domain crawl cap with jitter, and async housekeeping."""
        import zipfile
        from webmonitor import engine as eng_mod

        # 1) Compressed Telegram backup (.db.zip + watches-*.json)
        docs_sent = []
        texts_sent = []

        class _FakeBackupNotifier:
            async def send_document(self, chat_id, filename, content, caption, silent=False, content_type="text/html"):
                docs_sent.append({
                    "chat_id": chat_id,
                    "filename": filename,
                    "content": content,
                    "caption": caption,
                    "silent": silent,
                    "content_type": content_type,
                })

            async def send_text(self, chat_id, text, silent=False, reply_markup=None):
                texts_sent.append((chat_id, text))

        old_notifier = self.monitor.notifier
        self.monitor.notifier = _FakeBackupNotifier()
        try:
            ok = await self.monitor.send_telegram_backup(chat_ids=["777"], silent=False)
            self.assertTrue(ok)
            self.assertEqual(len(docs_sent), 2)
            zip_doc, json_doc = docs_sent[0], docs_sent[1]
            self.assertTrue(zip_doc["filename"].endswith(".db.zip"))
            self.assertEqual(zip_doc["content_type"], "application/zip")
            with zipfile.ZipFile(io.BytesIO(zip_doc["content"]), "r") as zf:
                names = zf.namelist()
                self.assertEqual(len(names), 1)
                self.assertTrue(names[0].endswith(".db"))
            self.assertTrue(json_doc["filename"].startswith("watches-") and json_doc["filename"].endswith(".json"))
            self.assertEqual(json_doc["content_type"], "application/json")
            exported = json.loads(json_doc["content"].decode("utf-8"))
            self.assertIn("watches", exported)
            self.assertGreaterEqual(len(exported["watches"]), 1)

            # Verify <48 MB size guard falls back to warning + lightweight export.json
            docs_sent.clear()
            texts_sent.clear()
            with mock.patch.object(eng_mod, "TELEGRAM_BACKUP_MAX_BYTES", 10):
                ok2 = await self.monitor.send_telegram_backup(chat_ids=["777"], silent=True)
            self.assertTrue(ok2)
            self.assertEqual(len(texts_sent), 1)
            self.assertIn("بیشتر از سقف ارسال ربات تلگرام", texts_sent[0][1])
            self.assertEqual(len(docs_sent), 1)
            self.assertTrue(docs_sent[0]["filename"].endswith(".json"))
        finally:
            self.monitor.notifier = old_notifier

        # 2) Per-domain crawl concurrency cap (<= 2) and jitter in _crawl_fetch
        w = self.monitor.watch("embassy")
        in_flight = 0
        max_seen = 0
        sleep_calls = []

        async def _fake_fetch(target, url, candidate, conditional=None):
            nonlocal in_flight, max_seen
            in_flight += 1
            max_seen = max(max_seen, in_flight)
            await asyncio.sleep(0.03)
            in_flight -= 1
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                content_type="text/html",
                text="<html><body>ok</body></html>",
                body=b"<html><body>ok</body></html>",
                etag=None,
                last_modified=None,
                not_modified=False,
                engine=candidate,
                elapsed=0.01,
            )

        real_sleep = asyncio.sleep

        async def _spy_sleep(delay):
            if 0.05 <= delay <= 0.40:
                sleep_calls.append(delay)
                await real_sleep(0.005)
            else:
                await real_sleep(delay)

        with mock.patch.object(self.monitor, "_fetch", side_effect=_fake_fetch), \
             mock.patch("webmonitor.engine.asyncio.sleep", side_effect=_spy_sleep):
            await asyncio.gather(*(
                self.monitor._crawl_fetch(w, f"https://diplo.example.de/sub/{i}")
                for i in range(6)
            ))

        self.assertLessEqual(max_seen, 2)
        self.assertEqual(len(sleep_calls), 6)

    async def test_wave10_phase1a_active_challenges_post_captcha_retry_finally_and_split_regex(self):
        """Phase 1-A: _active_challenges uses ChallengeSession.expired/created_at, post-CAPTCHA retry uses
        impersonate->browser without locking engine, _maybe_solve_challenge closes cb on CancelledError,
        and report.py buildSplitHtml regex transforms real render_hunk output."""
        from webmonitor.bot import AdminBot
        from webmonitor.report import Hunk, render_document, render_hunk

        w = self.monitor.watch("embassy")
        bot = AdminBot(self.monitor)

        # 1) bot._active_challenges detects real ChallengeSession and excludes expired ones
        sess = self.monitor.challenge.create(watch_id=w.id, watch_label=w.label, url=w.page_url)
        try:
            active_all = bot._active_challenges()
            active_w = bot._active_challenges(w.id)
            self.assertEqual(len(active_all), 1)
            self.assertEqual(active_w[0].token, sess.token)
            self.assertEqual(bot._active_challenges("other_watch"), [])

            # Expire the session and ensure it disappears
            sess.created_at = time.time() - (sess.ttl + 10)
            self.assertEqual(bot._active_challenges(w.id), [])
        finally:
            await self.monitor.challenge.cancel(sess.token)

        # 2) Post-CAPTCHA retry in _fetch_parse: tries impersonate first, then browser, never http,
        # and does NOT permanently persist engine="browser" in watch_state
        self.monitor.store.update_watch(w.id, engine=None)
        self.monitor._challenge_ready = True
        retry_engines = []

        async def _fake_fetch(target, url, candidate, conditional=None, wait_for=""):
            retry_engines.append(candidate)
            if candidate == "impersonate":
                raise FetchError("blocked", "still blocked on impersonate", status=403)
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                content_type="text/html",
                text="<html><body>ok after captcha</body></html>",
                body=b"<html><body>ok after captcha</body></html>",
                etag=None,
                last_modified=None,
                not_modified=False,
                engine=candidate,
                elapsed=0.05,
            )

        with mock.patch.object(self.monitor, "_engine_chain", new=mock.AsyncMock(side_effect=FetchError("blocked", "cf", status=403))), \
             mock.patch.object(self.monitor, "_maybe_solve_challenge", new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(self.monitor.impersonate, "supports", return_value=True), \
             mock.patch.object(self.monitor.browser, "supports", return_value=True), \
             mock.patch.object(self.monitor, "_fetch", side_effect=_fake_fetch):
            res, parsed = await self.monitor._fetch_parse(w, w.url, lambda r: ("parsed", r.engine))

        self.assertEqual(retry_engines, ["impersonate", "browser"])
        self.assertEqual(parsed, ("parsed", "browser"))
        # Must NOT permanently lock the watch's engine to "browser"
        self.assertIsNone(self.monitor.store.watch_state(w.id).get("engine"))

        # 3) _maybe_solve_challenge closes cb and cleans up session even on CancelledError (and swallows close errors)
        fake_cb = mock.AsyncMock()
        fake_cb.frame = mock.AsyncMock(return_value=b"")
        fake_cb.close = mock.AsyncMock(side_effect=RuntimeError("close boom"))
        self.monitor.store.set_setting(f"challenge_cooldown:{w.id}", "0")

        with mock.patch.object(self.monitor.browser, "open_challenge", new=mock.AsyncMock(return_value=fake_cb)), \
             mock.patch.object(self.monitor, "_notify_challenge", new=mock.AsyncMock()), \
             mock.patch.object(type(self.monitor.browser), "available", new_callable=mock.PropertyMock, return_value=True):
            task = asyncio.create_task(self.monitor._maybe_solve_challenge(w, w.url, FetchError("blocked", "cf", status=403)))
            await asyncio.sleep(0.05)
            self.assertEqual(self.monitor.challenge.count(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        fake_cb.close.assert_awaited_once()
        self.assertEqual(self.monitor.challenge.count(), 0)

        # 4) report.py buildSplitHtml regex matches real render_hunk output for side_by_side & before_after
        hunk = Hunk(kind="modify", old="قیمت قدیم ۱۰۰", new="قیمت جدید ۲۰۰")
        sbs_html = render_hunk(hunk, full=True, style="side_by_side")
        ba_html = render_hunk(hunk, full=True, style="before_after")
        doc_html = render_document("تست", "هدر", [sbs_html, ba_html])
        m_re = re.search(r"function buildSplitHtml\(html\)\{return html\.replace\((/.+?/g),", doc_html)
        self.assertIsNotNone(m_re)
        js_pattern = m_re.group(1)[1:-2]  # strip leading / and trailing /g
        py_re = re.compile(js_pattern)
        self.assertIsNotNone(py_re.search(sbs_html), f"regex failed to match side_by_side: {sbs_html!r}")
        self.assertIsNotNone(py_re.search(ba_html), f"regex failed to match before_after: {ba_html!r}")

    async def test_wave10_phase1b_scoped_download_token_clone_name_and_ui_contracts(self):
        """Phase 1-B: scoped reusable download token (rejected on other endpoints/files, works in local loopback
        with admins in DB), /clone returns name, and miniapp_ui.py matches backend canonical fields."""
        from urllib.parse import parse_qs, urlsplit
        from webmonitor.miniapp import (
            DOWNLOAD_TOKEN_TTL,
            make_download_token,
            miniapp_secret,
            verify_admin_token,
            verify_download_token,
        )
        from webmonitor.miniapp_ui import MINIAPP_HTML

        # 1) Token unit checks: scoped, reusable, never accepted as admin token, expires properly
        secret = miniapp_secret(self.monitor.store)
        now = time.time()
        tok = make_download_token(secret, "777", "shot:1:" + "a" * 64, now=now)
        self.assertTrue(tok.startswith("dl."))
        self.assertEqual(verify_download_token(tok, secret, "shot:1:" + "a" * 64, now=now + 60), "777")
        self.assertEqual(verify_download_token(tok, secret, "shot:1:" + "a" * 64, now=now + 120), "777")  # reusable
        self.assertIsNone(verify_download_token(tok, secret, "shot:2:" + "a" * 64, now=now + 60))       # wrong site
        self.assertIsNone(verify_download_token(tok, secret, "shot:1:" + "b" * 64, now=now + 60))       # wrong digest
        self.assertIsNone(verify_download_token(tok, secret, "shot:1:" + "a" * 64, now=now + DOWNLOAD_TOKEN_TTL + 5))
        self.assertIsNone(verify_admin_token(tok, secret, now=now + 60))  # cannot be used as X-Admin-Token

        # 2) Live HTTP tests: screenshot download in local loopback mode even with admins in DB,
        # rejection as X-Admin-Token, and /clone returning "name"
        self.monitor.store.touch_admin("777", "Admin")
        rec = self.monitor.registry.get(watch_id="embassy")
        fake_jpeg = b"\xff\xd8\xff\xe0FAKEJPEGDATA"

        async with aiohttp.ClientSession() as client:
            with mock.patch.object(self.monitor, "screenshot", new=mock.AsyncMock(return_value=fake_jpeg)):
                async with client.post(
                    f"{self.base}/api/app/site/{rec.key}/screenshot",
                    json={},
                    headers={"Origin": self.base},
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    shot_data = await resp.json()

            dl_url = shot_data["download_url"]
            dl_token = parse_qs(urlsplit(dl_url).query).get("t", [""])[0]
            self.assertTrue(dl_token.startswith("dl."))

            # Reusable download (twice in a row — e.g. preview + mobile download manager)
            for _ in range(2):
                async with client.get(f"{self.base}{dl_url}") as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(await resp.read(), fake_jpeg)
                    self.assertIn("attachment;", resp.headers.get("Content-Disposition", ""))

            # Token is rejected for a different digest when bot token auth is active
            old_tok = self.monitor.config.telegram.token
            self.monitor.config.telegram.token = "123456:TESTTOKEN"
            try:
                bad_digest = "0" * 64
                async with client.get(f"{self.base}/api/app/site/{rec.key}/screenshot/{bad_digest}.jpg?t={dl_token}") as resp:
                    self.assertEqual(resp.status, 403)
                async with client.get(f"{self.base}/api/app/state", headers={"X-Admin-Token": dl_token}) as resp:
                    self.assertEqual(resp.status, 403)
            finally:
                self.monitor.config.telegram.token = old_tok

            # /clone returns "name"
            with mock.patch("webmonitor.miniapp.netguard.is_public_host", new=mock.AsyncMock(return_value=True)):
                async with client.post(
                    f"{self.base}/api/app/site/{rec.key}/clone",
                    json={"name": "سفارت کپی"},
                    headers={"Origin": self.base},
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    clone_data = await resp.json()
                    self.assertEqual(clone_data.get("name"), "سفارت کپی")
                    self.monitor.registry.delete(clone_data["key"])

        # 3) UI contract checks in MINIAPP_HTML
        for expected in (
            "ev.site_label",
            "ev.created_human",
            "ev.summary",
            "ev.has_report",
            "p.type_hint",
            "addSitePending",
            "origHtml",
            "askConfirm",
            "scrollIntoView",
            "stopChallengeTimers",
            "uptime_human: \"\"",
        ):
            self.assertIn(expected, MINIAPP_HTML)

    async def test_wave11_phase2a_config_utf16_notifier_bot_reset_confirm_and_cookie_delete(self):
        """Phase 2-A: config rejects NaN/Inf/ftp proxy/invalid header names; notifier counts UTF-16 and
        handles 'too long' 400; bot confirms rs: before reset and deletes cookie messages safely."""
        from webmonitor.bot import AdminBot
        from webmonitor.config import ConfigError, Proxy, parse_watch
        from webmonitor.fetchers import has_watch_cookies, import_watch_cookies
        from webmonitor.notifier import TelegramApiError, TelegramNotifier, build_parts, utf16_len

        # 1) config.py: NaN/Infinity, proxy schemes/types, HTTP header token names
        with self.assertRaises(ConfigError):
            parse_watch({"id": "nan_w", "url": "https://example.com", "interval_seconds": float("nan")})
        with self.assertRaises(ConfigError):
            parse_watch({"id": "inf_w", "url": "https://example.com", "timeout_seconds": float("inf")})
        with self.assertRaises(ConfigError):
            Proxy.parse("ftp://proxy.example:21", "proxy")
        with self.assertRaises(ConfigError):
            Proxy.parse({"server": "http://proxy.example:8080", "username": {"bad": 1}}, "proxy")
        with self.assertRaises(ConfigError):
            parse_watch({"id": "hdr_w", "url": "https://example.com", "headers": {"Bad Name": "ok"}})
        with self.assertRaises(ConfigError):
            parse_watch({"id": "hdr_w2", "url": "https://example.com", "headers": {"Bad:Name": "ok"}})
        self.assertEqual(Proxy.parse("socks5://127.0.0.1:40000", "proxy").scheme, "socks5")
        ok_w = parse_watch({"id": "ok_w", "url": "https://example.com", "headers": {"X-Custom-Token": "abc123"}})
        self.assertEqual(ok_w.headers["X-Custom-Token"], "abc123")

        # 2) notifier.py: UTF-16 counting & "too long" 400 fallback
        self.assertEqual(utf16_len("🟢"), 2)
        self.assertEqual(utf16_len("سلام"), 4)
        emoji_block = "🟢 " + ("🟡" * 1000)  # 1002 code points, 2002 UTF-16 units
        parts = build_parts({"header": "هدر", "blocks": [emoji_block, emoji_block], "doc_title": "تست"}, limit=2100)
        text_parts = [content for kind, content in parts if kind == "text"]
        self.assertGreaterEqual(len(text_parts), 2)
        for chunk in text_parts:
            self.assertLessEqual(utf16_len(chunk), 2100)

        tg_cfg = self.monitor.config.telegram
        tn = TelegramNotifier(tg_cfg)
        calls = []

        async def _fake_call(method, payload=None, files=None, timeout=30):
            calls.append((method, dict(payload or {})))
            if len(calls) == 1:
                raise TelegramApiError(400, "Bad Request: message is too long")
            return {"message_id": 42}

        tn.call = _fake_call
        res = await tn.send_text("123", "<b>" + ("🟢" * 100) + "</b>")
        self.assertEqual(res.get("message_id"), 42)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("parse_mode", calls[1][1])

        # 3) bot.py: rs: asks confirmation without wiping cookies; rsy: performs reset; cookie message auto-deleted safely
        rec = self.monitor.registry.get(watch_id="embassy")
        import_watch_cookies(self.monitor.config.data_dir, rec.id, "cf_clearance=secret123", rec.watch.url)
        self.assertTrue(has_watch_cookies(self.monitor.config.data_dir, rec.id))

        bot = AdminBot(self.monitor)
        deleted_mids = []

        class _FakeBotTg:
            def __init__(self):
                self.texts = []
                self.fail_delete = False

            async def send_text(self, chat_id, text, silent=False, reply_markup=None):
                self.texts.append((chat_id, text, reply_markup))
                return {"message_id": 99}

            async def edit_text(self, chat_id, mid, text, reply_markup=None):
                self.texts.append((chat_id, text, reply_markup))

            async def answer_callback(self, cid, text="", alert=False):
                pass

            async def call(self, method, payload=None, files=None, timeout=30):
                if method == "deleteMessage":
                    if self.fail_delete:
                        raise NotifyError("message can't be deleted")
                    deleted_mids.append(payload.get("message_id"))
                return {}

        fake_tg = _FakeBotTg()
        bot.tg = fake_tg
        ctx = mock.AsyncMock()

        # Tapping rs:{key} must NOT wipe cookies yet — only ask confirmation
        await bot._handle_callback(ctx, "111", None, "111", f"rs:{rec.key}")
        self.assertTrue(has_watch_cookies(self.monitor.config.data_dir, rec.id))
        self.assertIn("پاک شود؟", fake_tg.texts[-1][1])

        # Tapping rsy:{key} performs the actual reset
        await bot._handle_callback(ctx, "111", None, "111", f"rsy:{rec.key}")
        self.assertFalse(has_watch_cookies(self.monitor.config.data_dir, rec.id))

        # Sending cookie message auto-deletes the message
        sess = bot._session("111")
        sess.ask(f"cookies:{rec.key}")
        await bot._handle_input("111", "111", sess, "session_id=abc999", message_id=501)
        self.assertTrue(has_watch_cookies(self.monitor.config.data_dir, rec.id))
        self.assertEqual(deleted_mids, [501])

        # Even if Telegram forbids deleteMessage, cookie import still succeeds cleanly
        fake_tg.fail_delete = True
        sess.ask(f"cookies:{rec.key}")
        await bot._handle_input("111", "111", sess, "session_id=xyz888", message_id=502)
        self.assertTrue(has_watch_cookies(self.monitor.config.data_dir, rec.id))

        # 4) AGENTS.md matches netguard.py (GuardedResolver, not PinnedResolver)
        agents_md = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("GuardedResolver", agents_md)
        self.assertNotIn("PinnedResolver", agents_md)

    async def test_wave11_phase2b_impersonate_streaming_cookie_isolation_and_challenge_lock_ratelimit(self):
        """Phase 2-B: real local HTTP server tests for ImpersonateFetcher stream=True (plain, gzip, chunked
        oversize abort), HttpFetcher + ImpersonateFetcher cookie isolation + Wave 1 save_storage_state sync,
        ChallengeManager solving_lock capture serialization & non-blocking cancel, and Nginx X-Real-IP rate limit."""
        import gzip
        from aiohttp import web
        from webmonitor.config import Watch

        # 1) Start a real local HTTP server for streaming + gzip + cookie-isolation tests
        async def handle_plain(_req):
            return web.Response(text="<html><body>سلام آلمان — ÄÖÜß</body></html>", content_type="text/html")

        async def handle_gzip(_req):
            raw = "<html><body>محتوای فشرده gzip — Termin verfügbar</body></html>".encode("utf-8")
            return web.Response(
                body=gzip.compress(raw),
                headers={"Content-Type": "text/html; charset=utf-8", "Content-Encoding": "gzip"},
            )

        async def handle_huge(req):
            resp = web.StreamResponse(status=200, headers={"Content-Type": "text/plain"})
            await resp.prepare(req)
            chunk = b"X" * 16384
            try:
                for _ in range(20):  # 320 KB chunked without Content-Length
                    await resp.write(chunk)
                    await asyncio.sleep(0.002)
                await resp.write_eof()
            except (ConnectionResetError, asyncio.CancelledError):
                pass
            return resp

        async def handle_set_cookie(_req):
            resp = web.Response(text="<html><body>cookie set</body></html>", content_type="text/html")
            resp.set_cookie("watch_a_secret", "TOPSECRET_A")
            return resp

        async def handle_echo_cookie(req):
            return web.Response(text=f"<html><body>COOKIES:{req.headers.get('Cookie', '')}</body></html>",
                                content_type="text/html")

        app = web.Application()
        app.router.add_get("/plain", handle_plain)
        app.router.add_get("/gzip", handle_gzip)
        app.router.add_get("/huge", handle_huge)
        app.router.add_get("/set-cookie", handle_set_cookie)
        app.router.add_get("/echo-cookie", handle_echo_cookie)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        watch_a = Watch(id="iso_watch_a", url=f"{base}/plain", timeout_seconds=10)
        watch_b = Watch(id="iso_watch_b", url=f"{base}/plain", timeout_seconds=10)
        try:
            # 1a) HttpFetcher cookie isolation (DummyCookieJar)
            await self.monitor.http.fetch(f"{base}/set-cookie", watch_a)
            res_http_b = await self.monitor.http.fetch(f"{base}/echo-cookie", watch_b)
            self.assertNotIn("TOPSECRET_A", res_http_b.text)

            # 1b) ImpersonateFetcher stream=True: plain, gzip, chunked oversize abort, cookie isolation & Wave 1 sync
            if self.monitor.impersonate.available:
                res_plain = await self.monitor.impersonate.fetch(f"{base}/plain", watch_a)
                self.assertIn("سلام آلمان — ÄÖÜß", res_plain.text)

                res_gz = await self.monitor.impersonate.fetch(f"{base}/gzip", watch_a)
                self.assertIn("محتوای فشرده gzip — Termin verfügbar", res_gz.text)

                with self.assertRaises(FetchError) as cm_big:
                    await self.monitor.impersonate.fetch(f"{base}/huge", watch_a, max_bytes=32768)
                self.assertEqual(cm_big.exception.kind, "too_large")

                # Cookie isolation between watch_a and watch_b on ImpersonateFetcher
                await self.monitor.impersonate.fetch(f"{base}/set-cookie", watch_a)
                res_imp_b = await self.monitor.impersonate.fetch(f"{base}/echo-cookie", watch_b)
                self.assertNotIn("TOPSECRET_A", res_imp_b.text)

                # Wave 1 compatibility: BrowserFetcher.save_storage_state syncs solved cookies to watch_a only
                solved_state = json.dumps({
                    "cookies": [{"name": "cf_clearance", "value": "SOLVED_BY_BROWSER", "domain": "127.0.0.1", "path": "/"}]
                }).encode("utf-8")
                self.monitor.browser.save_storage_state(watch_a, solved_state)
                res_imp_a_after = await self.monitor.impersonate.fetch(f"{base}/echo-cookie", watch_a)
                self.assertIn("cf_clearance=SOLVED_BY_BROWSER", res_imp_a_after.text)
                res_imp_b_after = await self.monitor.impersonate.fetch(f"{base}/echo-cookie", watch_b)
                self.assertNotIn("SOLVED_BY_BROWSER", res_imp_b_after.text)
        finally:
            await runner.cleanup()

        # 2) ChallengeManager solving_lock capture serialization & non-blocking cancel
        cm = self.monitor.challenge
        sess = cm.create(watch_id="embassy", watch_label="Embassy", url="https://example.com")
        capture_calls = 0

        async def _slow_frame():
            nonlocal capture_calls
            capture_calls += 1
            await asyncio.sleep(0.05)
            return b"\xff\xd8FRAME"

        sess.frame_fn = _slow_frame
        f1, f2 = await asyncio.gather(cm.capture_frame(sess), cm.capture_frame(sess))
        self.assertEqual(f1, b"\xff\xd8FRAME")
        self.assertEqual(f2, b"\xff\xd8FRAME")
        self.assertEqual(capture_calls, 1)  # serialized & deduplicated via solving_lock

        # cancel() must NOT deadlock even when solving_lock is currently held
        async with sess.solving_lock:
            cancelled = await asyncio.wait_for(cm.cancel(sess.token), timeout=1.0)
            self.assertTrue(cancelled)

        # 3) Nginx X-Real-IP trust only on loopback + valid tokens exempt from rate-limit
        fake_loopback_req = mock.MagicMock(remote="127.0.0.1", headers={"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "1.1.1.1"})
        self.assertEqual(cm._client_ip(fake_loopback_req), "203.0.113.5")
        fake_ext_req = mock.MagicMock(remote="198.51.100.9", headers={"X-Real-IP": "9.9.9.9"})
        self.assertEqual(cm._client_ip(fake_ext_req), "198.51.100.9")

        valid_sess = cm.create(watch_id="embassy", watch_label="Embassy", url="https://example.com")
        try:
            async with aiohttp.ClientSession() as client:
                # Exhaust invalid-token rate limit from one IP
                for _ in range(21):
                    await client.get(f"{self.base}/c/invalid_token_xyz", headers={"X-Real-IP": "203.0.113.99"})
                async with client.get(f"{self.base}/c/invalid_token_xyz", headers={"X-Real-IP": "203.0.113.99"}) as r429:
                    self.assertEqual(r429.status, 429)
                # Valid active token from the SAME IP must still work (never locked out!)
                async with client.get(f"{self.base}/c/{valid_sess.token}", headers={"X-Real-IP": "203.0.113.99"}) as r200:
                    self.assertEqual(r200.status, 200)
        finally:
            await cm.cancel(valid_sess.token)


if __name__ == "__main__":
    unittest.main()

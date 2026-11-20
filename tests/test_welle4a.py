"""Tests for "Welle 4A": the Mini App front end (miniapp_ui.py) and the API fields behind it.

The browser tests open the real page in Chromium (through patchright, which the project already uses). They are
skipped when no browser is available or when WEBMONITOR_SKIP_BROWSER is set. Set WEBMONITOR_CHROME to the path
of a Chrome/Chromium binary to use a specific one.

Run from the project folder:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import aiohttp
from aiohttp import web

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from test_welle2 import BASE, RELAUNCH, page  # noqa: E402

from webmonitor import miniapp, miniapp_ui  # noqa: E402
from webmonitor.config import parse_config  # noqa: E402
from webmonitor.engine import Monitor  # noqa: E402
from webmonitor.extract import page_snapshot, parse_html  # noqa: E402
from webmonitor.fetchers import FetchResult  # noqa: E402

SKIP_BROWSER = bool(os.environ.get("WEBMONITOR_SKIP_BROWSER"))


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def serve(pages: dict, status: dict):
    app = web.Application()
    for name in pages:
        async def handler(request, name=name):
            return web.Response(text=pages[name], status=status.get(name, 200), content_type="text/html")

        app.router.add_get(f"/{name}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]


def watch_spec(port: int, wid: str, label: str, path: str, **extra) -> dict:
    return {"id": wid, "name": label, "url": f"http://127.0.0.1:{port}/{path}", "selector": "#main", "engine": "http",
            "min_content_length": 1, "error_threshold": 2, "interval_seconds": 600, **extra}


class MiniAppCase(unittest.IsolatedAsyncioTestCase):
    """A monitor with five sites in different states: failing, redesigned, changed, healthy, paused."""

    sites = True

    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="webmonitor-w4a-"))
        self.pages = {"embassy": page(BASE),
                      "goethe": page([f"Goethe B1 | Teheran | {10 + i}.12.2026 | Plätze: {i % 5}" for i in range(24)],
                                     heads=("Prüfungstermine",)),
                      "news": page(BASE[:12], heads=("Aktuelles",)), "broken": page(BASE[:5]), "paused": page(BASE[:5])}
        self.status = {}
        self.runner, self.port = await serve(self.pages, self.status)
        self.cport = free_port()
        watches = []
        if self.sites:
            watches = [watch_spec(self.port, "embassy", "سفارت آلمان — بخش ویزا", "embassy"),
                       watch_spec(self.port, "goethe", "Goethe-Institut Teheran — آزمون B1", "goethe"),
                       watch_spec(self.port, "news", "اخبار کنسولگری", "news"),
                       watch_spec(self.port, "broken", "پرتال نوبت‌دهی (خراب)", "broken"),
                       watch_spec(self.port, "paused", "سایت متوقف‌شده", "paused", enabled=False)]
        cfg = parse_config({"data_dir": str(self.tmp / "data"), "notify_startup": False, "daily_report_hour": None,
                            "challenge_port": self.cport, "watches": watches}, self.tmp / "cfg.json")
        self.monitor = Monitor(cfg, dry_run=True)
        await self.monitor.start()
        self.base = f"http://127.0.0.1:{self.cport}"
        if self.sites:
            with contextlib.redirect_stdout(io.StringIO()):
                for wid in ("embassy", "goethe", "news", "broken"):
                    await self.monitor.check_watch(self.monitor.watch(wid))
                self.pages["embassy"] = page(BASE[:20] + ["Termin 20: GEÄNDERT neue Zeit 10:30 Uhr"] + BASE[21:40]
                                             + ["NEU: Zusatztermin am 30.11.2026"] + BASE[41:])
                self.pages["goethe"] = page(RELAUNCH[:30], heads=("Neues Portal",))
                self.status["broken"] = 503
                for wid in ("embassy", "goethe", "broken", "broken"):
                    await self.monitor.check_watch(self.monitor.watch(wid))
                await self.monitor.dispatch_pending()

    async def asyncTearDown(self):
        await self.monitor.close()
        await self.runner.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def get(self, path: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(self.base + path) as resp:
                return resp.status, await resp.json()

    async def post(self, path: str, body: dict | None = None):
        async with aiohttp.ClientSession() as session:
            async with session.post(self.base + path, json=body or {}) as resp:
                return resp.status, await resp.json()

    async def state(self) -> dict:
        status, data = await self.get("/api/app/state")
        self.assertEqual(status, 200)
        return data

    @staticmethod
    def by_id(state: dict, wid: str) -> dict:
        return next(s for s in state["sites"] if s["id"] == wid)


# =========================================================================== API fields and the new route

class ApiTests(MiniAppCase):
    async def test_the_page_comes_from_the_ui_module(self):
        self.assertIs(miniapp._MINIAPP_HTML, miniapp_ui.MINIAPP_HTML)
        async with aiohttp.ClientSession() as session:
            async with session.get(self.base + "/app") as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("<!doctype html>", (await resp.text()).lower())

    async def test_sites_carry_the_fields_the_list_needs(self):
        state = await self.state()
        goethe, embassy, news = (self.by_id(state, w) for w in ("goethe", "embassy", "news"))
        self.assertEqual(goethe["drift"]["level"], "redesign")
        self.assertGreater(goethe["last_change_ts"], 0)
        self.assertIsNone(embassy["drift"])
        self.assertEqual(news["last_change_ts"], 0)
        self.assertIsNone(embassy["suggestion"])

    async def test_state_contains_the_health_report(self):
        health = (await self.state())["health"]
        self.assertIn(health["status"], ("ok", "degraded"))
        self.assertEqual(health["watches"]["failing"], 1)
        self.assertEqual(health["drift"][0]["watch"], "goethe")

    async def test_a_failing_health_report_does_not_break_the_dashboard(self):
        with mock.patch("webmonitor.miniapp.build_health", side_effect=RuntimeError("boom")):
            state = await self.state()
        self.assertIsNone(state["health"])
        self.assertEqual(len(state["sites"]), 5)

    async def test_events_name_their_drift_level(self):
        state = await self.state()
        status, data = await self.get(f"/api/app/site/{self.by_id(state, 'goethe')['key']}")
        self.assertEqual(status, 200)
        self.assertEqual(data["events"][0]["drift_level"], "redesign")
        data = (await self.get(f"/api/app/site/{self.by_id(state, 'embassy')['key']}"))[1]
        self.assertEqual(data["events"][0]["drift_level"], "")


class SuggestionTests(MiniAppCase):
    async def lose_the_selector(self, wid: str = "embassy") -> str:
        self.pages[wid] = page(BASE, root="section id='content'")
        with contextlib.redirect_stdout(io.StringIO()):
            return await self.monitor.check_watch(self.monitor.watch(wid))

    async def test_a_lost_selector_leaves_a_suggestion_that_is_cleared_when_parsing_works_again(self):
        outcome = await self.lose_the_selector()
        self.assertIn("#content", outcome)
        self.assertEqual(self.monitor._suggestions["embassy"]["selector"], "#content")
        self.pages["embassy"] = page(BASE)
        with contextlib.redirect_stdout(io.StringIO()):
            await self.monitor.check_watch(self.monitor.watch("embassy"))
        self.assertNotIn("embassy", self.monitor._suggestions)

    async def test_the_state_shows_the_suggestion_and_hides_it_once_the_selector_changed(self):
        await self.lose_the_selector()
        site = self.by_id(await self.state(), "embassy")
        self.assertEqual(site["suggestion"]["selector"], "#content")
        self.assertGreaterEqual(site["suggestion"]["cover"], 0.9)
        self.monitor._suggestions["embassy"]["selector"] = "#main"  # the configured selector: nothing to suggest
        self.assertIsNone(self.by_id(await self.state(), "embassy")["suggestion"])

    async def test_applying_the_suggestion_changes_the_selector_and_checks_the_site(self):
        await self.lose_the_selector()
        key = self.by_id(await self.state(), "embassy")["key"]
        with contextlib.redirect_stdout(io.StringIO()):
            status, data = await self.post(f"/api/app/site/{key}/apply-suggestion")
        self.assertEqual((status, data["ok"], data["selector"]), (200, True, "#content"))
        self.assertEqual(self.monitor.watch("embassy").selector, "#content")
        self.assertNotIn("embassy", self.monitor._suggestions)
        self.assertFalse(data["outcome"].startswith("error"), data["outcome"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(await self.monitor.check_watch(self.monitor.watch("embassy")), "no change")

    async def test_without_a_suggestion_nothing_is_changed(self):
        key = self.by_id(await self.state(), "embassy")["key"]
        status, data = await self.post(f"/api/app/site/{key}/apply-suggestion")
        self.assertEqual((status, data["ok"]), (400, False))
        self.assertEqual(self.monitor.watch("embassy").selector, "#main")
        self.assertEqual((await self.post("/api/app/site/99999/apply-suggestion"))[0], 404)

    async def test_a_subpage_does_not_clear_the_hint_of_the_main_page(self):
        await self.lose_the_selector()
        w = self.monitor.watch("embassy")
        good = page(BASE)

        def result(url):
            return FetchResult(url, url, 200, "text/html", good, good.encode(), "http")

        sub = w.url + "/unterseite"
        snap = page_snapshot(parse_html(good, sub), sub, selector="#main")
        with contextlib.redirect_stdout(io.StringIO()):
            await self.monitor._apply_snapshot(w, sub, None, snap, result(sub))
        self.assertIn("embassy", self.monitor._suggestions)
        snap = page_snapshot(parse_html(good, w.url), w.url, selector="#main")
        with contextlib.redirect_stdout(io.StringIO()):
            await self.monitor._apply_snapshot(w, w.url, self.monitor.store.get_page(w.id, w.url), snap, result(w.url))
        self.assertNotIn("embassy", self.monitor._suggestions)


# =========================================================================== the page in a real browser

CONTRAST_JS = """(selector) => {
  const parse = c => {
    let m = c.match(/rgba?\\(([^)]+)\\)/);
    if (m) { const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = c.match(/color\\(srgb ([^)]+)\\)/);
    if (m) { const p = m[1].split(/[ \\/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1]; }
    return [0, 0, 0, 0];
  };
  const over = (t, b) => { const a = t[3] + b[3] * (1 - t[3]); if (!a) return [0, 0, 0, 0];
    return [0, 1, 2].map(i => (t[i] * t[3] + b[i] * b[3] * (1 - t[3])) / a).concat([a]); };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const el = document.querySelector(selector);
  if (!el) return null;
  let bg = [0, 0, 0, 0];
  for (let e = el; e; e = e.parentElement) { bg = over(bg, parse(getComputedStyle(e).backgroundColor)); if (bg[3] >= 0.999) break; }
  bg = over(bg, [255, 255, 255, 1]);
  const fg = over(parse(getComputedStyle(el).color), bg);
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}"""

TELEGRAM_STUB = """window.Telegram = {WebApp: {colorScheme: "%s", initData: "", ready() {}, expand() {}, onEvent() {},
  BackButton: {onClick() {}, show() {}, hide() {}}, HapticFeedback: {impactOccurred() {}, notificationOccurred() {}},
  showConfirm(message, cb) { cb(true); }}};"""


class BrowserCase(MiniAppCase):
    async def asyncSetUp(self):
        if SKIP_BROWSER:
            self.skipTest("WEBMONITOR_SKIP_BROWSER is set")
        try:
            from patchright.async_api import async_playwright
        except ImportError:
            self.skipTest("patchright is not installed")
        await super().asyncSetUp()
        self._pw = await async_playwright().start()
        exe = os.environ.get("WEBMONITOR_CHROME")
        try:
            self.browser = await self._pw.chromium.launch(**({"executable_path": exe, "args": ["--no-sandbox"]} if exe else {}))
        except Exception as first_exc:
            if exe:
                await self._pw.stop()
                await super().asyncTearDown()
                self.skipTest(f"no browser available ({type(first_exc).__name__})")
            try:
                self.browser = await self._pw.chromium.launch(channel="chrome")
            except Exception as exc:
                await self._pw.stop()
                await super().asyncTearDown()
                self.skipTest(f"no browser available ({type(exc).__name__})")

    async def asyncTearDown(self):
        if getattr(self, "browser", None):
            await self.browser.close()
            await self._pw.stop()
        await super().asyncTearDown()

    async def open(self, scheme: str = "dark", telegram: str | None = None, path: str = "/app"):
        self.errors = []
        context = await self.browser.new_context(viewport={"width": 390, "height": 844}, locale="fa-IR", color_scheme=scheme)
        pg = await context.new_page()
        await pg.route("**/telegram.org/**", lambda route: route.abort())
        if telegram:
            await pg.add_init_script(TELEGRAM_STUB % telegram)
        pg.on("pageerror", lambda err: self.errors.append(f"pageerror: {err}"))
        pg.on("console", lambda msg: self.errors.append(f"console: {msg.text}")
              if msg.type == "error" and "ERR_FAILED" not in msg.text else None)
        await pg.goto(self.base + path)
        await pg.wait_for_selector("#sites-list .site-card, #sites-list .empty, #sites-list .notice", timeout=8000)
        return pg

    @staticmethod
    async def js(pg, expression: str, arg=None):
        return await pg.evaluate(expression, arg, isolated_context=False)


class HomeScreenTests(BrowserCase):
    async def test_the_home_list_puts_what_needs_attention_first(self):
        pg = await self.open()
        titles = await pg.locator("#sites-list .card-title").all_inner_texts()
        self.assertEqual(titles, ["پرتال نوبت‌دهی (خراب)", "Goethe-Institut Teheran — آزمون B1", "سفارت آلمان — بخش ویزا",
                                  "اخبار کنسولگری", "سایت متوقف‌شده"])
        self.assertEqual(self.errors, [])

    async def test_cards_show_the_last_check_and_the_last_change(self):
        pg = await self.open()
        text = await pg.locator(".site-card", has_text="سفارت آلمان").inner_text()
        self.assertIn("بررسی", text)
        self.assertIn("تغییر", text)
        self.assertIn("127.0.0.1", text)
        self.assertNotIn("http://", text)  # only the host: the full URL belongs to the detail page
        self.assertIn("هنوز بررسی موفقی نشده", await pg.locator(".site-card", has_text="سایت متوقف‌شده").inner_text())

    async def test_a_card_is_compact(self):
        pg = await self.open()
        heights = await self.js(pg, "() => Array.from(document.querySelectorAll('.site-card')).map(e => e.getBoundingClientRect().height)")
        self.assertLess(max(heights), 190, heights)
        self.assertLess(sum(heights[:4]), 700, "four sites should fit in about one screen")

    async def test_the_health_strip_summarises_the_monitor(self):
        pg = await self.open()
        strip = pg.locator("#health-strip")
        self.assertIn("نیاز به توجه", await strip.inner_text())
        self.assertEqual(await strip.get_attribute("aria-expanded"), "false")
        await strip.click()
        self.assertEqual(await strip.get_attribute("aria-expanded"), "true")
        detail = await pg.locator("#health-detail").inner_text()
        self.assertIn("پرتال نوبت‌دهی", detail)
        self.assertIn("بازطراحی", detail)

    async def test_filters_search_and_counts(self):
        pg = await self.open()
        chips = await pg.locator("#filter-chips .fchip").all_inner_texts()
        self.assertTrue(any("نیاز به توجه" in c for c in chips))
        await pg.locator("#filter-chips .fchip", has_text="نیاز به توجه").click()
        self.assertEqual(await pg.locator("#sites-list .card-title").all_inner_texts(), ["پرتال نوبت‌دهی (خراب)"])
        await pg.locator("#filter-chips .fchip", has_text="همه").click()
        await pg.fill("#site-q", "goethe")
        self.assertEqual(await pg.locator("#sites-list .card-title").count(), 1)
        await pg.fill("#site-q", "zzz-nothing")
        self.assertIn("هیچ سایتی", await pg.locator("#sites-list").inner_text())

    async def test_the_header_fits_on_one_line_and_nothing_scrolls_sideways(self):
        pg = await self.open()
        title_height = await self.js(pg, "() => document.querySelector('header h1').getBoundingClientRect().height")
        add_height = await self.js(pg, "() => document.querySelector('header .btn.primary').getBoundingClientRect().height")
        self.assertLess(title_height, 30)
        self.assertLess(add_height, 52)
        self.assertFalse(await self.js(pg, "() => document.documentElement.scrollWidth > innerWidth"))

    async def test_an_unreachable_server_shows_a_retry_button(self):
        context = await self.browser.new_context(viewport={"width": 390, "height": 844}, locale="fa-IR")
        pg = await context.new_page()
        await pg.route("**/telegram.org/**", lambda route: route.abort())
        await pg.route("**/api/app/state", lambda route: route.abort())
        await pg.goto(self.base + "/app")
        await pg.wait_for_selector("#sites-list .notice")
        self.assertIn("اتصال به مانیتور برقرار نشد", await pg.locator("#sites-list").inner_text())
        await pg.unroute("**/api/app/state")
        await pg.locator("#sites-list .btn", has_text="تلاش دوباره").click()
        await pg.wait_for_selector("#sites-list .site-card")

    async def test_wave6_view_switch_and_events_timeline(self):
        pg = await self.open()
        await pg.wait_for_selector("#view-tab-events")
        await pg.click("#view-tab-events")
        await pg.wait_for_selector("#events-feed-panel:not([hidden])")
        self.assertTrue(await pg.locator("#events-feed-panel").is_visible())
        self.assertFalse(await pg.locator("#sites-list").is_visible())

        # Switch back to sites
        await pg.click("#view-tab-sites")
        await pg.wait_for_selector("#sites-list:not([hidden])")
        self.assertTrue(await pg.locator("#sites-list").is_visible())
        self.assertFalse(await pg.locator("#events-feed-panel").is_visible())

    async def test_wave6_bulk_mode_selection_and_bar(self):
        pg = await self.open()
        await pg.wait_for_selector("#btn-bulk-mode")
        await pg.click("#btn-bulk-mode")
        await pg.wait_for_selector(".site-check")

        # Initially bulk-bar is hidden until a card is selected
        self.assertFalse(await pg.locator("#bulk-bar").is_visible())
        await pg.locator(".site-card .site-check").first.click()
        await pg.wait_for_selector("#bulk-bar:not([hidden])")
        self.assertTrue(await pg.locator("#bulk-bar").is_visible())
        self.assertIn("۱ سایت انتخاب شد", await pg.locator("#bulk-count").inner_text())

        # Deselect via button
        await pg.locator("#bulk-bar button", has_text="لغو انتخاب").click()
        await pg.wait_for_selector("#bulk-bar", state="hidden")
        self.assertFalse(await pg.locator("#bulk-bar").is_visible())

        # Exit bulk mode
        await pg.click("#btn-bulk-mode")
        self.assertEqual(await pg.locator(".site-check").count(), 0)

    async def test_wave6_add_dialog_persona_profiles(self):
        pg = await self.open()
        await pg.locator("header .btn.primary", has_text="سایت").click()
        await pg.wait_for_selector("#modal-add[aria-hidden='false']")
        await pg.wait_for_selector("#add-profiles-box .profile-btn")
        self.assertEqual(await pg.locator("#add-profiles-box .profile-btn").count(), 6)

        # Click the embassy profile button
        await pg.locator("#add-profiles-box .profile-btn", has_text="سفارت").click()
        self.assertEqual(await pg.input_value("#add-interval"), "120")
        self.assertEqual(await pg.input_value("#add-type"), "page")

        # Close modal
        await pg.locator("#modal-add .btn", has_text="انصراف").click()
        await pg.wait_for_selector("#modal-add", state="hidden")
        self.assertFalse(await pg.locator("#modal-add").is_visible())


class EmptyMonitorTests(BrowserCase):
    sites = False

    async def test_an_empty_monitor_invites_to_add_the_first_site(self):
        pg = await self.open()
        self.assertIn("هنوز سایتی اضافه نکرده‌اید", await pg.locator("#sites-list").inner_text())
        await pg.locator("#sites-list .btn.primary").click()
        self.assertEqual(await pg.get_attribute("#modal-add", "aria-hidden"), "false")


class SiteScreenTests(BrowserCase):
    async def open_site(self, label: str, scheme: str = "dark"):
        pg = await self.open(scheme)
        await pg.locator(".site-card", has_text=label).locator(".card-open").click()
        await pg.wait_for_selector("#view-site:not([hidden]) #site-header-card h2")
        return pg

    async def test_a_card_opens_with_the_keyboard(self):
        pg = await self.open()
        await pg.focus(".site-card .card-open")
        await pg.keyboard.press("Enter")
        await pg.wait_for_selector("#view-site:not([hidden]) #site-header-card h2")
        self.assertIn("پرتال نوبت‌دهی", await pg.locator("#site-header-card h2").inner_text())

    async def test_all_four_tabs_are_visible_and_work_with_the_keyboard(self):
        pg = await self.open_site("سفارت آلمان")
        boxes = await self.js(pg, "() => Array.from(document.querySelectorAll('#site-tabs .tab')).map(e => { const r = e.getBoundingClientRect(); return [r.left, r.right, r.height]; })")
        self.assertEqual(len(boxes), 4)
        for left, right, height in boxes:
            self.assertGreaterEqual(left, 0)
            self.assertLessEqual(right, 390)
            self.assertGreaterEqual(height, 44)
        self.assertEqual(await pg.locator("#site-tabs .tab[aria-selected=true]").count(), 1)
        await pg.focus("#tab-btn-overview")
        await pg.keyboard.press("ArrowLeft")  # right-to-left: the key towards the left reaches the NEXT tab
        self.assertEqual(await pg.get_attribute("#tab-btn-diffs", "aria-selected"), "true")
        self.assertTrue(await pg.locator("#site-tab-diffs").is_visible())
        self.assertFalse(await pg.locator("#site-tab-overview").is_visible())
        await pg.keyboard.press("ArrowRight")
        self.assertEqual(await pg.get_attribute("#tab-btn-overview", "aria-selected"), "true")

    async def test_the_history_collapses_old_entries_and_can_be_searched(self):
        self.pages["embassy"] = page(BASE[:20] + ["Termin 20: ZWEITE Änderung 11:00 Uhr"] + BASE[21:40] + ["NEU: Zusatztermin am 30.11.2026"] + BASE[41:])
        with contextlib.redirect_stdout(io.StringIO()):
            await self.monitor.check_watch(self.monitor.watch("embassy"))
        pg = await self.open_site("سفارت آلمان")
        await pg.locator("#tab-btn-diffs").click()
        events = pg.locator("#site-tab-diffs details.event")
        self.assertGreaterEqual(await events.count(), 2)
        self.assertIsNotNone(await events.nth(0).get_attribute("open"))
        self.assertIsNone(await events.nth(1).get_attribute("open"))
        await events.nth(1).locator("summary").click()
        self.assertIsNotNone(await events.nth(1).get_attribute("open"))
        await pg.fill("#site-tab-diffs input[type=search]", "Zusatztermin")
        visible = await self.js(pg, "() => Array.from(document.querySelectorAll('.site-diff-item')).filter(e => !e.hidden).length")
        self.assertEqual(visible, 1)

    async def test_settings_are_grouped_and_a_switch_saves_through_the_api(self):
        pg = await self.open_site("سفارت آلمان")
        await pg.locator("#tab-btn-settings").click()
        groups = await pg.locator("#site-tab-settings .group-title").all_inner_texts()
        self.assertEqual(groups, ["پایش", "اعلان‌ها", "تشخیص تغییر", "منطقهٔ خطر"])
        silent = pg.locator("#site-tab-settings .switch[aria-labelledby=sw-silent-l]")
        self.assertEqual(await silent.get_attribute("aria-checked"), "false")
        await silent.click()
        await pg.wait_for_function("() => document.querySelector('#site-tab-settings .switch[aria-labelledby=sw-silent-l]').getAttribute('aria-checked') === 'true'")
        self.assertTrue(self.monitor.watch("embassy").silent)
        labels = await self.js(pg, "() => Array.from(document.querySelectorAll('#site-tab-settings .setting-info b')).map(e => e.getBoundingClientRect().height)")
        self.assertLess(max(labels), 80, "titles must not be squeezed into a narrow column")

    async def test_danger_actions_ask_first(self):
        pg = await self.open(telegram="dark")
        await pg.locator(".site-card", has_text="اخبار").locator(".card-open").click()
        await pg.wait_for_selector("#view-site:not([hidden])")
        await pg.locator("#tab-btn-settings").click()
        await self.js(pg, "() => { window.Telegram.WebApp.showConfirm = (m, cb) => { window.__asked = m; cb(false); }; }")
        await pg.locator("#site-tab-settings .btn.danger", has_text="حذف").click()
        self.assertIn("حذف", await self.js(pg, "() => window.__asked"))
        self.assertIsNotNone(self.monitor.watch("news"))  # declined: still there

    async def test_the_selector_suggestion_can_be_applied_with_one_tap(self):
        self.pages["embassy"] = page(BASE, root="section id='content'")
        with contextlib.redirect_stdout(io.StringIO()):
            await self.monitor.check_watch(self.monitor.watch("embassy"))
        pg = await self.open()
        card = pg.locator(".site-card", has_text="سفارت آلمان")
        self.assertIn("پیشنهاد", await card.inner_text())
        titles = await pg.locator("#sites-list .card-title").all_inner_texts()
        self.assertLess(titles.index("سفارت آلمان — بخش ویزا"), titles.index("اخبار کنسولگری"))
        await card.locator(".card-open").click()
        button = pg.locator("#site-header-card .btn", has_text="اعمال این انتخابگر")
        await button.wait_for()
        self.assertIn("#content", await pg.locator("#site-header-card .notice.info").inner_text())
        with contextlib.redirect_stdout(io.StringIO()):
            await button.click()
            await pg.wait_for_function("() => !document.querySelector('#site-header-card .notice.info')", timeout=15000)
        self.assertEqual(self.monitor.watch("embassy").selector, "#content")

    async def test_a_redesign_is_explained_on_the_site_page(self):
        pg = await self.open_site("Goethe")
        box = await pg.locator("#site-header-card .notice.warn").inner_text()
        self.assertIn("بازطراحی", box)
        await pg.locator("#site-header-card .btn", has_text="دیدن تغییر").click()
        self.assertTrue(await pg.locator("#site-tab-diffs").is_visible())
        self.assertIn("بازطراحی", await pg.locator("#site-tab-diffs summary").first.inner_text())


class AccessibilityTests(BrowserCase):
    CHECK_JS = """() => {
      const visible = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'; };
      const clickable = Array.from(document.querySelectorAll('[onclick]')).filter(e => e.id !== 'ch-img');
      const notReal = clickable.filter(e => !['BUTTON', 'A', 'INPUT', 'SELECT', 'SUMMARY'].includes(e.tagName)).map(e => e.outerHTML.slice(0, 80));
      const buttons = Array.from(document.querySelectorAll('button, a[href], summary')).filter(visible);
      const named = e => { const ref = document.getElementById(e.getAttribute('aria-labelledby') || ''); return (e.getAttribute('aria-label') || e.textContent || (ref && ref.textContent) || '').trim(); };
      const unnamed = buttons.filter(e => !named(e)).map(e => e.outerHTML.slice(0, 80));
      const small = buttons.filter(e => !e.classList.contains('switch') && !e.matches('a, .link-btn, summary'))
        .filter(e => e.getBoundingClientRect().height < 40).map(e => e.className + ' ' + Math.round(e.getBoundingClientRect().height));
      const switches = Array.from(document.querySelectorAll('.switch')).filter(visible);
      const badSwitches = switches.filter(e => e.getAttribute('role') !== 'switch' || !e.hasAttribute('aria-checked') ||
        !document.getElementById(e.getAttribute('aria-labelledby') || '')).length;
      return {notReal, unnamed, small, badSwitches, switches: switches.length, main: !!document.querySelector('main'),
              header: !!document.querySelector('header'), live: document.getElementById('toast').getAttribute('aria-live'),
              dialogs: Array.from(document.querySelectorAll('.modal-backdrop')).every(e => e.getAttribute('role') === 'dialog' && e.getAttribute('aria-modal') === 'true'),
              lang: document.documentElement.lang, dir: document.documentElement.dir};
    }"""

    async def check(self, pg) -> dict:
        return await self.js(pg, self.CHECK_JS)

    async def test_the_home_screen(self):
        pg = await self.open()
        result = await self.check(pg)
        self.assertEqual(result["notReal"], [])
        self.assertEqual(result["unnamed"], [])
        self.assertEqual(result["small"], [])
        self.assertTrue(result["main"] and result["header"] and result["dialogs"])
        self.assertEqual((result["live"], result["lang"], result["dir"]), ("polite", "fa", "rtl"))

    async def test_the_site_screen_and_its_switches(self):
        pg = await self.open()
        await pg.locator(".site-card", has_text="سفارت آلمان").locator(".card-open").click()
        await pg.wait_for_selector("#view-site:not([hidden])")
        await pg.locator("#tab-btn-settings").click()
        result = await self.check(pg)
        self.assertEqual(result["notReal"], [])
        self.assertEqual(result["unnamed"], [])
        self.assertEqual(result["small"], [])
        self.assertGreaterEqual(result["switches"], 7)
        self.assertEqual(result["badSwitches"], 0)

    async def test_dialogs_take_focus_and_give_it_back(self):
        pg = await self.open()
        await pg.locator("header .btn.primary").click()
        await pg.wait_for_function("() => document.activeElement && document.activeElement.id === 'add-url'")
        self.assertEqual(await pg.get_attribute("#modal-add", "aria-hidden"), "false")
        await pg.keyboard.press("Escape")
        self.assertEqual(await pg.get_attribute("#modal-add", "aria-hidden"), "true")
        self.assertTrue(await self.js(pg, "() => document.activeElement.classList.contains('btn') && document.activeElement.textContent.includes('سایت')"))
        await pg.locator("header .icon-btn").click()
        await pg.wait_for_selector("#modal-settings .switch")
        await pg.mouse.click(5, 5)  # a tap on the backdrop closes it
        self.assertEqual(await pg.get_attribute("#modal-settings", "aria-hidden"), "true")

    async def test_adding_a_site_through_the_dialog(self):
        pg = await self.open()
        await pg.locator("header .btn.primary").click()
        await pg.fill("#add-url", f"http://127.0.0.1:{self.port}/news")
        await pg.fill("#add-name", "نمونهٔ تازه")
        with mock.patch("webmonitor.netguard.is_public_host", new=mock.AsyncMock(return_value=True)):
            await pg.locator("#modal-add .btn.primary").click()
            await pg.wait_for_selector("#view-site:not([hidden]) #site-header-card h2", timeout=15000)
        self.assertIn("نمونهٔ تازه", await pg.locator("#site-header-card h2").inner_text())


class ChallengeDialogTests(BrowserCase):
    PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

    async def test_the_captcha_dialog_loads_a_frame_sends_clicks_and_can_be_cancelled(self):
        pg = await self.open()
        actions = []

        async def frame(route):
            await route.fulfill(content_type="application/json", body=json.dumps(
                {"ok": True, "image_data_url": self.PNG, "remaining": 540}))

        async def action(route):
            actions.append(json.loads(route.request.post_data or "{}"))
            await route.fulfill(content_type="application/json", body='{"ok": true}')

        await pg.route("**/api/app/challenge/tok123/frame", frame)
        await pg.route("**/api/app/challenge/tok123/action", action)
        await self.js(pg, "() => openChallengeModal('tok123', 'سایت نمونه')")
        await pg.wait_for_function("() => document.getElementById('ch-img').src.startsWith('data:image/png')")
        self.assertEqual(await pg.get_attribute("#modal-challenge", "aria-hidden"), "false")
        self.assertIn("سایت نمونه", await pg.locator("#ch-title").inner_text())
        self.assertEqual((await pg.locator("#ch-timer").inner_text()).strip(), "540s")
        await pg.locator("#ch-img").click(position={"x": 10, "y": 10})
        await pg.wait_for_timeout(300)
        self.assertEqual(actions[0]["action"], "click")
        await pg.locator("#modal-challenge .btn", has_text="کلیک روی مربع کپچا").click()
        await pg.locator("#modal-challenge .btn.danger").click()
        await pg.wait_for_function("() => document.getElementById('modal-challenge').getAttribute('aria-hidden') === 'true'")
        self.assertEqual([a["action"] for a in actions], ["click", "turnstile", "cancel"])
        self.assertEqual(self.errors, [])


class ThemeTests(BrowserCase):
    SELECTORS = [".badge.ok", ".badge.error", ".badge.warn", ".badge.paused", ".badge.info", ".card-title", ".card-times span",
                 ".card-note.err", "header .btn.primary", ".fchip[aria-pressed=true]", ".fchip[aria-pressed=false]", ".health .txt small"]

    async def contrast(self, pg) -> dict:
        found = {}
        for selector in self.SELECTORS:
            ratio = await self.js(pg, CONTRAST_JS, selector)
            if ratio is not None:
                found[selector] = round(ratio, 2)
        return found

    async def test_text_is_readable_in_the_dark_theme(self):
        pg = await self.open("dark")
        self.assertEqual(await self.js(pg, "() => document.documentElement.className"), "dark")
        ratios = await self.contrast(pg)
        self.assertGreaterEqual(len(ratios), 9, ratios)
        self.assertEqual({k: v for k, v in ratios.items() if v < 4.5}, {})

    async def test_text_is_readable_in_the_light_theme(self):
        pg = await self.open("light")
        self.assertEqual(await self.js(pg, "() => document.documentElement.className"), "light")
        ratios = await self.contrast(pg)
        self.assertGreaterEqual(len(ratios), 9, ratios)
        self.assertEqual({k: v for k, v in ratios.items() if v < 4.5}, {})

    async def test_telegram_decides_when_it_is_present(self):
        pg = await self.open("dark", telegram="light")
        self.assertEqual(await self.js(pg, "() => document.documentElement.className"), "light")
        pg = await self.open("light", telegram="dark")
        self.assertEqual(await self.js(pg, "() => document.documentElement.className"), "dark")

    async def test_telegram_colour_variables_are_used(self):
        context = await self.browser.new_context(viewport={"width": 390, "height": 844})
        pg = await context.new_page()
        await pg.route("**/telegram.org/**", lambda route: route.fulfill(
            content_type="application/javascript",
            body="document.documentElement.style.setProperty('--tg-theme-bg-color', '#ffffff');"
                 "document.documentElement.style.setProperty('--tg-theme-secondary-bg-color', '#f4ecd8');"))
        await pg.goto(self.base + "/app")
        await pg.wait_for_selector("#sites-list .site-card")
        self.assertEqual(await self.js(pg, "() => document.documentElement.className"), "light")  # derived from the variable
        self.assertEqual(await self.js(pg, "() => getComputedStyle(document.body).backgroundColor"), "rgb(244, 236, 216)")


class UiModuleTests(unittest.TestCase):
    def test_the_script_is_valid_javascript(self):
        import re
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", miniapp_ui.MINIAPP_HTML, re.S)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.js"
            path.write_text(max(scripts, key=len), encoding="utf-8")
            result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_page_keeps_its_safety_properties(self):
        html = miniapp_ui.MINIAPP_HTML
        self.assertIn('hashParams.get("t")', html)  # the admin token comes from the fragment, never the query
        self.assertNotIn('params.get("t")', html)
        self.assertEqual(html.count("<main"), 1)
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn("[hidden] { display: none !important; }", html)
        self.assertIn('role="status" aria-live="polite"', html)


if __name__ == "__main__":
    unittest.main()

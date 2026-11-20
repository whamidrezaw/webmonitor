"""Telegram Mini App (TWA) dashboard and REST API for WebMonitor.

Provides:
* Cryptographic validation of Telegram WebApp ``initData`` (HMAC-SHA256 per Telegram spec)
  plus HMAC-signed admin URL tokens for seamless multi-device access.
* Rich RTL Persian Single-Page Application (``/app``) with:
  - Per-site dedicated profile pages (Overview, Access Diagnostics, Visual Diff History,
    Live Screenshot, Interactive Settings switches, Cookie importer, Subpages inspector)
  - Global search across all historical diffs
  - Smart URL Analyzer & Add-site wizard modal and global bot settings drawer
  - Live interactive CAPTCHA / Cloudflare challenge solver inside the Mini App
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import Counter
from dataclasses import replace
from urllib.parse import parse_qsl, urlsplit

from aiohttp import web

from . import netguard
from .analyzer import GOETHE, Analysis, analyze, choice_filter_values, preview_choice, smart_name, suggest_choices
from .bot import ENGINE_NAMES, _error_kind, normalize_input_url
from .challenge import _check_csrf
from .config import REPORT_STYLES, ConfigError, Proxy, Watch
from .engine import DIGESTABLE, ENGINE_LABELS
from .extract import ExtractError, detect_block, parse_feed
from .fetchers import FetchError, clear_watch_cookies, has_watch_cookies, import_watch_cookies
from .health import build_health
from .miniapp_ui import MINIAPP_HTML as _MINIAPP_HTML
from .registry import default_crawl
from .report import render_document
from .util import fa_datetime, fa_digits, format_short, format_ts, human_duration, truncate

log = logging.getLogger("webmonitor")

TOKEN_TTL = 86400  # a signed link stays valid for one day
DOWNLOAD_TOKEN_TTL = 1200  # 20 minutes: reusable for mobile download managers, scoped to one file
_PROXY_HEADERS = ("X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP")
_MINIAPP_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://telegram.org 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
)

# One-tap use-case templates: sensible defaults per kind of target. They never force a monitoring type on the
# server (that comes from the analyzer or the user); ``type_hint`` only pre-selects the type field in the UI.
USE_CASE_PROFILES: list[dict] = [
    {"id": "embassy", "icon": "landmark", "label": "نوبت سفارت و ویزا", "desc": "بررسی سریع، بیدارباش و کلمات نوبت",
     "type_hint": "page", "defaults": {"interval_seconds": 120, "alarm": True, "crawl_enabled": True,
                                       "report_style": "before_after",
                                       "keywords": ["نوبت", "ویزا", "Termin", "appointment", "Visa"]}},
    {"id": "exam", "icon": "graduation", "label": "ظرفیت آزمون (گوته و زبان)", "desc": "هر دقیقه، بیدارباش فوری",
     "type_hint": "json", "defaults": {"interval_seconds": 60, "alarm": True, "crawl_enabled": False,
                                       "keywords": ["قابل رزرو", "buchbar", "verfügbar", "available"]}},
    {"id": "official", "icon": "building", "label": "اطلاعیهٔ دانشگاه و سازمان", "desc": "فهرست اطلاعیه‌ها با خزش زیرصفحه",
     "type_hint": "page", "defaults": {"interval_seconds": 900, "crawl_enabled": True, "report_style": "inline"}},
    {"id": "news", "icon": "newspaper", "label": "اخبار و رسانه", "desc": "فقط تیترهای تازه، بی‌صدا",
     "type_hint": "headlines", "defaults": {"interval_seconds": 300, "silent": True, "crawl_enabled": False}},
    {"id": "telegram", "icon": "send", "label": "کانال عمومی تلگرام", "desc": "پست‌های جدید یک کانال",
     "type_hint": "items", "defaults": {"interval_seconds": 180, "crawl_enabled": False}},
    {"id": "price_api", "icon": "chart", "label": "قیمت، موجودی و API", "desc": "مقایسهٔ دوطرفه و عکس صفحه",
     "type_hint": "page", "defaults": {"interval_seconds": 600, "crawl_enabled": False,
                                       "report_style": "side_by_side", "notify_mode": "both"}},
]
_PROFILES_BY_ID = {p["id"]: p for p in USE_CASE_PROFILES}
_EVENT_KIND_FILTERS = {
    "changes": ("change", "changed", "new_items", "items", "crawl", "new_page", "removed_page", "file"),
    "errors": ("error",),
}
_BULK_ACTIONS = ("pause", "resume", "check", "silent_on", "silent_off", "delete")
BULK_MAX = 200


def _split_list(raw, *, commas: bool = True) -> list[str]:
    """A list of strings from a JSON list or a comma/line separated string (Persian comma included)."""
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    if not isinstance(raw, str):
        return []
    text = raw.replace("،", ",") if commas else raw
    parts = [p for line in text.splitlines() for p in (line.split(",") if commas else [line])]
    return [p.strip() for p in parts if p.strip()]


def miniapp_secret(store) -> str:
    """Key that signs admin links: random, kept in the database and independent of the bot token, so a
    leaked bot token alone cannot be used to forge a Mini App login."""
    secret = store.get_setting("miniapp_secret", "")
    if len(secret) < 32:
        secret = secrets.token_hex(32)
        store.set_setting("miniapp_secret", secret)
    return secret


def make_admin_token(secret: str, user_id: str, ttl: int = TOKEN_TTL, now: float | None = None) -> str:
    """Create an HMAC-SHA256 signed token ``<exp>.<uid>.<sig>`` that is bound to one Telegram user id."""
    uid = str(user_id or "").strip()
    if not secret or not uid:
        return ""
    exp = int((now if now is not None else time.time()) + ttl)
    payload = f"{exp}.{uid}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def verify_admin_token(token: str, secret: str, now: float | None = None) -> str | None:
    """Verify a token produced by ``make_admin_token``; returns ``user_id`` or ``None``."""
    if not token or not secret:
        return None
    parts = token.strip().split(".")
    if len(parts) != 3:
        return None
    exp_s, uid, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    cur = now if now is not None else time.time()
    if cur > exp:
        return None
    payload = f"{exp}.{uid}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    return uid


def make_download_token(secret: str, user_id: str, scope: str, ttl: int = DOWNLOAD_TOKEN_TTL,
                        now: float | None = None) -> str:
    """Create a short-lived, reusable HMAC-SHA256 token scoped to one downloadable resource."""
    uid = str(user_id or "").strip()
    sc = str(scope or "").strip()
    if not secret or not uid or not sc:
        return ""
    exp = int((now if now is not None else time.time()) + ttl)
    payload = f"dl.{exp}.{uid}"
    mac_input = f"{payload}|{sc}"
    sig = hmac.new(secret.encode("utf-8"), mac_input.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def verify_download_token(token: str, secret: str, expected_scope: str,
                          now: float | None = None) -> str | None:
    """Verify a scoped download token; returns ``user_id`` or ``None`` (never accepted as an admin token)."""
    if not token or not secret or not expected_scope:
        return None
    parts = token.strip().split(".")
    if len(parts) != 4 or parts[0] != "dl":
        return None
    _, exp_s, uid, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    cur = now if now is not None else time.time()
    if cur > exp:
        return None
    mac_input = f"dl.{exp}.{uid}|{expected_scope}"
    expected = hmac.new(secret.encode("utf-8"), mac_input.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    return uid


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400,
                       now: float | None = None) -> dict | None:
    """Validate Telegram WebApp ``initData`` query string using HMAC-SHA256.

    Returns the parsed ``user`` dict if valid, or ``None`` if tampered/expired.
    """
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        return None
    auth_date_s = pairs.get("auth_date", "0")
    try:
        auth_date = int(auth_date_s)
    except ValueError:
        return None
    cur = now if now is not None else time.time()
    if max_age > 0 and abs(cur - auth_date) > max_age:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return None
    user_raw = pairs.get("user")
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
        if not isinstance(user, dict) or not user.get("id"):
            return None
        return user
    except Exception:
        return None


class MiniApp:
    """Serves the Telegram Mini App UI and JSON API on the ChallengeManager aiohttp server."""

    def __init__(self, monitor):
        self.m = monitor

    def register_routes(self, app: web.Application) -> None:
        app.router.add_get("/app", self.handle_app_page)
        app.router.add_get("/api/app/state", self.handle_state)
        app.router.add_get("/api/app/site/{key}", self.handle_site_detail)
        app.router.add_post("/api/app/site/{key}/check", self.handle_site_check)
        app.router.add_post("/api/app/site/{key}/diagnose", self.handle_site_diagnose)
        app.router.add_post("/api/app/site/{key}/screenshot", self.handle_site_screenshot)
        app.router.add_get("/api/app/site/{key}/screenshot/{digest}.jpg", self.handle_site_screenshot_download)
        app.router.add_post("/api/app/site/{key}/preview", self.handle_site_preview)
        app.router.add_post("/api/app/site/{key}/update", self.handle_site_update)
        app.router.add_post("/api/app/site/{key}/reset", self.handle_site_reset)
        app.router.add_post("/api/app/site/{key}/cookies", self.handle_site_cookies)
        app.router.add_post("/api/app/site/{key}/delete", self.handle_site_delete)
        app.router.add_post("/api/app/site/{key}/apply-suggestion", self.handle_apply_suggestion)
        app.router.add_post("/api/app/site/{key}/clone", self.handle_site_clone)
        app.router.add_get("/api/app/events", self.handle_recent_events)
        app.router.add_post("/api/app/bulk", self.handle_bulk)
        app.router.add_post("/api/app/analyze", self.handle_analyze)
        app.router.add_post("/api/app/add", self.handle_add_site)
        app.router.add_post("/api/app/check-all", self.handle_check_all)
        app.router.add_post("/api/app/clear-outbox", self.handle_clear_outbox)
        app.router.add_post("/api/app/settings", self.handle_settings)
        app.router.add_get("/api/app/search", self.handle_search)
        app.router.add_get("/api/app/event/{event_id}/report", self.handle_event_report)
        app.router.add_get("/api/app/export", self.handle_export)
        app.router.add_post("/api/app/import", self.handle_import)
        app.router.add_get("/api/app/challenge/{token}/frame", self.handle_challenge_frame)
        app.router.add_post("/api/app/challenge/{token}/action", self.handle_challenge_action)

    # ------------------------------------------------------------------ auth & validation helpers

    @staticmethod
    def _parse_key(request: web.Request) -> int | None:
        try:
            return int(request.match_info["key"])
        except (KeyError, TypeError, ValueError):
            return None

    def _is_authorized_user(self, uid: str) -> bool:
        """Only people the bot knows as admins (configured, or seen using the panel) may use the Mini App."""
        uid = str(uid or "").strip()
        if not uid:
            return False
        cfg_admins = {str(x) for x in (self.m.config.telegram.admin_ids or [])}
        cfg_chats = {str(x) for x in (self.m.config.telegram.chat_ids or []) if not str(x).startswith("-")}
        db_admins = set(self.m.store.admin_ids())
        authorized = cfg_admins | cfg_chats | db_admins
        if uid in authorized:
            return True
        if uid == "local" and not authorized:
            return True
        return False

    def _authenticate(self, request: web.Request) -> tuple[bool, str]:
        bot_token = self.m.config.telegram.token
        if not bot_token:
            # Local dry-run / console mode without Telegram token: ONLY direct loopback (never via reverse proxy)
            if any(request.headers.get(h) for h in _PROXY_HEADERS):
                return False, "حالت بدون توکن فقط از روی خود سیستم (localhost مستقیم) مجاز است."
            remote = getattr(request, "remote", None)
            if remote is not None and not netguard.is_direct_loopback(remote, request.headers):
                return False, "حالت بدون توکن فقط از روی localhost مجاز است."
            return True, "local"
        # Credentials travel in headers only: a query string would end up in access logs.
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        if init_data:
            user = validate_init_data(init_data, bot_token)
            if user is not None:
                uid = str(user.get("id", "")).strip()
                if self._is_authorized_user(uid):
                    if uid.isdigit():
                        name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or uid
                        self.m.store.touch_admin(uid, name)
                    return True, uid
                return False, "این اکانت تلگرام دسترسی ادمین ندارد."
        token = request.headers.get("X-Admin-Token", "")
        if token:
            uid = verify_admin_token(token, miniapp_secret(self.m.store))
            if uid and self._is_authorized_user(uid):
                return True, uid
        return False, "نشست منقضی شده یا دسترسی غیرمجاز است. لطفاً دوباره از داخل ربات دکمهٔ «🚀 مینی‌اپ» را بزنید."

    def _require_auth(self, request: web.Request) -> web.Response | None:
        if getattr(request, "method", "GET") in ("POST", "PUT", "DELETE", "PATCH"):
            csrf_err = _check_csrf(request)
            if csrf_err:
                return web.json_response({"ok": False, "error": csrf_err}, status=403)
        ok, info = self._authenticate(request)
        if not ok:
            return web.json_response({"ok": False, "error": info}, status=403)
        return None

    # ------------------------------------------------------------------ serialization helpers

    def _serialize_site(self, record, now: float, counts_24h: dict,
                        page_counts: dict[str, int] | None = None,
                        watch_states: dict[str, dict] | None = None) -> dict:
        w = record.watch
        store = self.m.store
        if w:
            state = watch_states.get(record.id, {}) if watch_states is not None else store.watch_state(record.id)
            subpages_count = page_counts.get(record.id, 0) if page_counts is not None else store.page_counts().get(record.id, 0)
            last_ev = store.last_event(record.id, DIGESTABLE)
        else:
            state = {}
            subpages_count = 0
            last_ev = None
        changes_24h = sum(counts_24h.get(record.id, Counter())[k] for k in DIGESTABLE)
        has_cookies = has_watch_cookies(self.m.config.data_dir, record.id)
        if w is None:
            status = "broken"
            status_label = "❌ خطای تنظیمات"
        elif not w.enabled:
            status = "paused"
            status_label = "⏸ متوقف"
        elif state.get("consecutive_errors", 0) > 0:
            status = "error"
            status_label = f"⚠️ خطا ({fa_digits(state['consecutive_errors'])} بار)"
        elif state.get("last_ok"):
            status = "ok"
            status_label = "🟢 فعال و سالم"
        else:
            status = "pending"
            status_label = "⏳ در انتظار بررسی"

        active_engine = (w.engine if w.engine != "auto" else (state.get("engine") or "http")) if w else "http"
        schedule_fn = getattr(self.m, "schedule_info", None)
        schedule = schedule_fn(record.id, now) if (w and callable(schedule_fn)) else {"checking": False, "next_due_in": None}
        return {
            "key": record.key,
            "id": record.id,
            "label": record.label,
            "name": str(record.spec.get("name") or ""),
            "checking": bool(schedule.get("checking")),
            "next_due_in": schedule.get("next_due_in"),
            "url": w.url if w else record.spec.get("url", ""),
            "page_url": w.page_url if w else record.spec.get("url", ""),
            "origin": record.origin,
            "status": status,
            "status_label": status_label,
            "enabled": bool(w.enabled) if w else False,
            "type": w.type if w else record.spec.get("type", "page"),
            "type_label": self.m.kind_label(w) if w else "نامعتبر",
            "engine": w.engine if w else "auto",
            "active_engine": active_engine,
            "engine_label": ENGINE_LABELS.get(active_engine, active_engine),
            "interval_seconds": int(w.interval_seconds) if w else 120,
            "interval_human": human_duration(w.interval_seconds) if w else "—",
            "consecutive_errors": state.get("consecutive_errors", 0),
            "last_error": state.get("last_error") or record.error or "",
            "last_ok_ago": human_duration(now - state["last_ok"]) + " پیش" if state.get("last_ok") else "هنوز نه",
            "last_check_ago": human_duration(now - state["last_check"]) + " پیش" if state.get("last_check") else "هنوز نه",
            "last_change_ago": (human_duration(now - last_ev["created"]) + " پیش" if last_ev else "بدون تغییر"),
            "last_change_summary": (last_ev["summary"] or "") if last_ev else "",
            "last_change_ts": float(last_ev["created"]) if last_ev else 0.0,
            "drift": self._drift_info(record.id, now),
            "suggestion": self._suggestion_info(record.id, w),
            "changes_24h": changes_24h,
            "subpages_count": subpages_count,
            "crawl_enabled": bool(w and w.crawl),
            "crawl_max_pages": w.crawl.max_pages if (w and w.crawl) else 0,
            "has_cookies": has_cookies,
            "keywords": list(w.keywords) if w else [],
            "only_keywords": bool(w.only_keywords) if w else False,
            "track_links": bool(w.track_links) if w else True,
            "silent": bool(w.silent) if w else False,
            "alarm": bool(w.alarm) if w else False,
            "selector": (w.item_selector if w.type == "items" else w.selector) if w else "",
            "exclude_selectors": list(w.exclude_selectors) if w else [],
            "ignore_patterns": [getattr(p, "pattern", str(p)) for p in w.ignore_patterns] if w else [],
            "proxy": w.proxy.server if (w and w.proxy) else "",
            "report_style": getattr(w, "report_style", "inline") if w else "inline",
            "ignore_reorder": bool(getattr(w, "ignore_reorder", True)) if w else True,
            "notify_mode": getattr(w, "notify_mode", "text") if w else "text",
            "route": (state.get("route") or "direct") if w else "direct",
        }

    def _drift_info(self, watch_id: str, now: float) -> dict | None:
        """The last large-scale change of the page, while it is still news (a day)."""
        info = getattr(self.m, "_drift", {}).get(watch_id)
        if not info or now - info["ts"] > 86400:
            return None
        return {"level": info["level"], "age_s": int(now - info["ts"])}

    def _suggestion_info(self, watch_id: str, w) -> dict | None:
        """A selector that now holds the old content (found when the configured one stopped matching)."""
        found = getattr(self.m, "_suggestions", {}).get(watch_id)
        if not found or w is None or w.selector == found["selector"]:
            return None
        return {"selector": found["selector"], "cover": round(float(found["cover"]), 2)}

    def _health(self, now: float) -> dict | None:
        try:
            return build_health(self.m, now)
        except Exception:  # the dashboard must open even if the health report cannot be built
            log.exception("health report failed")
            return None

    def _serialize_event(self, row) -> dict:
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {}
        blocks = payload.get("full_blocks") or payload.get("blocks") or []
        return {
            "id": row["id"],
            "watch_id": row["watch_id"],
            "url": row["url"] or "",
            "kind": row["kind"],
            "created": row["created"],
            "created_human": fa_datetime(row["created"], self.m.tz),
            "created_short": format_short(row["created"], self.m.tz),
            "summary": row["summary"] or "",
            "status": row["status"],
            "header_html": payload.get("header", ""),
            "blocks_html": blocks[:40],
            "drift_level": (payload.get("drift") or {}).get("level", ""),
        }

    # ------------------------------------------------------------------ HTTP handlers

    async def handle_app_page(self, request: web.Request) -> web.Response:
        return web.Response(
            text=_MINIAPP_HTML,
            content_type="text/html",
            charset="utf-8",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": _MINIAPP_CSP,
            },
        )

    async def handle_state(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        now = time.time()
        store = self.m.store
        records = self.m.registry.records()
        counts_24h = store.event_counts_since(now - 86400)
        page_counts = store.page_counts()
        watch_states = store.all_watch_states()
        sites = [self._serialize_site(r, now, counts_24h, page_counts, watch_states) for r in records]

        challenges = []
        if getattr(self.m, "challenge", None):
            for tok, sess in list(self.m.challenge._sessions.items()):
                if not sess.expired:
                    challenges.append({
                        "token": tok,
                        "watch_id": sess.watch_id,
                        "watch_label": sess.watch_label,
                        "url": sess.url,
                        "remaining": max(0, int(sess.expires_at - now)),
                    })

        return web.json_response({
            "ok": True,
            "uptime_human": human_duration(now - self.m.started_at),
            "pending_outbox": store.pending_count(),
            "sites": sites,
            "challenges": challenges,
            "health": self._health(now),
            "activity_7d": store.daily_activity(7, now=now),
            "profiles": USE_CASE_PROFILES,
            "settings": {
                "report_style": store.get_setting("default_report_style", "inline"),
                "auto_screenshot": store.get_setting("auto_screenshot", "off") == "on",
                "quiet_hours": store.get_setting("quiet_hours", "off") == "on",
                "daily_digest": store.get_setting("daily_report", "on") != "off",
                "startup_notify": store.get_setting("startup_notify", "on") != "off",
                "fallback_proxy": store.get_setting("fallback_proxy", "auto"),
            },
        })

    async def handle_site_detail(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None:
            return web.json_response({"ok": False, "error": "سایت پیدا نشد"}, status=404)
        now = time.time()
        counts_24h = self.m.store.event_counts_since(now - 86400)
        page_counts = self.m.store.page_counts()
        site = self._serialize_site(record, now, counts_24h, page_counts)
        events = [self._serialize_event(r) for r in self.m.store.recent_events(record.id, 25)]
        subpages = []
        for row in self.m.store.page_summaries(record.id, 80):
            url = row["url"]
            subpages.append({
                "url": url,
                "title": row["title"] or url,
                "engine": row["engine"] or "",
                "last_seen": human_duration(now - row["last_seen"]) + " پیش" if row["last_seen"] else "—",
                "last_changed": human_duration(now - row["last_changed"]) + " پیش" if row["last_changed"] else "—",
            })
        active_challenge = None
        if getattr(self.m, "challenge", None):
            for tok, sess in list(self.m.challenge._sessions.items()):
                if not sess.expired and sess.watch_id == record.id:
                    active_challenge = {
                        "token": tok,
                        "url": sess.url,
                        "remaining": max(0, int(sess.expires_at - now)),
                    }
                    break
        return web.json_response({
            "ok": True,
            "site": site,
            "events": events,
            "subpages": subpages,
            "challenge": active_challenge,
            "activity_7d": self.m.store.daily_activity(7, watch_id=record.id, now=now),
        })

    async def handle_site_check(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None or record.watch is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        started = time.monotonic()
        outcome = await self.m.check_watch(record.watch)
        elapsed = round(time.monotonic() - started, 1)
        return web.json_response({"ok": True, "outcome": outcome, "elapsed": elapsed})

    async def handle_site_diagnose(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None or record.watch is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        w = record.watch
        results = await self.m.diagnose(w.url, base=w)
        rows = [
            {
                "route": route,
                "route_label": ("پروکسی اختصاصی" if w.proxy else "مستقیم") if route == "direct" else "پروکسی پشتیبان",
                "engine": engine,
                "engine_label": ENGINE_NAMES.get(engine, engine),
                "ok": bool(ok),
                "detail": detail,
            }
            for route, engine, ok, detail in results
        ]
        recommended = None
        for route in ("direct", "fallback"):
            good = [r for r in rows if r["route"] == route and r["ok"]]
            if good:
                recommended = {
                    "route": route,
                    "engine": good[0]["engine"],
                    "engine_label": good[0]["engine_label"],
                }
                break
        return web.json_response({"ok": True, "results": rows, "recommended": recommended})

    async def handle_site_screenshot(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        _, uid = self._authenticate(request)
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None or record.watch is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        try:
            raw_body = await request.text()
            body_data = json.loads(raw_body) if raw_body.strip() else {}
            if not isinstance(body_data, dict):
                body_data = {}
        except Exception:
            body_data = {}
        req_digest = str(body_data.get("digest") or "").strip().lower()
        send_to_chat = bool(body_data.get("send_to_chat"))
        cached_path = self.m._shot_path(record.id, req_digest) if len(req_digest) == 64 else None
        if cached_path is not None:
            try:
                image_bytes = cached_path.read_bytes()
                digest = req_digest
            except OSError:
                cached_path = None
        if cached_path is None:
            try:
                image_bytes = await self.m.screenshot(record.watch)
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=500)
            digest = self.m._save_shot(record.id, image_bytes)
        taken_at = fa_datetime(time.time(), self.m.tz)
        sent_to_chat = False
        if send_to_chat and hasattr(self.m.notifier, "send_photo"):
            target_chat = uid if (uid and uid != "local") else ((self.m._backup_targets() or [None])[0])
            if target_chat:
                caption = (f"📸 <b>{record.label}</b>\n🕒 {taken_at}\n"
                           f"🔗 {record.watch.page_url}")
                try:
                    await self.m.notifier.send_photo(target_chat, f"{record.id}.jpg", image_bytes, caption)
                    sent_to_chat = True
                except Exception as exc:
                    return web.json_response({"ok": False, "error": f"ارسال به چت تلگرام ناموفق بود: {exc}"}, status=502)
        dl_token = make_download_token(miniapp_secret(self.m.store), uid or "local", f"shot:{key}:{digest}")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return web.json_response({
            "ok": True,
            "digest": digest,
            "filename": f"{record.id}.jpg",
            "download_url": f"/api/app/site/{key}/screenshot/{digest}.jpg?t={dl_token}",
            "sent_to_chat": sent_to_chat,
            "image_data_url": f"data:image/jpeg;base64,{b64}",
            "taken_at": taken_at,
        })

    async def handle_site_screenshot_download(self, request: web.Request) -> web.Response:
        key = self._parse_key(request)
        digest = (request.match_info.get("digest") or "").strip().lower()
        if key is None or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            return web.json_response({"ok": False, "error": "تصویر معتبر نیست"}, status=400)
        token_q = (request.query.get("t") or "").strip()
        authed = False
        if token_q:
            uid = verify_download_token(token_q, miniapp_secret(self.m.store), f"shot:{key}:{digest}")
            if uid:
                if self._is_authorized_user(uid):
                    authed = True
                elif (uid == "local" and not self.m.config.telegram.token
                      and not any(request.headers.get(h) for h in _PROXY_HEADERS)
                      and netguard.is_direct_loopback(getattr(request, "remote", None), request.headers)):
                    authed = True
        if not authed:
            err = self._require_auth(request)
            if err is not None:
                return err
        record = self.m.registry.get(key=key)
        if record is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        path = self.m._shot_path(record.id, digest)
        if path is None:
            return web.json_response({"ok": False, "error": "فایل تصویر پیدا نشد"}, status=404)
        try:
            data = path.read_bytes()
        except OSError:
            return web.json_response({"ok": False, "error": "خطا در خواندن فایل تصویر"}, status=500)
        safe_name = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in record.id) or f"site-{key}"
        return web.Response(
            body=data,
            content_type="image/jpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}.jpg"',
                "Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def handle_site_preview(self, request: web.Request) -> web.Response:
        """Live dry-run extraction preview for a site (optionally testing draft selector/exclude/regex rules)."""
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None or record.watch is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        try:
            raw_body = await request.text()
            data = json.loads(raw_body) if raw_body.strip() else {}
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)

        draft_spec = dict(record.spec, id=record.id)
        if "selector" in data:
            sel_val = str(data.get("selector") or "").strip()
            target_key = "item_selector" if draft_spec.get("type") == "items" else "selector"
            if sel_val:
                draft_spec[target_key] = sel_val
            elif target_key == "selector":
                draft_spec.pop("selector", None)
        if "exclude_selectors" in data:
            raw_ex = data["exclude_selectors"]
            if isinstance(raw_ex, str):
                ex_list = [s.strip() for s in raw_ex.replace("،", ",").splitlines() for s in s.split(",") if s.strip()]
            elif isinstance(raw_ex, list):
                ex_list = [str(s).strip() for s in raw_ex if str(s).strip()]
            else:
                ex_list = []
            if ex_list:
                draft_spec["exclude_selectors"] = ex_list
            else:
                draft_spec.pop("exclude_selectors", None)
        if "ignore_patterns" in data:
            raw_ig = data["ignore_patterns"]
            if isinstance(raw_ig, str):
                ig_list = [s.strip() for s in raw_ig.splitlines() if s.strip()]
            elif isinstance(raw_ig, list):
                ig_list = [str(s).strip() for s in raw_ig if str(s).strip()]
            else:
                ig_list = []
            if ig_list:
                draft_spec["ignore_patterns"] = ig_list
            else:
                draft_spec.pop("ignore_patterns", None)
        if "track_links" in data and draft_spec.get("type", "page") == "page":
            draft_spec["track_links"] = bool(data["track_links"])

        try:
            probe = self.m.registry.validate(draft_spec)
        except ConfigError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

        try:
            parse = self.m._parser(probe)
            result, parsed = await self.m._fetch_parse(
                probe, probe.url, lambda r: parse(probe, r),
                wait_for=probe.wait_selector, remember=False,
            )
        except (FetchError, ExtractError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=422)

        if probe.type in ("page", "json"):
            snap, discovered = parsed
            scoped = [u for _, u in discovered if self.m._crawl_kind(probe, u)] if probe.crawl else []
            lines = list(snap.lines[:40])
            sample_links = [{"text": truncate(txt, 80), "url": u} for txt, u in (snap.links or [])[:12]]
            title = snap.title or ""
            line_count = len(snap.lines)
            char_count = snap.text_length
            links_count = len(snap.links or [])
            crawl_count = len(scoped)
        else:
            items = list(parsed)
            lines = [f"• {truncate(it.title, 140)}" for it in items[:40]]
            sample_links = [{"text": truncate(it.title, 80), "url": it.url} for it in items[:12] if it.url]
            title = ""
            line_count = len(items)
            char_count = sum(len(it.title or "") for it in items)
            links_count = len(sample_links)
            crawl_count = 0

        return web.json_response({
            "ok": True,
            "mode": probe.type,
            "engine": result.engine,
            "engine_label": ENGINE_LABELS.get(result.engine, result.engine),
            "status": result.status,
            "elapsed": round(result.elapsed, 2),
            "title": title,
            "line_count": line_count,
            "char_count": char_count,
            "links_count": links_count,
            "crawl_count": crawl_count,
            "lines": lines,
            "sample_links": sample_links,
        })

    async def handle_site_update(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)
        if "url" in data:
            norm = normalize_input_url(str(data["url"])) or str(data["url"]).strip()
            host = urlsplit(norm).hostname or ""
            if not host or not await netguard.is_public_host(host):
                return web.json_response(
                    {"ok": False, "error": "آدرس‌های داخلی یا خصوصی سرور قابل پایش نیستند"},
                    status=400,
                )
            data = dict(data, url=norm)
        spec = dict(record.spec)
        allowed = {
            "name", "url", "type", "engine", "interval_seconds",
            "enabled", "silent", "alarm", "only_keywords", "track_links",
            "ignore_reorder", "report_style", "notify_mode", "keywords",
        }
        for k, v in data.items():
            if k in allowed:
                spec[k] = v
        if "selector" in data:
            sel_val = str(data.get("selector") or "").strip()
            target_key = "item_selector" if spec.get("type") == "items" else "selector"
            if sel_val:
                spec[target_key] = sel_val
            elif target_key == "selector":
                spec.pop("selector", None)
        if "exclude_selectors" in data:
            raw_ex = data["exclude_selectors"]
            if isinstance(raw_ex, str):
                ex_list = [s.strip() for s in raw_ex.replace("،", ",").splitlines() for s in s.split(",") if s.strip()]
            elif isinstance(raw_ex, list):
                ex_list = [str(s).strip() for s in raw_ex if str(s).strip()]
            else:
                ex_list = []
            if ex_list:
                spec["exclude_selectors"] = ex_list
            else:
                spec.pop("exclude_selectors", None)
        if "ignore_patterns" in data:
            raw_ig = data["ignore_patterns"]
            if isinstance(raw_ig, str):
                ig_list = [s.strip() for s in raw_ig.splitlines() if s.strip()]
            elif isinstance(raw_ig, list):
                ig_list = [str(s).strip() for s in raw_ig if str(s).strip()]
            else:
                ig_list = []
            if ig_list:
                spec["ignore_patterns"] = ig_list
            else:
                spec.pop("ignore_patterns", None)
        if "proxy" in data:
            raw_px = str(data.get("proxy") or "").strip()
            if raw_px in ("", "-", "—", "حذف"):
                spec.pop("proxy", None)
            elif record.watch and record.watch.proxy and raw_px == record.watch.proxy.server and record.spec.get("proxy"):
                spec["proxy"] = record.spec["proxy"]
            else:
                try:
                    Proxy.parse_url(raw_px)
                except ConfigError as exc:
                    return web.json_response({"ok": False, "error": str(exc)}, status=400)
                spec["proxy"] = raw_px
        if "keywords" in data and not spec.get("keywords"):
            spec.pop("only_keywords", None)
        if "crawl_enabled" in data:
            if data["crawl_enabled"] and not spec.get("crawl"):
                spec["crawl"] = default_crawl(spec.get("url", ""))
            elif not data["crawl_enabled"]:
                spec.pop("crawl", None)
        if "interval_seconds" in spec and isinstance(spec.get("crawl"), dict):
            try:
                spec["crawl"] = dict(spec["crawl"], interval_seconds=max(900, int(spec["interval_seconds"])))
            except (TypeError, ValueError):
                pass
        try:
            updated = self.m.registry.update(key, spec)
        except ConfigError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        state_updates = {}
        if "engine" in data:
            state_updates["engine"] = None if spec.get("engine") == "auto" else spec.get("engine")
        if "route" in data and data["route"] in ("direct", "fallback"):
            state_updates["route"] = "fallback" if data["route"] == "fallback" else None
        if state_updates:
            self.m.store.update_watch(record.id, **state_updates)
        await self.m.apply_watch(updated.watch)
        return web.json_response({"ok": True})

    async def handle_apply_suggestion(self, request: web.Request) -> web.Response:
        """Use the selector the monitor found after the old one stopped matching, and check the site once."""
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None or record.watch is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        found = getattr(self.m, "_suggestions", {}).get(record.id)
        if not found:
            return web.json_response({"ok": False, "error": "برای این سایت پیشنهادی وجود ندارد؛ شاید قبلاً اعمال شده یا منقضی شده است."},
                                     status=400)
        spec = dict(record.spec)
        spec["selector"] = found["selector"]
        try:
            updated = self.m.registry.update(key, spec)
        except ConfigError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        self.m._suggestions.pop(record.id, None)
        await self.m.apply_watch(updated.watch)
        outcome = await self.m.check_watch(updated.watch)
        return web.json_response({"ok": True, "selector": found["selector"], "outcome": outcome})

    async def handle_site_reset(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None or record.watch is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        self.m.store.reset_watch(record.id)
        clear_watch_cookies(self.m.config.data_dir, record.id)
        getattr(self.m, "_suggestions", {}).pop(record.id, None)
        getattr(self.m, "_drift", {}).pop(record.id, None)
        self.m.trigger(record.id)
        return web.json_response({"ok": True})

    async def handle_site_cookies(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None or record.watch is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)
        raw = str(data.get("cookies", "")).strip()
        if raw in ("", "-", "—", "حذف"):
            clear_watch_cookies(self.m.config.data_dir, record.id)
            return web.json_response({"ok": True, "cleared": True})
        count = import_watch_cookies(self.m.config.data_dir, record.id, raw, record.watch.url)
        if count <= 0:
            return web.json_response({"ok": False, "error": "هیچ کوکی معتبری در متن ارسالی پیدا نشد"}, status=400)
        self.m.store.update_watch(record.id, consecutive_errors=0, last_error=None)
        self.m.trigger(record.id)
        return web.json_response({"ok": True, "count": count})

    async def handle_site_delete(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        removed = self.m.registry.delete(key)
        if removed is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        await self.m.remove_watch(removed.id)
        return web.json_response({"ok": True})

    async def _run_analysis(self, url: str, proxy=None) -> Analysis:
        try:
            return await asyncio.wait_for(
                analyze(
                    self.m.config, url,
                    http=self.m.http, browser=self.m.browser, impersonate=self.m.impersonate,
                    proxy=proxy,
                ),
                timeout=110,
            )
        except asyncio.TimeoutError:
            return Analysis(url=url, error="بررسی صفحه بیش از حد طول کشید")

    async def handle_analyze(self, request: web.Request) -> web.Response:
        """Smart URL analyzer for the Mini App add-site wizard (parity with Telegram bot wizard)."""
        err = self._require_auth(request)
        if err is not None:
            return err
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)
        raw_url = str(data.get("url", "")).strip()
        url = normalize_input_url(raw_url)
        if not url:
            return web.json_response({"ok": False, "error": "لینک واردشده معتبر نیست"}, status=400)
        host = urlsplit(url).hostname or ""
        if not host or not await netguard.is_public_host(host):
            return web.json_response(
                {"ok": False, "error": "آدرس‌های داخلی یا خصوصی سرور قابل پایش نیستند"},
                status=400,
            )
        analysis = await self._run_analysis(url)
        direct = analysis
        usable = bool(analysis.final_url) and not analysis.error and not analysis.blocked
        if not usable and self.m.config.global_proxy is None:
            fallback = await self.m.fallback_proxy()
            if fallback is not None:
                proxied = await self._run_analysis(url, fallback)
                if proxied.final_url and not proxied.error and not proxied.blocked:
                    analysis = proxied
                else:
                    analysis.notes.append(f"via proxy: {proxied.error or proxied.block_hint or 'blocked'}")
                    analysis.via_proxy = fallback.server

        route = "fallback" if analysis is not direct else ""
        raw_choices = suggest_choices(analysis) if analysis.final_url and not analysis.error else []
        if not raw_choices or (analysis.blocked and not analysis.regions):
            reason = direct.error or (f"صفحهٔ محافظ {direct.block_hint}" if direct.block_hint else "صفحه باز نشد")
            return web.json_response({
                "ok": False,
                "can_add_anyway": True,
                "normalized_url": url,
                "error": f"صفحه از روی سرور باز نشد ({reason}). می‌توانید مستقیم ذخیره کنید تا مانیتور در پس‌زمینه تلاش کند.",
            }, status=422)

        city_filter = str(data.get("city", "")).strip()
        jfilter = {GOETHE["filter_field"]: city_filter} if city_filter else None
        out_choices = []
        for idx, ch in enumerate(raw_choices):
            work = dict(ch)
            if work["type"] == "feed" and "items" not in work and work.get("url") and work["url"] != analysis.final_url:
                try:
                    feed_host = urlsplit(work["url"]).hostname or ""
                    if feed_host and await netguard.is_public_host(feed_host):
                        proxy = await self.m.fallback_proxy() if route else None
                        probe = Watch(id="_preview", url=work["url"], proxy=proxy)
                        fetcher = self.m.http if self.m.http.supports(probe) else self.m.impersonate
                        fres = await fetcher.fetch(work["url"], probe)
                        work["items"] = parse_feed(fres.body or fres.text.encode("utf-8"), fres.final_url)
                except (FetchError, ExtractError):
                    pass
            try:
                lines, total = preview_choice(analysis, work, json_filter=jfilter if work["type"] == "json" else None)
            except ExtractError:
                lines, total = [], 0
            cities = choice_filter_values(analysis, work) if work["type"] == "json" else []
            out_choices.append({
                "index": idx,
                "type": work["type"],
                "label": work.get("label", ""),
                "desc": work.get("desc", ""),
                "recommended": bool(work.get("recommended")),
                "preset": work.get("preset", ""),
                "url": work.get("url") or url,
                "page": work.get("page") or url,
                "selector": work.get("selector", ""),
                "link_selector": work.get("link_selector", ""),
                "exclude": list(work.get("exclude") or []),
                "cities": cities[:40],
                "filter_field": GOETHE["filter_field"] if cities else "",
                "preview": lines[:10],
                "preview_total": total,
            })

        clean_host = host.removeprefix("www.")
        quick = analysis.is_feed or out_choices[0]["type"] in ("items", "json", "headlines", "feed")
        rec_interval = 180 if analysis.protected or route else (60 if quick and not analysis.newsy else 120)
        return web.json_response({
            "ok": True,
            "url": url,
            "final_url": analysis.final_url or url,
            "title": analysis.title or "",
            "suggested_name": smart_name(analysis.title or clean_host, url),
            "engine": analysis.engine or "http",
            "engine_label": ENGINE_NAMES.get(analysis.engine or "http", analysis.engine or "http"),
            "elapsed": round(analysis.elapsed, 1),
            "protected": bool(analysis.protected),
            "newsy": bool(analysis.newsy),
            "is_feed": bool(analysis.is_feed),
            "block_hint": analysis.block_hint or "",
            "route": route,
            "recommended_interval": rec_interval,
            "goethe_keywords": list(GOETHE["keywords"]) if analysis.exam_api else [],
            "choices": out_choices,
        })

    async def handle_add_site(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
            profile = _PROFILES_BY_ID.get(str(data.get("profile") or ""))
            if profile is not None:  # template defaults fill only what the user did not choose explicitly
                data = {**profile["defaults"], **{k: v for k, v in data.items() if v not in (None, "", [])}}
            interval = int(data.get("interval_seconds", 120))
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)
        raw_url = str(data.get("url", "")).strip()
        if not raw_url:
            return web.json_response({"ok": False, "error": "لطفاً آدرس سایت را وارد کنید"}, status=400)
        url = normalize_input_url(raw_url)
        if not url:
            url = raw_url if raw_url.startswith(("http://", "https://")) else ("https://" + raw_url)
        host = urlsplit(url).hostname or ""
        if not host or not await netguard.is_public_host(host):
            return web.json_response(
                {"ok": False, "error": "آدرس‌های داخلی یا خصوصی سرور قابل پایش نیستند"},
                status=400,
            )
        default_style = self.m.store.get_setting("default_report_style", "inline")
        style = str(data.get("report_style") or default_style)
        if style not in REPORT_STYLES:
            style = "inline"
        wtype = str(data.get("type", "page"))
        spec: dict = {
            "url": url,
            "name": str(data.get("name", "")).strip(),
            "type": wtype,
            "engine": str(data.get("engine", "auto")),
            "interval_seconds": interval,
            "report_style": style,
            "ignore_reorder": bool(data.get("ignore_reorder", True)),
        }
        if data.get("alarm"):
            spec["alarm"] = True
        if data.get("silent"):
            spec["silent"] = True
        if wtype == "page":
            spec["track_links"] = bool(data.get("track_links", True))
            if data.get("selector"):
                spec["selector"] = str(data["selector"]).strip()
            if data.get("min_content_length"):
                try:
                    spec["min_content_length"] = max(1, int(data["min_content_length"]))
                except (TypeError, ValueError):
                    pass
            if data.get("crawl_enabled"):
                crawl_cfg = default_crawl(url)
                crawl_cfg["interval_seconds"] = max(900, interval)
                spec["crawl"] = crawl_cfg
        elif wtype == "headlines":
            if data.get("selector"):
                spec["selector"] = str(data["selector"]).strip()
        elif wtype == "items":
            if data.get("item_selector") or data.get("selector"):
                spec["item_selector"] = str(data.get("item_selector") or data.get("selector")).strip()
            if data.get("item_link_selector"):
                spec["item_link_selector"] = str(data["item_link_selector"]).strip()
            if isinstance(data.get("exclude_selectors"), list) and data["exclude_selectors"]:
                spec["exclude_selectors"] = [str(s).strip() for s in data["exclude_selectors"] if str(s).strip()]
        elif wtype == "json":
            spec["link"] = str(data.get("link") or url).strip()
            spec["json_records"] = str(data.get("json_records") or GOETHE["records"])
            spec["json_template"] = str(data.get("json_template") or GOETHE["template"])
            spec["json_labels"] = dict(data.get("json_labels") or GOETHE["labels"])
            if isinstance(data.get("json_filter"), dict) and data["json_filter"]:
                spec["json_filter"] = {str(k): str(v) for k, v in data["json_filter"].items() if str(v).strip()}
        kws = data.get("keywords")
        if isinstance(kws, list):
            spec["keywords"] = [str(k).strip() for k in kws if str(k).strip()]
        elif isinstance(kws, str) and kws.strip():
            spec["keywords"] = [k.strip() for k in kws.replace("،", ",").split(",") if k.strip()]
        if data.get("only_keywords") and spec.get("keywords"):
            spec["only_keywords"] = True
        if str(data.get("notify_mode") or "") in ("text", "screenshot", "both"):
            spec["notify_mode"] = str(data["notify_mode"])
        if wtype != "items" and data.get("exclude_selectors"):
            excl = _split_list(data["exclude_selectors"])
            if excl:
                spec["exclude_selectors"] = excl
        if data.get("ignore_patterns"):
            patterns = _split_list(data["ignore_patterns"], commas=False)
            if patterns:
                spec["ignore_patterns"] = patterns
        raw_px = str(data.get("proxy") or "").strip()
        if raw_px:
            try:
                Proxy.parse_url(raw_px)
            except ConfigError as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=400)
            spec["proxy"] = raw_px
        try:
            record = self.m.registry.add(spec, created_by="miniapp")
        except ConfigError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        state_seed = {}
        pref_engine = str(data.get("preferred_engine") or "")
        if record.watch.engine == "auto" and pref_engine in ("impersonate", "browser"):
            state_seed["engine"] = pref_engine
        if data.get("route") == "fallback":
            state_seed["route"] = "fallback"
        if state_seed:
            self.m.store.update_watch(record.id, **state_seed)
        await self.m.apply_watch(record.watch)
        self.m.trigger(record.id)
        return web.json_response({"ok": True, "key": record.key})

    async def handle_recent_events(self, request: web.Request) -> web.Response:
        """Cross-site activity stream: the newest events of every watch, optionally only changes or errors."""
        err = self._require_auth(request)
        if err is not None:
            return err
        kind = (request.query.get("kind") or request.query.get("filter") or "all").strip()
        if kind not in ("all", *_EVENT_KIND_FILTERS):
            return web.json_response({"ok": False, "error": "فیلتر نامعتبر"}, status=400)
        try:
            limit = max(1, min(100, int(request.query.get("limit") or 40)))
        except ValueError:
            return web.json_response({"ok": False, "error": "تعداد نامعتبر"}, status=400)
        rows = await asyncio.to_thread(self.m.store.recent_events, None, limit, _EVENT_KIND_FILTERS.get(kind))
        records = {r.id: r for r in self.m.registry.records()}
        events = []
        for row in rows:
            item = self._serialize_event(row)
            rec = records.get(row["watch_id"])
            item["site_key"] = rec.key if rec else None
            item["site_label"] = rec.label if rec else row["watch_id"]
            item["blocks_html"] = item["blocks_html"][:2]  # the timeline shows a preview; the report has the rest
            item["has_report"] = bool(item["blocks_html"])
            events.append(item)
        return web.json_response({"ok": True, "kind": kind, "events": events})

    async def handle_bulk(self, request: web.Request) -> web.Response:
        """One action on several sites at once (pause, resume, check, silent on/off, delete)."""
        err = self._require_auth(request)
        if err is not None:
            return err
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
            action = str(data.get("action") or "")
            keys = list(dict.fromkeys(int(k) for k in (data.get("keys") or [])))
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)
        if action not in _BULK_ACTIONS:
            return web.json_response({"ok": False, "error": "عملیات نامعتبر"}, status=400)
        if not keys:
            return web.json_response({"ok": False, "error": "هیچ سایتی انتخاب نشده است"}, status=400)
        if len(keys) > BULK_MAX:
            return web.json_response({"ok": False, "error": f"حداکثر {fa_digits(BULK_MAX)} سایت در هر بار"}, status=400)
        done, failed = 0, []
        for key in keys:
            record = self.m.registry.get(key=key)
            if record is None:
                failed.append({"key": key, "error": "سایت یافت نشد"})
                continue
            try:
                if action == "delete":
                    removed = self.m.registry.delete(key)
                    if removed is not None:
                        await self.m.remove_watch(removed.id)
                elif action == "check":
                    if record.watch is None or not record.watch.enabled:
                        failed.append({"key": key, "error": "سایت فعال نیست"})
                        continue
                    self.m.trigger(record.id)
                else:
                    field, value = {"pause": ("enabled", False), "resume": ("enabled", True),
                                    "silent_on": ("silent", True), "silent_off": ("silent", False)}[action]
                    updated = self.m.registry.update(key, dict(record.spec, **{field: value}))
                    if updated.watch is not None:
                        await self.m.apply_watch(updated.watch)
            except ConfigError as exc:
                failed.append({"key": key, "error": str(exc)})
                continue
            done += 1
        return web.json_response({"ok": True, "action": action, "done": done, "affected": done, "failed": failed[:20]})

    async def handle_site_clone(self, request: web.Request) -> web.Response:
        """Duplicate a site with all its settings (optionally under a new name or for another address)."""
        err = self._require_auth(request)
        if err is not None:
            return err
        key = self._parse_key(request)
        if key is None:
            return web.json_response({"ok": False, "error": "کلید نامعتبر"}, status=400)
        record = self.m.registry.get(key=key)
        if record is None:
            return web.json_response({"ok": False, "error": "سایت یافت نشد"}, status=404)
        try:
            raw = await request.text()
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)
        spec = {k: v for k, v in record.spec.items() if k != "id"}  # a fresh id: history stays with the original
        if str(data.get("url") or "").strip():
            raw_url = str(data["url"]).strip()
            spec["url"] = normalize_input_url(raw_url) or raw_url
            if isinstance(spec.get("crawl"), dict):
                spec["crawl"] = dict(default_crawl(spec["url"]),
                                     interval_seconds=spec["crawl"].get("interval_seconds", 900))
        host = urlsplit(str(spec.get("url") or "")).hostname or ""
        if not host or not await netguard.is_public_host(host):
            return web.json_response({"ok": False, "error": "آدرس‌های داخلی یا خصوصی سرور قابل پایش نیستند"},
                                     status=400)
        spec["name"] = str(data.get("name") or "").strip() or f"{record.label} (کپی)"
        try:
            clone = self.m.registry.add(spec, created_by="miniapp")
        except ConfigError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        if clone.watch is not None:
            await self.m.apply_watch(clone.watch)
            self.m.trigger(clone.id)
        return web.json_response({"ok": True, "key": clone.key, "id": clone.id, "name": clone.label})

    async def handle_check_all(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        self.m.trigger_all()
        return web.json_response({"ok": True, "count": len(self.m.watches)})

    async def handle_clear_outbox(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        watch_id = None
        try:
            data = await request.json()
            if isinstance(data, dict) and data.get("watch_id"):
                watch_id = str(data["watch_id"]).strip()
        except Exception:
            pass
        cleared = self.m.store.clear_pending_events(watch_id)
        return web.json_response({"ok": True, "cleared": cleared})

    async def handle_settings(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)
        store = self.m.store
        if "report_style" in data and data["report_style"] in REPORT_STYLES:
            store.set_setting("default_report_style", data["report_style"])
        if "auto_screenshot" in data:
            store.set_setting("auto_screenshot", "on" if data["auto_screenshot"] else "off")
        if "quiet_hours" in data:
            store.set_setting("quiet_hours", "on" if data["quiet_hours"] else "off")
        if "daily_digest" in data:
            store.set_setting("daily_report", "on" if data["daily_digest"] else "off")
        if "startup_notify" in data:
            store.set_setting("startup_notify", "on" if data["startup_notify"] else "off")
        if "fallback_proxy" in data:
            raw_fp = str(data["fallback_proxy"] or "").strip()
            if raw_fp in ("", "auto", "-"):
                store.set_setting("fallback_proxy", "auto")
            elif raw_fp == "off":
                store.set_setting("fallback_proxy", "off")
            else:
                try:
                    Proxy.parse_url(raw_fp)
                except ConfigError as exc:
                    return web.json_response({"ok": False, "error": str(exc)}, status=400)
                store.set_setting("fallback_proxy", raw_fp)
        return web.json_response({"ok": True})

    async def handle_search(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        q = (request.query.get("q") or "").strip()
        if not q:
            return web.json_response({"ok": True, "results": []})
        rows = await asyncio.to_thread(self.m.store.search_events, q, 25)
        return web.json_response({"ok": True, "results": [self._serialize_event(r) for r in rows]})

    async def handle_event_report(self, request: web.Request) -> web.Response:
        """Render a standalone interactive dark/light HTML diff document for one historical event."""
        err = self._require_auth(request)
        if err is not None:
            return err
        try:
            event_id = int(request.match_info["event_id"])
        except (KeyError, TypeError, ValueError):
            return web.json_response({"ok": False, "error": "شناسهٔ رویداد نامعتبر است"}, status=400)
        row = self.m.store.get_event(event_id)
        if row is None:
            return web.json_response({"ok": False, "error": "این رویداد پیدا نشد"}, status=404)
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "دادهٔ رویداد قابل خواندن نیست"}, status=422)
        blocks = payload.get("full_blocks") or payload.get("blocks") or []
        if not blocks:
            return web.json_response({"ok": False, "error": "این رویداد محتوای قابل نمایشی ندارد"}, status=422)
        doc_title = payload.get("doc_title") or f"گزارش رویداد #{event_id}"
        html_doc = render_document(doc_title, payload.get("header") or "", blocks)
        filename = f"event-{event_id}-{time.strftime('%Y%m%d-%H%M')}.html"
        return web.json_response({
            "ok": True,
            "id": event_id,
            "filename": filename,
            "html": html_doc,
        })

    async def handle_export(self, request: web.Request) -> web.Response:
        """Export all watch definitions as a portable JSON bundle (redacting proxy/auth secrets by default)."""
        err = self._require_auth(request)
        if err is not None:
            return err
        redact = request.query.get("redact", "1") != "0"
        sensitive_headers = {"authorization", "cookie", "proxy-authorization", "x-api-key"}
        specs = []
        for record in self.m.registry.records():
            spec = dict(record.spec)
            if redact:
                spec.pop("proxy", None)
                if isinstance(spec.get("headers"), dict):
                    spec["headers"] = {
                        k: ("REDACTED" if str(k).lower() in sensitive_headers else v)
                        for k, v in spec["headers"].items()
                    }
            specs.append(spec)
        stamp = time.strftime("%Y%m%d-%H%M")
        bundle = {"exported": format_ts(time.time(), self.m.tz), "watches": specs}
        return web.json_response({
            "ok": True,
            "count": len(specs),
            "filename": f"watches-{stamp}.json",
            "bundle": bundle,
        })

    async def handle_import(self, request: web.Request) -> web.Response:
        """Import a JSON backup bundle of watches with deduplication and SSRF host validation."""
        err = self._require_auth(request)
        if err is not None:
            return err
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ JSON معتبر نیست"}, status=400)

        payload_obj = data.get("bundle", data)
        if isinstance(data.get("raw"), str):
            try:
                payload_obj = json.loads(data["raw"].lstrip("\ufeff"))
            except ValueError:
                return web.json_response({"ok": False, "error": "متن JSON پشتیبان معتبر نیست"}, status=400)
        specs = payload_obj.get("watches") if isinstance(payload_obj, dict) else payload_obj
        if not isinstance(specs, list):
            return web.json_response({"ok": False, "error": "در فایل ارسالی فهرست سایتی پیدا نشد"}, status=400)
        if len(specs) > 200:
            return web.json_response({"ok": False, "error": "حداکثر ۲۰۰ سایت در هر بار درون‌ریزی مجاز است"}, status=400)

        records = self.m.registry.records()
        known_ids = {r.id for r in records}
        known = {(r.spec.get("url"), r.spec.get("selector"), r.spec.get("item_selector")) for r in records}
        added, duplicates, invalid = 0, 0, 0
        errors: list[str] = []

        for raw_spec in specs:
            if not isinstance(raw_spec, dict) or not str(raw_spec.get("url") or "").strip():
                invalid += 1
                continue
            raw_url = str(raw_spec["url"]).strip()
            url = normalize_input_url(raw_url) or raw_url
            host = urlsplit(url).hostname or ""
            if not host or not await netguard.is_public_host(host):
                invalid += 1
                errors.append(f"آدرس داخلی/نامعتبر رد شد: {truncate(raw_url, 60)}")
                continue
            clean_spec = dict(raw_spec, url=url)
            if clean_spec.get("link"):
                link_url = str(clean_spec["link"]).strip()
                link_host = urlsplit(link_url).hostname or ""
                if not link_host or not await netguard.is_public_host(link_host):
                    invalid += 1
                    errors.append(f"لینک داخلی/نامعتبر رد شد: {truncate(link_url, 60)}")
                    continue
            dedup_sig = (url, clean_spec.get("selector"), clean_spec.get("item_selector"))
            if clean_spec.get("id") in known_ids or dedup_sig in known:
                duplicates += 1
                continue
            try:
                record = self.m.registry.add(clean_spec, created_by="miniapp")
            except ConfigError as exc:
                invalid += 1
                errors.append(str(exc))
                continue
            known_ids.add(record.id)
            known.add(dedup_sig)
            await self.m.apply_watch(record.watch)
            self.m.trigger(record.id)
            added += 1

        return web.json_response({
            "ok": True,
            "added": added,
            "duplicates": duplicates,
            "invalid": invalid,
            "errors": errors[:5],
        })

    async def handle_challenge_frame(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        token = request.match_info["token"]
        sess = self.m.challenge.get(token) if getattr(self.m, "challenge", None) else None
        if sess is None or sess.frame_fn is None:
            return web.json_response({"ok": False, "error": "چالش منقضی یا بسته شده است"}, status=404)
        try:
            frame = await self.m.challenge.capture_frame(sess)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)
        b64 = base64.b64encode(frame).decode("ascii")
        return web.json_response({
            "ok": True,
            "image_data_url": f"data:image/jpeg;base64,{b64}",
            "remaining": max(0, int(sess.expires_at - time.time())),
        })

    async def handle_challenge_action(self, request: web.Request) -> web.Response:
        err = self._require_auth(request)
        if err is not None:
            return err
        token = request.match_info["token"]
        sess = self.m.challenge.get(token) if getattr(self.m, "challenge", None) else None
        if sess is None:
            return web.json_response({"ok": False, "error": "چالش منقضی شده است"}, status=404)
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            return web.json_response({"ok": False, "error": "دادهٔ نامعتبر"}, status=400)
        act = data.get("action")
        if act == "click" and sess.click_fn:
            try:
                x = float(data.get("x", 640))
                y = float(data.get("y", 450))
            except (TypeError, ValueError):
                return web.json_response({"ok": False, "error": "مختصات نامعتبر"}, status=400)
            async with sess.solving_lock:
                await sess.click_fn(x, y)
            return web.json_response({"ok": True})
        if act == "turnstile":
            turnstile_fn = getattr(sess, "click_turnstile_fn", None)
            async with sess.solving_lock:
                if turnstile_fn is not None:
                    await turnstile_fn()
                elif sess.click_fn is not None:
                    await sess.click_fn(255.0, 290.0)
            return web.json_response({"ok": True})
        if act == "type" and sess.type_fn:
            async with sess.solving_lock:
                await sess.type_fn(str(data.get("text", ""))[:500])
            return web.json_response({"ok": True})
        if act == "key" and getattr(sess, "key_fn", None):
            key_name = str(data.get("key", "Enter"))[:30]
            async with sess.solving_lock:
                await sess.key_fn(key_name)
            return web.json_response({"ok": True})
        if act == "done":
            if not data.get("force"):
                html_fn = getattr(sess, "html_fn", None)
                if callable(html_fn):
                    try:
                        html = await html_fn()
                    except Exception:
                        html = ""
                    hint = detect_block(html, 200) if html else None
                    if hint:
                        return web.json_response({
                            "ok": False,
                            "still_blocked": True,
                            "hint": hint,
                            "error": f"صفحه هنوز شبیه چالش ({hint}) است؛ اگر مطمئنید حل شده دوباره «✅ حل شد» را بزنید.",
                        }, status=409)
            await self.m.challenge.complete(token)
            return web.json_response({"ok": True, "completed": True})
        if act == "cancel":
            await self.m.challenge.cancel(token)
            return web.json_response({"ok": True, "cancelled": True})
        return web.json_response({"ok": False, "error": "عملیات نامعتبر"}, status=400)


# The page itself (HTML, CSS and JavaScript) lives in miniapp_ui.py.

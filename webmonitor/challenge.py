"""Challenge server (Sprint 3.2) — solves bot walls by hand through a private tunnel.

Design
------
* Binds to 127.0.0.1 by default: nothing is exposed to the internet.
* The admin opens an SSH tunnel:
    ssh -L 8899:127.0.0.1:8899 user@server
  then loads the URL the bot sent (e.g. http://127.0.0.1:8899/c/<token>).
* Every challenge gets a random single-use token, valid for a few minutes.

This module is *infrastructure only*: it exposes a small HTTP API and an
in-memory session registry. It does not drive Playwright itself; that is wired
in Sprint 3.3 (engine.py) so the two pieces can be tested independently.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from aiohttp import web

log = logging.getLogger("webmonitor")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8899
DEFAULT_TTL_SECONDS = 10 * 60      # 10 minutes
FRAME_INTERVAL = 1.2               # seconds between MJPEG frames
MIN_CAPTURE_INTERVAL = 0.45        # reuse recent frame across concurrent viewers
MAX_STREAMS_PER_SESSION = 2        # guard Chromium from multiple open stream tabs
MAX_FRAME_BYTES = 4 * 1024 * 1024  # guard against runaway pages
RATE_LIMIT_WINDOW = 60.0           # seconds for invalid-token window
RATE_LIMIT_MAX_FAILURES = 20       # max invalid token lookups per IP per minute
_CSP_HEADER = (
    "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)

# Injection hooks — Sprint 3.3 fills these in with Playwright calls.
ClickFn = Callable[[float, float], Awaitable[None]]
TypeFn = Callable[[str], Awaitable[None]]
KeyFn = Callable[[str], Awaitable[None]]
FrameFn = Callable[[], Awaitable[bytes]]
DoneFn = Callable[[], Awaitable[None]]      # save storage_state / close context
CancelFn = Callable[[], Awaitable[None]]    # close without saving
AutoClickFn = Callable[[], Awaitable[bool]]
HtmlFn = Callable[[], Awaitable[str]]


@dataclass
class ChallengeSession:
    """One in-flight challenge awaiting a human."""
    token: str
    watch_id: str
    watch_label: str
    url: str
    created_at: float = field(default_factory=time.time)
    ttl: float = DEFAULT_TTL_SECONDS
    last_frame: bytes = b""
    last_frame_at: float = 0.0
    active_streams: int = 0
    solving_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # These are filled by the owner (Sprint 3.3).
    frame_fn: FrameFn | None = None
    click_fn: ClickFn | None = None
    type_fn: TypeFn | None = None
    key_fn: KeyFn | None = None
    done_fn: DoneFn | None = None
    cancel_fn: CancelFn | None = None
    click_turnstile_fn: AutoClickFn | None = None
    html_fn: HtmlFn | None = None

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


def _check_csrf(request: web.Request) -> str | None:
    """Block cross-origin browser POSTs against localhost tunnel endpoints."""
    sec_site = (request.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if sec_site == "cross-site":
        return "cross-site request blocked"
    origin = (request.headers.get("Origin") or "").strip()
    if origin:
        if origin.lower() == "null":
            return "origin mismatch"
        origin_host = (urlsplit(origin).netloc or "").lower()
        req_host = (request.host or "").lower()
        if not origin_host or (req_host and origin_host != req_host):
            return "origin mismatch"
    return None


class ChallengeManager:
    """Owns the HTTP server and the token → session map."""

    def __init__(self, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 ttl_seconds: float = DEFAULT_TTL_SECONDS):
        self.host = host
        self.port = port
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, ChallengeSession] = {}
        self._failed_lookups: dict[str, list[float]] = {}
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._purge_task: asyncio.Task | None = None
        self._public_base: str | None = None  # set by engine when known
        self._pending_watchers: dict[str, asyncio.Future] = {}
        self._route_installers: list[Callable[[web.Application], None]] = []
        self.health_provider: Callable[[], dict] | None = None  # set by the engine (see health.py)

    def add_routes(self, installer: Callable[[web.Application], None]) -> None:
        self._route_installers.append(installer)

    def _client_ip(self, request: web.Request) -> str:
        remote = str(getattr(request, "remote", None) or "local").strip()
        # Trust X-Real-IP ONLY on direct loopback connections (Nginx on oracle-server overwrites
        # X-Real-IP with $remote_addr on /app, /api/app/, and /c/, so external clients cannot spoof it).
        if remote in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            real_ip = (request.headers.get("X-Real-IP") or "").strip()
            if real_ip and len(real_ip) <= 64 and "\n" not in real_ip and "\r" not in real_ip:
                return real_ip
        return remote

    def _is_rate_limited(self, ip: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        hits = self._failed_lookups.get(ip)
        if not hits:
            return False
        cutoff = now - RATE_LIMIT_WINDOW
        fresh = [t for t in hits if t >= cutoff]
        if fresh:
            self._failed_lookups[ip] = fresh
        else:
            self._failed_lookups.pop(ip, None)
        return len(fresh) >= RATE_LIMIT_MAX_FAILURES

    def _record_invalid_token(self, ip: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        cutoff = now - RATE_LIMIT_WINDOW
        if len(self._failed_lookups) > 256 and ip not in self._failed_lookups:
            # Evict stale/oldest entries instead of clearing the entire table.
            for k in list(self._failed_lookups):
                kept = [t for t in self._failed_lookups[k] if t >= cutoff]
                if kept:
                    self._failed_lookups[k] = kept
                else:
                    self._failed_lookups.pop(k, None)
            if len(self._failed_lookups) > 256:
                oldest = min(self._failed_lookups, key=lambda k: self._failed_lookups[k][-1])
                self._failed_lookups.pop(oldest, None)
        fresh = [t for t in self._failed_lookups.get(ip, ()) if t >= cutoff]
        fresh.append(now)
        self._failed_lookups[ip] = fresh

    async def _capture_frame_unlocked(self, session: ChallengeSession) -> bytes:
        """Capture or reuse a recent frame; caller must hold ``session.solving_lock``."""
        now = time.time()
        if session.last_frame and (now - session.last_frame_at) < MIN_CAPTURE_INTERVAL:
            return session.last_frame
        if session.frame_fn is None:
            return b""
        frame = await session.frame_fn()
        if frame:
            session.last_frame = frame
            session.last_frame_at = time.time()
        return frame

    async def capture_frame(self, session: ChallengeSession) -> bytes:
        """Serialized frame capture using ``session.solving_lock`` (no nested lock acquisition)."""
        async with session.solving_lock:
            return await self._capture_frame_unlocked(session)

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        if self._runner is not None:
            return
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/c/{token}", self._handle_page)
        app.router.add_get("/c/{token}/frame.mjpg", self._handle_frame)
        app.router.add_post("/c/{token}/click", self._handle_click)
        app.router.add_post("/c/{token}/auto", self._handle_auto)
        app.router.add_post("/c/{token}/type", self._handle_type)
        app.router.add_post("/c/{token}/key", self._handle_key)
        app.router.add_post("/c/{token}/done", self._handle_done)
        app.router.add_post("/c/{token}/cancel", self._handle_cancel)
        for installer in self._route_installers:
            installer(app)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        try:
            self._site = web.TCPSite(self._runner, self.host, self.port)
            await self._site.start()
        except OSError as exc:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            raise RuntimeError(f"challenge server could not bind to {self.host}:{self.port}: {exc}") from exc
        self._purge_task = asyncio.create_task(self._purge_loop())
        log.info("Challenge server listening on http://%s:%d (admin tunnel)", self.host, self.port)

    async def close(self) -> None:
        if self._purge_task is not None:
            self._purge_task.cancel()
            try:
                await self._purge_task
            except (asyncio.CancelledError, Exception):
                pass
            self._purge_task = None
        # Cancel any live sessions cleanly.
        for token in list(self._sessions):
            await self.cancel(token, notify=False)
        self._pending_watchers.clear()
        self._failed_lookups.clear()
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    # ------------------------------------------------------------------ sessions

    def new_token(self) -> str:
        return secrets.token_hex(16)  # 32 hex chars

    def create(self, *, watch_id: str, watch_label: str, url: str) -> ChallengeSession:
        token = self.new_token()
        session = ChallengeSession(token=token, watch_id=watch_id, watch_label=watch_label, url=url,
                                   ttl=self.ttl_seconds)
        self._sessions[token] = session
        return session

    def get(self, token: str) -> ChallengeSession | None:
        session = self._sessions.get(token)
        if session is None or session.expired:
            if session is not None:
                self._sessions.pop(token, None)
            return None
        return session

    def count(self) -> int:
        return len(self._sessions)

    async def cancel(self, token: str, notify: bool = True) -> bool:
        session = self._sessions.pop(token, None)
        if session is None:
            return False
        if session.cancel_fn is not None:
            try:
                await session.cancel_fn()
            except Exception:
                log.debug("challenge cancel_fn failed", exc_info=True)
        fut = self._pending_watchers.pop(token, None)
        if notify and fut is not None and not fut.done():
            fut.set_result(("cancelled", None))
        return True

    async def complete(self, token: str) -> bool:
        session = self._sessions.pop(token, None)
        if session is None:
            return False
        if session.done_fn is not None:
            try:
                await session.done_fn()
            except Exception:
                log.debug("challenge done_fn failed", exc_info=True)
        fut = self._pending_watchers.pop(token, None)
        if fut is not None and not fut.done():
            fut.set_result(("done", None))
        return True

    def await_result(self, token: str) -> asyncio.Future:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_watchers[token] = fut
        return fut

    # ------------------------------------------------------------------ housekeeping

    async def _purge_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                now = time.time()
                for token, session in list(self._sessions.items()):
                    if session.expires_at < now:
                        log.info("Challenge session %s… expired", token[:8])
                        await self.cancel(token)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("challenge purge failed")

    # ------------------------------------------------------------------ HTTP handlers

    async def _handle_health(self, _request: web.Request) -> web.Response:
        data = {"ok": True, "sessions": self.count(), "host": self.host, "port": self.port}
        status = 200
        if self.health_provider is not None:
            try:
                report = self.health_provider()
            except Exception as exc:  # the probe itself must never take the server down
                log.exception("health report failed")
                report = {"status": "down", "problems": [f"health report failed: {type(exc).__name__}"]}
            data.update(report)
            data["ok"] = report.get("status") != "down"
            status = 503 if report.get("status") == "down" else 200
        return web.json_response(data, status=status)

    async def _handle_page(self, request: web.Request) -> web.Response:
        ip = self._client_ip(request)
        token = request.match_info["token"]
        session = self.get(token)
        if session is None:
            if self._is_rate_limited(ip):
                return web.Response(status=429, text="too many invalid attempts", content_type="text/plain")
            self._record_invalid_token(ip)
            return web.Response(status=404, text="link expired or invalid", content_type="text/plain")
        remaining = max(0, int(session.expires_at - time.time()))
        html = (_PAGE_HTML
                .replace("__TOKEN__", _escape(token))
                .replace("__LABEL__", _escape(session.watch_label))
                .replace("__URL__", _escape(session.url))
                .replace("__TTL__", str(remaining)))
        return web.Response(
            text=html,
            content_type="text/html",
            charset="utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": _CSP_HEADER,
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    async def _handle_frame(self, request: web.Request) -> web.StreamResponse:
        ip = self._client_ip(request)
        token = request.match_info["token"]
        session = self.get(token)
        if session is None or session.frame_fn is None:
            if session is None:
                if self._is_rate_limited(ip):
                    return web.Response(status=429, text="too many invalid attempts", content_type="text/plain")
                self._record_invalid_token(ip)
            return web.Response(status=404, text="not found", content_type="text/plain")
        if session.active_streams >= MAX_STREAMS_PER_SESSION:
            return web.Response(status=429, text="too many concurrent streams", content_type="text/plain")
        boundary = "frame"
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
        session.active_streams += 1
        try:
            await response.prepare(request)
            while True:
                session = self.get(token)
                if session is None:
                    break
                try:
                    frame = await self.capture_frame(session)
                except Exception:
                    frame = b""
                if frame and len(frame) <= MAX_FRAME_BYTES:
                    header = (f"--{boundary}\r\n"
                              f"Content-Type: image/jpeg\r\n"
                              f"Content-Length: {len(frame)}\r\n\r\n").encode("ascii")
                    await response.write(header + frame + b"\r\n")
                await asyncio.sleep(FRAME_INTERVAL)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            cur = self._sessions.get(token)
            if cur is not None and cur.active_streams > 0:
                cur.active_streams -= 1
            try:
                await response.write_eof()
            except Exception:
                pass
        return response

    async def _handle_click(self, request: web.Request) -> web.Response:
        session, error = await self._require(request)
        if session is None:
            return error
        try:
            data = await request.json()
            x = float(data.get("x", -1))
            y = float(data.get("y", -1))
        except Exception:
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        if x < 0 or y < 0 or session.click_fn is None:
            return web.json_response({"ok": False, "error": "no click handler or bad coords"}, status=400)
        async with session.solving_lock:
            try:
                await session.click_fn(x, y)
            except Exception as exc:
                log.warning("challenge click failed: %s", exc)
                return web.json_response({"ok": False, "error": str(exc)[:200]}, status=500)
        return web.json_response({"ok": True})

    async def _handle_auto(self, request: web.Request) -> web.Response:
        session, error = await self._require(request)
        if session is None:
            return error
        async with session.solving_lock:
            try:
                if session.click_turnstile_fn is not None:
                    clicked = await session.click_turnstile_fn()
                elif session.click_fn is not None:
                    await session.click_fn(210, 290)
                    clicked = True
                else:
                    return web.json_response({"ok": False, "error": "no click handler"}, status=400)
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)[:200]}, status=500)
        return web.json_response({"ok": True, "clicked": bool(clicked)})

    async def _handle_type(self, request: web.Request) -> web.Response:
        session, error = await self._require(request)
        if session is None:
            return error
        try:
            data = await request.json()
            text = str(data.get("text", ""))[:2000]
        except Exception:
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        if not text or session.type_fn is None:
            return web.json_response({"ok": False, "error": "no type handler"}, status=400)
        async with session.solving_lock:
            try:
                await session.type_fn(text)
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)[:200]}, status=500)
        return web.json_response({"ok": True})

    async def _handle_key(self, request: web.Request) -> web.Response:
        session, error = await self._require(request)
        if session is None:
            return error
        try:
            data = await request.json()
            key = str(data.get("key", ""))[:20]
        except Exception:
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        if not key or session.key_fn is None:
            return web.json_response({"ok": False, "error": "no key handler"}, status=400)
        async with session.solving_lock:
            try:
                await session.key_fn(key)
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)[:200]}, status=500)
        return web.json_response({"ok": True})

    async def _handle_done(self, request: web.Request) -> web.Response:
        session, error = await self._require(request)
        if session is None:
            return error
        await self.complete(session.token)
        return web.json_response({"ok": True, "message": "done"})

    async def _handle_cancel(self, request: web.Request) -> web.Response:
        session, error = await self._require(request)
        if session is None:
            return error
        await self.cancel(session.token)
        return web.json_response({"ok": True, "message": "cancelled"})

    async def _require(self, request: web.Request):
        csrf_err = _check_csrf(request)
        if csrf_err:
            return None, web.json_response({"ok": False, "error": csrf_err}, status=403)
        ip = self._client_ip(request)
        token = request.match_info["token"]
        session = self.get(token)
        if session is None:
            if self._is_rate_limited(ip):
                return None, web.json_response({"ok": False, "error": "too many invalid attempts"}, status=429)
            self._record_invalid_token(ip)
            return None, web.json_response({"ok": False, "error": "link expired"}, status=404)
        return session, None


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


# --------------------------------------------------------------------------- page

_PAGE_HTML = """<!doctype html>
<html lang="fa" dir="rtl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#090d14">
<title>حل چالش — __LABEL__</title>
<style>
  :root { color-scheme: dark; --ease-out: cubic-bezier(0.23, 1, 0.32, 1); }
  * { box-sizing: border-box; }
  :focus-visible { outline: 2px solid #3b82f6; outline-offset: 2px; border-radius: 6px; }
  body { font-family: Vazirmatn, Tahoma, system-ui, sans-serif; margin: 0; background: #090d14; color: #f1f5f9; }
  header { padding: 12px 16px; background: #111826; border-bottom: 1px solid #243046; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
  header h1 { font-size: 16px; margin: 0 0 4px; font-weight: 700; }
  header .url { font-size: 12px; color: #9aa8bd; word-break: break-all; }
  main { display: grid; grid-template-columns: 1fr 350px; gap: 0; height: calc(100vh - 68px); }
  @media (max-width: 900px) {
    main { grid-template-columns: 1fr; height: auto; }
    #stage { max-height: 60vh; border-bottom: 1px solid #243046; }
  }
  #stage { position: relative; background: #05070a; overflow: auto; overscroll-behavior: contain; display: flex; justify-content: center; align-items: flex-start; }
  #frame { display: block; max-width: 100%; height: auto; cursor: crosshair; touch-action: manipulation; }
  .ripple { position: absolute; width: 20px; height: 20px; border-radius: 50%; border: 2px solid #38bdf8; box-shadow: 0 0 10px rgba(56,189,248,.6); transform: translate(-50%, -50%); pointer-events: none; animation: pop .45s var(--ease-out) forwards; }
  @keyframes pop { from { opacity: 1; transform: translate(-50%, -50%) scale(0.45); } to { opacity: 0; transform: translate(-50%, -50%) scale(2.3); } }
  aside { padding: 16px; background: #0e1420; border-inline-start: 1px solid #243046; overflow: auto; overscroll-behavior: contain; }
  aside h2 { font-size: 12px; color: #9aa8bd; margin: 14px 0 8px; font-weight: 700; }
  aside h2:first-child { margin-top: 0; }
  aside p { font-size: 12.5px; color: #cbd5e1; line-height: 1.75; margin: 0 0 10px; }
  .row { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  input[type=text] { flex: 1; min-width: 140px; min-height: 40px; padding: 9px 11px; background: #090d14; border: 1px solid #2a364d; border-radius: 8px; color: #f1f5f9; font-size: 14px; }
  input[type=text]:focus { border-color: #3b82f6; }
  button { min-height: 40px; padding: 9px 13px; border: 1px solid #2a364d; background: #172032; color: #f1f5f9; border-radius: 8px; cursor: pointer; font-size: 13px; font-family: inherit; touch-action: manipulation;
    transition: background-color 140ms var(--ease-out), border-color 140ms var(--ease-out), transform 120ms var(--ease-out); }
  button:active:not(:disabled) { transform: scale(0.97); }
  @media (hover: hover) and (pointer: fine) {
    button:hover:not(:disabled) { background: #222e46; border-color: #3a4a68; }
    button.primary:hover:not(:disabled) { background: #1d4ed8; }
    button.accent:hover:not(:disabled)  { background: #115e59; }
    button.danger:hover:not(:disabled)  { background: #991b1b; }
  }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  button.primary { background: #2563eb; border-color: #2563eb; font-weight: 600; flex: 1; }
  button.accent  { background: #0f766e; border-color: #0d9488; width: 100%; font-weight: 600; }
  button.danger  { background: #7f1d1d; border-color: #991b1b; }
  .keys button { flex: 1; min-width: 58px; direction: ltr; }
  #status { margin-top: 12px; padding: 8px 10px; border-radius: 8px; background: #090d14; border: 1px solid #1e293b; font-size: 12.5px; color: #93c5fd; min-height: 38px; display: flex; align-items: center; }
  .badge { display: inline-flex; align-items: center; gap: 4px; padding: 4px 9px; border-radius: 6px; background: #1a2436; font-size: 11.5px; color: #cbd5e1; font-variant-numeric: tabular-nums; }
  #timer { font-variant-numeric: tabular-nums; color: #fbbf24; font-weight: 700; }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
</head><body>
<header>
  <div>
    <h1>🛡 حل چالش امنیتی «__LABEL__»</h1>
    <div class="url">🔗 <span dir="ltr">__URL__</span> · <span class="badge">token: __TOKEN__</span></div>
  </div>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <div class="badge" id="coords" dir="ltr">1280×900</div>
    <div class="badge" aria-live="off">⏱ زمان باقی‌مانده: <span id="timer" dir="ltr">--:--</span></div>
  </div>
</header>
<main>
  <section id="stage" aria-label="نمایش زنده مرورگر سرور">
    <img id="frame" src="/c/__TOKEN__/frame.mjpg" alt="تصویر زنده صفحه چالش در مرورگر سرور">
  </section>
  <aside>
    <h2>راهنمای سریع</h2>
    <p>روی هر نقطه از تصویر کلیک کنید تا دقیقاً همان‌جا در مرورگر سرور کلیک شود. برای Turnstile کلادفلر می‌توانید دکمهٔ خودکار زیر را بزنید.</p>
    <div class="row">
      <button id="btn-auto" type="button" class="accent">🎯 کلیک خودکار روی مربع کپچا</button>
    </div>
    <h2>تایپ متن در کادر انتخاب‌شده</h2>
    <div class="row">
      <input id="text" type="text" placeholder="متن برای تایپ…" aria-label="متن برای تایپ در مرورگر" autocomplete="off" autocapitalize="off" spellcheck="false">
      <button id="btn-type" type="button" aria-label="ارسال متن">ارسال</button>
    </div>
    <h2>کلیدهای کنترلی و اسکرول</h2>
    <div class="row keys">
      <button type="button" data-key="Enter">Enter ↵</button>
      <button type="button" data-key="Tab">Tab ⇥</button>
      <button type="button" data-key="Backspace">⌫</button>
      <button type="button" data-key="Escape">Esc</button>
    </div>
    <div class="row keys">
      <button type="button" data-key="PageUp">PgUp ↑</button>
      <button type="button" data-key="PageDown">PgDn ↓</button>
    </div>
    <h2>ثبت نتیجه</h2>
    <div class="row">
      <button id="btn-done" type="button" class="primary">✅ حل شد (ذخیره کوکی)</button>
      <button id="btn-cancel" type="button" class="danger">❌ انصراف</button>
    </div>
    <div id="status" role="status" aria-live="polite">آماده دریافت دستور شما…</div>
  </aside>
</main>
<script>
const TOKEN = "__TOKEN__";
let remaining = parseInt("__TTL__", 10) || 600;
const timerEl = document.getElementById("timer");
const statusEl = document.getElementById("status");
const coordsEl = document.getElementById("coords");
function renderTimer() {
  const m = String(Math.floor(remaining / 60)).padStart(2, "0");
  const s = String(remaining % 60).padStart(2, "0");
  timerEl.textContent = `${m}:${s}`;
  if (remaining <= 0) {
    statusEl.textContent = "⛔ مهلت این لینک به پایان رسید.";
  }
}
renderTimer();
setInterval(() => { if (remaining > 0) { remaining--; renderTimer(); } }, 1000);

const stage = document.getElementById("stage");
const frame = document.getElementById("frame");
frame.addEventListener("mousemove", (ev) => {
  const rect = frame.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const x = Math.round((ev.clientX - rect.left) * ((frame.naturalWidth || 1280) / rect.width));
  const y = Math.round((ev.clientY - rect.top) * ((frame.naturalHeight || 900) / rect.height));
  coordsEl.textContent = `${x}, ${y}`;
});
frame.addEventListener("click", async (ev) => {
  const rect = frame.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const natW = frame.naturalWidth || 1280;
  const natH = frame.naturalHeight || 900;
  const x = Math.round((ev.clientX - rect.left) * (natW / rect.width));
  const y = Math.round((ev.clientY - rect.top)  * (natH / rect.height));
  coordsEl.textContent = `${x}, ${y}`;
  const sRect = stage.getBoundingClientRect();
  const dot = document.createElement("div");
  dot.className = "ripple";
  dot.style.left = `${ev.clientX - sRect.left + stage.scrollLeft}px`;
  dot.style.top  = `${ev.clientY - sRect.top  + stage.scrollTop}px`;
  stage.appendChild(dot);
  setTimeout(() => dot.remove(), 500);
  await post(`/c/${TOKEN}/click`, {x, y});
});

const textInput = document.getElementById("text");
textInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") { ev.preventDefault(); sendType(); }
});
document.getElementById("btn-type").addEventListener("click", sendType);
document.getElementById("btn-auto").addEventListener("click", () => post(`/c/${TOKEN}/auto`, {}));
document.querySelectorAll("[data-key]").forEach((btn) => {
  btn.addEventListener("click", () => sendKey(btn.getAttribute("data-key")));
});
document.getElementById("btn-done").addEventListener("click", done);
document.getElementById("btn-cancel").addEventListener("click", cancel);

async function sendType() {
  const text = textInput.value;
  if (!text) return;
  const ok = await post(`/c/${TOKEN}/type`, {text});
  if (ok) {
    textInput.value = "";
    await sendKey("Enter");
  }
}
async function sendKey(key) { await post(`/c/${TOKEN}/key`, {key}); }
async function done() {
  if (!confirm("مطمئنید چالش حل شد؟ کوکی‌های نشست ذخیره می‌شود.")) return;
  const ok = await post(`/c/${TOKEN}/done`, {});
  if (ok) lockUi("✅ چالش با موفقیت ثبت شد. می‌توانید این تب را ببندید.");
}
async function cancel() {
  if (!confirm("انصراف از حل چالش؟")) return;
  const ok = await post(`/c/${TOKEN}/cancel`, {});
  if (ok) lockUi("❌ عملیات لغو شد.");
}
function lockUi(msg) {
  document.querySelectorAll("button, input").forEach((el) => { el.disabled = true; });
  statusEl.textContent = msg;
}
async function post(path, body) {
  statusEl.textContent = "⏳ در حال ارسال…";
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body || {})
    });
    const j = await r.json().catch(() => ({}));
    statusEl.textContent = r.ok ? "✅ انجام شد" : ("❌ " + (j.error || r.status));
    return r.ok;
  } catch (_e) {
    statusEl.textContent = "❌ خطای ارتباط با سرور";
    return false;
  }
}
</script>
</body></html>
"""

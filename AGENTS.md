# AGENTS.md — WebMonitor Project Guide

## Overview
**WebMonitor** (`webmonitor/`) is an enterprise-grade, asynchronous website change monitor (embassy pages, appointment portals, news, RSS/Atom, JSON endpoints, Telegram channels, and subpage crawlers) with a Persian Telegram admin panel, a full RTL Telegram Mini App (`/app`), 3-tier anti-bot fetching (`http` -> `impersonate` via `curl_cffi` -> `browser` via stealth Patchright/Playwright + automatic Cloudflare Turnstile solver + 1-tap Telegram/Mini App/SSH tunnel CAPTCHA solver), full SSRF & DNS-rebinding protection across all engines, transactional SQLite WAL outbox (`data/monitor.db`), and 3-mode word-by-word diff reporting (`inline`, `before_after`, `side_by_side`).

## Architecture & Module Map
- [`monitor_system.py`](monitor_system.py): Entry point (`run`, `once`, `inspect`, `preview`, `validate`, `health`, `diagnose`, `history`, `reset`, `package`).
- [`webmonitor/cli.py`](webmonitor/cli.py): Synchronous offline commands (`validate`, `package [--include-secrets]`, `history`, `reset`, `app-url`) and async live commands (`run`, `once`, `inspect`, `preview`, `health`, `diagnose`).
- [`webmonitor/config.py`](webmonitor/config.py): Configuration parser and validator (`monitor-config.json`), header CRLF validation, CSS/regex validation, and `REPORT_STYLES` (`inline`, `before_after`, `side_by_side`).
- [`webmonitor/netguard.py`](webmonitor/netguard.py): SSRF & DNS-rebinding guard (`is_public_ip`, `is_public_host`, `ensure_public_url`, `ensure_public_browser_url`, `is_direct_loopback`, `GuardedResolver`).
- [`webmonitor/fetchers.py`](webmonitor/fetchers.py): 3-tier fetchers (`HttpFetcher`, `ImpersonateFetcher`, `BrowserFetcher`) with Playwright route/peer-IP SSRF guard, automatic Cloudflare Turnstile clicker (`_try_solve_turnstile`), and unified atomic cookie helpers (`import_watch_cookies`, `has_watch_cookies`, `clear_watch_cookies`).
- [`webmonitor/extract.py`](webmonitor/extract.py): HTML/RSS/JSON extraction, noise filtering, link discovery, and bot-wall detection (`detect_block`).
- [`webmonitor/analyzer.py`](webmonitor/analyzer.py): Smart URL inspection, Goethe exam API discovery (with SSRF validation), and monitoring mode recommendations.
- [`webmonitor/report.py`](webmonitor/report.py): Line-level (`diff_lines`) and word-level (`word_diff_html`) diffing, layout drift assessment (`assess_drift`), 3 report styles (`inline`, `before_after`, `side_by_side`), and standalone dark/light/split-view HTML document renderer (`render_document`).
- [`webmonitor/storage.py`](webmonitor/storage.py): Thread-safe SQLite WAL database (`pages`, `seen_items`, `watch_state`, `events` outbox, `watches`, `admins`, `settings`), bounded Persian-normalized `search_events`, and `VACUUM INTO` integrity-checked backups.
- [`webmonitor/registry.py`](webmonitor/registry.py): Live DB-backed watch registry synced with `monitor-config.json`.
- [`webmonitor/health.py`](webmonitor/health.py): Self-diagnostics (`GET /health` on `127.0.0.1` + `monitor_system.py health`).
- [`webmonitor/engine.py`](webmonitor/engine.py): Scheduling loop, smart route memory, auto-escalating subpage BFS crawler (`_crawl_fetch`), selector self-healing suggestions, quiet hours, and interactive challenge orchestration.
- [`webmonitor/notifier.py`](webmonitor/notifier.py): Telegram Bot API client with message chunking, retry/429 handling, and HTML document/photo uploads.
- [`webmonitor/bot.py`](webmonitor/bot.py): Telegram inline control panel (`/panel`, `/list`, `/add`, `/status`, `/check`, `/search`, `/export`), 1-tap CAPTCHA solver (`+ck`, `+cc`) with block verification, unified cookie importer, and global settings.
- [`DESIGN.md`](DESIGN.md): Authoritative UI/UX & Design System specification (4-step dark/light surface ladder, bidirectional RTL Persian + LTR technical rules, Emil Kowalski motion physics, SVG telemetry spark-bars, and WCAG AA / CSP guardrails).
- [`webmonitor/miniapp.py`](webmonitor/miniapp.py) & [`webmonitor/miniapp_ui.py`](webmonitor/miniapp_ui.py): Telegram Mini App (`/app`) REST API + accessible RTL SPA with `Ctrl+K` command palette, 7-day SVG activity pulse, Smart URL Analyzer, live selector/regex preview sandbox, standalone HTML diff export, JSON backup export/import, live access diagnostics, split-column diffs, and live CAPTCHA solver.
- [`webmonitor/challenge.py`](webmonitor/challenge.py): Localhost HTTP/MJPEG challenge server (`127.0.0.1:8899`) with CSRF, CSP, rate-limiting, live coordinate indicator, and stream concurrency caps.

## Local Verification & Testing Commands
```powershell
# Validate configuration (offline, synchronous)
python monitor_system.py validate

# Preview a site extraction
python monitor_system.py preview de_embassy_home

# Run fast unit test suite (skipping live Playwright browser launches)
$env:WEBMONITOR_SKIP_BROWSER="1"; python -m unittest discover -s tests -v

# Run full unit test suite (including live browser tests)
Remove-Item Env:WEBMONITOR_SKIP_BROWSER -ErrorAction SilentlyContinue; python -m unittest discover -s tests -v

# Interactive headless browser QA via @playwright/cli
cmd.exe /c "playwright-cli --version"

# Build clean deployment zip (redacts secrets in monitor-config.json by default; pass --include-secrets to keep live tokens)
python monitor_system.py package -o monitor-deploy.zip
```

## Production Server Deployment (`oracle-server`)
- **SSH Host Alias**: `oracle-server` (`<SERVER_IP>`, user `ubuntu`, key `~/.ssh/<your-ssh-key>`)
- **Install Directory**: `/opt/monitor` (owned by `monitorsvc:monitorsvc`)
- **Systemd Service**: `monitor-service.service`
- **One-Command Deploy**:
  ```powershell
  python monitor_system.py package -o monitor-deploy.zip
  scp monitor-deploy.zip oracle-server:~/monitor-deploy.zip
  ssh oracle-server "sudo unzip -o ~/monitor-deploy.zip -d /opt/monitor -x monitor-config.json && sudo chown -R monitorsvc:monitorsvc /opt/monitor/webmonitor /opt/monitor/monitor_system.py /opt/monitor/deploy && sudo systemctl restart monitor-service && sudo systemctl status monitor-service --no-pager"
  ```
  *(Note: `-x monitor-config.json` preserves the production server's live `monitor-config.json` if already customized).*

#!/usr/bin/env bash
# Configure Nginx reverse proxy for Telegram Mini App (/app and /api/app/) to 127.0.0.1:8899.
# Note: /c/ (interactive SSH challenge solver) intentionally stays bound to 127.0.0.1:8899 only
# and is NOT exposed on the public internet; admins solve challenges via Mini App (/api/app/challenge/*)
# or over an authenticated SSH tunnel.
set -euo pipefail

DOMAIN="${MINIAPP_DOMAIN:-your-domain.duckdns.org}"

echo "[1/3] Stopping unused caddy service if present..."
if systemctl is-active --quiet caddy 2>/dev/null; then
    sudo systemctl stop caddy || true
    sudo systemctl disable caddy || true
fi

echo "[2/3] Configuring Nginx reverse proxy for /app and /api/app/ on existing SSL vhost..."
sudo python3 - <<'PY'
import glob, pathlib, re

snippet = """
    # --- WebMonitor Telegram Mini App Proxy ---
    location = /app {
        proxy_pass http://127.0.0.1:8899/app;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_hide_header X-Frame-Options;
        add_header Content-Security-Policy "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org;" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
    }
    location ^~ /api/app/ {
        proxy_pass http://127.0.0.1:8899/api/app/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "no-referrer" always;
    }
    location ^~ /c/ {
        return 404;
    }
    # --- End WebMonitor Proxy ---
"""

candidates = glob.glob("/etc/nginx/sites-enabled/*") + glob.glob("/etc/nginx/conf.d/*.conf")
updated = False
for path_str in candidates:
    p = pathlib.Path(path_str)
    if not p.is_file():
        continue
    text = p.read_text(encoding="utf-8", errors="ignore")
    if "ssl_certificate" not in text and "443" not in text:
        continue
    # Remove old block if already injected
    text = re.sub(
        r"\n\s*# --- WebMonitor Telegram Mini App.*?# --- End WebMonitor Proxy ---\n?",
        "\n",
        text,
        flags=re.S,
    )
    # Insert right before ssl_certificate line inside the 443 server block
    idx = text.find("ssl_certificate")
    if idx != -1:
        line_start = text.rfind("\n", 0, idx)
        new_text = text[:line_start] + "\n" + snippet + text[line_start:]
        p.write_text(new_text, encoding="utf-8")
        print(f"Updated Nginx SSL config: {p}")
        updated = True
        break

if not updated:
    raise SystemExit("Could not find an Nginx SSL vhost in /etc/nginx/sites-enabled/ or /etc/nginx/conf.d/")
PY

echo "[3/3] Testing and reloading Nginx..."
sudo nginx -t
sudo systemctl reload nginx
echo "Done! Telegram Mini App is now live with valid SSL at: https://${DOMAIN}/app"

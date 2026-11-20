"""The Telegram Mini App front end (one self-contained HTML page: CSS, markup and JavaScript).

It lives apart from ``miniapp.py`` (the REST API) so that the page can be read, linted and tested on its own -
``tests/test_welle4a.py`` loads it in a real browser. All text that comes from monitored sites is escaped here;
the ready-made diff HTML (``header_html`` / ``blocks_html``) is escaped on the server (``report.py``).

Design notes (governed by DESIGN.md)
* Phone first (Telegram opens it at ~390 px), light and dark: the colours follow Telegram's theme variables,
  and the semantic colours (green / red / amber) have a darker set for the light theme so that they stay readable.
* Every clickable thing is a real <button> or <a>: it can be reached and used with the keyboard and a screen reader.
* Transitions are explicit and compositor-friendly; hover states only fire on fine pointers; numbers use tabular-nums.
* Includes a 0ms Ctrl+K command palette, 7-day SVG activity pulse, live selector preview sandbox, HTML diff export,
  and portable JSON watch backup export/import.
"""

MINIAPP_HTML = r"""<!doctype html>
<html lang="fa" dir="rtl" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" id="meta-theme-color" content="#0b0f17">
<title>داشبورد هوشمند مانیتور</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root {
  color-scheme: dark;
  --bg: var(--tg-theme-secondary-bg-color, #0b0f17);
  --card: var(--tg-theme-bg-color, #151c28);
  --surface-2: color-mix(in srgb, var(--card) 82%, #ffffff 6%);
  --surface-3: color-mix(in srgb, var(--card) 72%, #ffffff 12%);
  --border: rgba(148, 163, 184, 0.2);
  --border-strong: rgba(148, 163, 184, 0.34);
  --text: var(--tg-theme-text-color, #f1f5f9);
  --muted: var(--tg-theme-hint-color, #9aa8bd);
  --primary: var(--tg-theme-button-color, #2563eb);
  --primary-fg: var(--tg-theme-button-text-color, #ffffff);
  --radius: 14px;
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --success: #34d399; --success-bg: rgba(52, 211, 153, 0.15);
  --danger: #f87171;  --danger-bg: rgba(248, 113, 113, 0.15);
  --warn: #fbbf24;    --warn-bg: rgba(251, 191, 36, 0.15);
  --link: #7aa7ff;
}
:root.light {
  color-scheme: light;
  --bg: var(--tg-theme-secondary-bg-color, #eef1f6);
  --card: var(--tg-theme-bg-color, #ffffff);
  --surface-2: #f4f6fa;
  --surface-3: #e8edf5;
  --text: var(--tg-theme-text-color, #0f172a);
  --muted: var(--tg-theme-hint-color, #566074);
  --primary: var(--tg-theme-button-color, #1d4ed8);
  --success: #047857; --success-bg: rgba(4, 120, 87, 0.12);
  --danger: #b91c1c;  --danger-bg: rgba(185, 28, 28, 0.1);
  --warn: #92400e;    --warn-bg: rgba(180, 83, 9, 0.12);
  --link: #1d4ed8;
  --border: rgba(60, 60, 67, 0.18);
  --border-strong: rgba(60, 60, 67, 0.3);
}
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
[hidden] { display: none !important; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; padding: 0 0 calc(70px + env(safe-area-inset-bottom));
  font-family: Vazirmatn, system-ui, -apple-system, 'Segoe UI', Tahoma, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6; font-size: 14px;
}
button, input, select, textarea { font-family: inherit; }
button, a, summary, input, select { touch-action: manipulation; }
select option { background: var(--card); color: var(--text); }
:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; border-radius: 6px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.skip-link {
  position: fixed; top: -120px; inset-inline-start: 12px; z-index: 200;
  padding: 8px 14px; min-height: 40px; border-radius: 10px;
  background: var(--primary); color: var(--primary-fg); font-weight: 700; text-decoration: none;
}
.skip-link:focus { top: 10px; }
a { color: var(--link); }
.container { max-width: 780px; margin: 0 auto; padding: 10px 12px; }

/* ---- header */
header.top {
  position: sticky; top: 0; z-index: 30; background: var(--card); border-bottom: 1px solid var(--border);
  padding: 8px 12px; padding-top: calc(8px + env(safe-area-inset-top));
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
}
.brand { display: flex; align-items: center; gap: 10px; min-width: 0; background: none; border: none; color: inherit;
  padding: 0; cursor: pointer; text-align: start; min-height: 44px; }
.brand-icon { width: 36px; height: 36px; border-radius: 10px; flex: none; color: #fff;
  background: linear-gradient(135deg, #2563eb, #1e40af); display: flex; align-items: center; justify-content: center;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.22); }
.brand-text { min-width: 0; }
.brand h1 { font-size: 16px; margin: 0; font-weight: 700; white-space: nowrap; letter-spacing: -0.01em; }
.brand small { font-size: 11px; color: var(--muted); display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
.top-actions { display: flex; gap: 6px; flex: none; }

/* ---- controls */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 14px;
  border-radius: 10px; border: 1px solid var(--border); background: var(--card); color: var(--text);
  font-size: 13px; font-weight: 600; cursor: pointer; min-height: 44px; text-decoration: none;
  transition: transform 140ms var(--ease-out), background-color 140ms var(--ease-out), border-color 140ms var(--ease-out), opacity 140ms linear;
}
.btn:active { transform: scale(0.97); }
.btn[disabled] { opacity: .6; cursor: progress; }
.btn.primary { background: var(--primary); color: var(--primary-fg); border-color: transparent; }
.btn.success { background: var(--success-bg); color: var(--success); border-color: transparent; }
.btn.danger { background: var(--danger-bg); color: var(--danger); border-color: transparent; }
.btn.sm { padding: 5px 12px; font-size: 12px; min-height: 40px; border-radius: 9px; }
.icon-btn { width: 44px; min-height: 44px; padding: 0; font-size: 18px; }
@media (hover: hover) and (pointer: fine) {
  .btn:not([disabled]):not(.primary):not(.success):not(.danger):hover { background: var(--surface-2); border-color: var(--border-strong); }
  .btn.primary:not([disabled]):hover { filter: brightness(1.07); }
  .fchip[aria-pressed="false"]:hover { background: var(--surface-2); border-color: var(--border-strong); }
  .site-card:hover { border-color: var(--border-strong); }
  .cmd-item:hover { background: var(--surface-2); }
}
.input {
  width: 100%; padding: 10px 12px; min-height: 44px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--bg); color: var(--text); font-size: 14px;
  transition: border-color 140ms var(--ease-out), background-color 140ms var(--ease-out);
}
.input:focus { border-color: var(--primary); }
textarea.input { min-height: 0; }
label.lbl { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.badge {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px; border-radius: 999px;
  font-size: 11.5px; font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums;
}
.badge.ok { background: var(--success-bg); color: var(--success); }
.badge.error, .badge.broken { background: var(--danger-bg); color: var(--danger); }
.badge.paused, .badge.pending, .badge.warn { background: var(--warn-bg); color: var(--warn); }
.badge.neutral { background: rgba(148, 163, 184, 0.16); color: var(--muted); }
.badge.info { background: color-mix(in srgb, var(--primary) 16%, transparent); color: var(--link); }

/* ---- health strip & 7-day telemetry spark-bars */
.health { width: 100%; text-align: start; display: flex; align-items: center; gap: 10px; padding: 10px 12px; min-height: 48px;
  border-radius: var(--radius); border: 1px solid var(--border); background: var(--card); color: var(--text); cursor: pointer; margin-bottom: 10px;
  transition: border-color 140ms var(--ease-out), background-color 140ms var(--ease-out); }
.health .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; background: var(--success); }
.health.warn .dot { background: var(--warn); } .health.error .dot { background: var(--danger); }
.health .txt { flex: 1; min-width: 0; font-weight: 600; font-size: 13px; }
.health .txt small { display: block; font-weight: 400; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.health .chev { color: var(--muted); transition: transform 160ms var(--ease-out); } .health[aria-expanded="true"] .chev { transform: rotate(180deg); }
.health-detail { border: 1px solid var(--border); background: var(--card); border-radius: var(--radius); padding: 8px 12px; margin: -4px 0 10px; }
.health-detail li { list-style: none; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.health-detail li:last-child { border-bottom: none; }
.health-detail ul { margin: 0; padding: 0; }
.link-btn { background: none; border: none; color: var(--link); padding: 0; font-size: inherit; text-decoration: underline; cursor: pointer; text-align: start; }

.spark-card { background: var(--bg); border: 1px solid var(--border); border-radius: 11px; padding: 8px 10px; margin-top: 8px; }
.spark-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; margin-bottom: 4px; }
.spark-meta { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 11.5px; }
.spark-svg { width: 100%; height: 42px; display: block; }

/* ---- filter chips & toolbar */
.chips { display: flex; gap: 6px; overflow-x: auto; padding: 2px 0 8px; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.fchip { flex: none; min-height: 40px; padding: 6px 14px; border-radius: 999px; border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap;
  transition: background-color 140ms var(--ease-out), border-color 140ms var(--ease-out), transform 140ms var(--ease-out); }
.fchip:active { transform: scale(0.97); }
.fchip[aria-pressed="true"] { background: var(--primary); color: var(--primary-fg); border-color: transparent; }
.fchip .n { opacity: .88; margin-inline-start: 4px; font-weight: 700; font-variant-numeric: tabular-nums; }
.toolbar { display: flex; gap: 6px; margin-bottom: 10px; }
.toolbar .input { flex: 1; min-width: 0; }
.toolbar .btn { padding: 8px 11px; flex: none; }

/* ---- site cards */
.site-card { display: flex; align-items: stretch; gap: 4px; background: var(--card); border: 1px solid var(--border);
  border-inline-start: 4px solid var(--border); border-radius: var(--radius); margin-bottom: 8px;
  transition: border-color 140ms var(--ease-out); }
.site-card.st-ok { border-inline-start-color: var(--success); }
.site-card.st-error { border-inline-start-color: var(--danger); }
.site-card.st-warn, .site-card.st-paused { border-inline-start-color: var(--warn); }
.card-open { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; text-align: start; padding: 11px 12px;
  background: none; border: none; color: inherit; cursor: pointer; border-radius: var(--radius); min-height: 44px; }
.card-title { font-size: 15px; font-weight: 700; line-height: 1.45; overflow-wrap: anywhere; }
.card-badges { display: flex; flex-wrap: wrap; gap: 5px; }
.card-host { font-size: 12px; color: var(--muted); direction: ltr; text-align: start; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-times { font-size: 12px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 0 12px; font-variant-numeric: tabular-nums; }
.card-times span { white-space: nowrap; }
.card-note { font-size: 12.5px; }
.card-note.err { color: var(--danger); } .card-note.warn { color: var(--warn); }
.card-side { display: flex; align-items: center; padding-inline-end: 6px; }
.skeleton { height: 92px; border-radius: var(--radius); margin-bottom: 8px; border: 1px solid var(--border);
  background: linear-gradient(90deg, var(--card), color-mix(in srgb, var(--card) 85%, var(--muted)), var(--card)); background-size: 200% 100%;
  animation: shimmer 1.3s linear infinite; }
@keyframes shimmer { from { background-position: 100% 0; } to { background-position: -100% 0; } }
@media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } * { transition: none !important; } }

/* ---- boxes, tabs, settings */
.panel-box { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; margin-bottom: 10px; }
.panel-box h2, .panel-box h3, .panel-box h4 { margin: 0 0 8px; }
.notice { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px 12px;
  border-radius: 12px; border: 1px solid transparent; margin-bottom: 10px; font-size: 13px; }
.notice.warn { background: var(--warn-bg); border-color: var(--warn); } .notice.info { background: color-mix(in srgb, var(--primary) 12%, transparent); border-color: var(--primary); }
.notice.err { background: var(--danger-bg); border-color: var(--danger); }
.notice .grow { flex: 1; min-width: 180px; } .notice small { display: block; color: var(--muted); font-size: 12px; }
.meta-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tabs { display: flex; gap: 4px; margin: 10px 0; padding: 4px; border-radius: 12px; background: var(--card); border: 1px solid var(--border); }
.tab { flex: 1; min-width: 0; padding: 8px 4px; min-height: 44px; border-radius: 9px; border: none; background: transparent; color: var(--muted);
  font-size: 12.5px; font-weight: 600; cursor: pointer; line-height: 1.3;
  transition: background-color 140ms var(--ease-out), color 140ms var(--ease-out); }
.tab[aria-selected="true"] { background: var(--primary); color: var(--primary-fg); }
.facts { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.fact { background: var(--bg); border-radius: 10px; padding: 8px 10px; border: 1px solid var(--border); }
.fact span { display: block; font-size: 11.5px; color: var(--muted); } .fact b { font-size: 13px; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.group-title { font-size: 12px; font-weight: 700; color: var(--muted); margin: 14px 2px 6px; letter-spacing: .02em; }
.setting-row { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); }
.setting-row:last-child { border-bottom: none; }
.setting-info { flex: 1; min-width: 0; } .setting-info b { display: block; font-size: 14px; } .setting-info small { color: var(--muted); font-size: 12px; display: block; }
.setting-row.stack { flex-direction: column; align-items: stretch; gap: 8px; }
.row-inline { display: flex; gap: 8px; align-items: center; }
.switch { position: relative; width: 52px; min-width: 52px; height: 32px; background: rgba(148, 163, 184, 0.45); border-radius: 99px; cursor: pointer;
  transition: background-color 160ms var(--ease-out); flex: none; border: none; padding: 0; }
.switch::after { content: ""; position: absolute; top: 4px; right: 4px; width: 24px; height: 24px; background: #fff; border-radius: 50%;
  transition: transform 160ms var(--ease-out); }
.switch.on { background: #059669; } .switch.on::after { transform: translateX(-20px); }
.diff-block { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; margin-top: 8px; white-space: pre-wrap;
  unicode-bidi: plaintext; overflow-wrap: anywhere; font-size: 13px; line-height: 1.85; }
.diff-block blockquote { margin: 6px 0; padding: 6px 10px; border-inline-start: 3px solid var(--primary); background: rgba(59,130,246,0.07); border-radius: 6px; }
.diff-block s { color: var(--danger); background: var(--danger-bg); padding: 0 3px; border-radius: 4px; }
.diff-block b u { color: var(--success); background: var(--success-bg); text-decoration: none; padding: 0 3px; border-radius: 4px; }
.diff-block a { color: var(--link); }
.sbs-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 6px 0; white-space: pre-wrap; }
@media (max-width: 560px) { .sbs-grid { grid-template-columns: 1fr; } }
.sbs-cell { padding: 7px 9px; border-radius: 8px; border: 1px solid var(--border); font-size: 12.5px; }
.sbs-old { background: var(--danger-bg); color: var(--danger); }
.sbs-new { background: var(--success-bg); color: var(--success); }
details.event { background: var(--card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 8px; }
details.event > summary { list-style: none; cursor: pointer; padding: 10px 12px; min-height: 44px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
details.event > summary::-webkit-details-marker { display: none; }
details.event > summary .when { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
details.event > summary .sum { flex-basis: 100%; font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
details.event[open] > summary { border-bottom: 1px solid var(--border); }
details.event .body { padding: 0 12px 12px; }
.ev-foot { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px; }

/* ---- smart analyzer choice cards & challenge ripple */
.choice-list { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
.choice-btn { width: 100%; text-align: start; padding: 10px 12px; min-height: 48px; border-radius: 11px; border: 1px solid var(--border);
  background: var(--bg); color: var(--text); cursor: pointer; display: flex; flex-direction: column; gap: 2px;
  transition: border-color 140ms var(--ease-out), background-color 140ms var(--ease-out); }
.choice-btn.active { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 13%, var(--bg)); }
.choice-btn b { font-size: 13.5px; }
.choice-btn small { font-size: 12px; color: var(--muted); }
.preview-box { background: var(--bg); border: 1px dashed var(--border); border-radius: 10px; padding: 8px 10px; font-size: 12px;
  max-height: 180px; overflow-y: auto; white-space: pre-wrap; unicode-bidi: plaintext; color: var(--muted); margin-top: 6px; }
.ch-ripple { position: absolute; width: 24px; height: 24px; border: 2.5px solid #38bdf8; border-radius: 50%;
  transform: translate(-50%, -50%); pointer-events: none; display: none; box-shadow: 0 0 0 4px rgba(56,189,248,.25); }

/* ---- instant command palette (0ms transition per Emil Kowalski frequency rule) */
#modal-cmd { align-items: flex-start; padding-top: max(12px, 7vh); transition: none !important; }
#modal-cmd .modal { border-radius: 16px; max-width: 520px; padding: 12px; transition: none !important; }
.cmd-list { display: flex; flex-direction: column; gap: 4px; max-height: 58vh; overflow-y: auto; margin-top: 8px; }
.cmd-item {
  width: 100%; min-height: 44px; padding: 8px 10px; border-radius: 10px; border: 1px solid transparent;
  background: transparent; color: var(--text); cursor: pointer; text-align: start;
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
}
.cmd-item.active { background: color-mix(in srgb, var(--primary) 15%, var(--card)); border-color: var(--primary); }
.cmd-item small { color: var(--muted); font-size: 11.5px; direction: ltr; }

.toast { position: fixed; bottom: calc(18px + env(safe-area-inset-bottom)); left: 50%; transform: translateX(-50%); max-width: 92vw; background: #1e293b; color: #fff;
  padding: 10px 18px; border-radius: 14px; font-size: 13px; font-weight: 600; box-shadow: 0 8px 24px rgba(0,0,0,.4); z-index: 100; display: none; text-align: center; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 60; display: none; align-items: flex-end; justify-content: center; }
.modal { background: var(--card); border: 1px solid var(--border); border-radius: 18px 18px 0 0; max-width: 560px; width: 100%; max-height: 92vh; overflow-y: auto;
  overscroll-behavior: contain; padding: 18px 16px calc(18px + env(safe-area-inset-bottom)); }
@media (min-width: 600px) { .modal-backdrop { align-items: center; padding: 14px; } .modal { border-radius: 16px; } }
.modal h2 { font-size: 17px; margin: 0 0 12px; }
.chipx { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 99px; background: color-mix(in srgb, var(--primary) 15%, transparent); color: var(--link); font-size: 12px; }
img.live-shot { width: 100%; border-radius: 10px; border: 1px solid var(--border); margin-top: 8px; }
.empty { text-align: center; color: var(--muted); padding: 26px 12px; }
.empty .big { font-size: 34px; display: block; margin-bottom: 6px; }

/* ---- view switch, bulk mode, persona profiles ---- */
.view-switch { display: flex; gap: 4px; background: color-mix(in srgb, var(--card) 60%, var(--bg)); padding: 4px; border-radius: 12px; margin-bottom: 10px; border: 1px solid var(--border); }
.vtab { flex: 1; min-height: 40px; border: none; background: transparent; color: var(--muted); border-radius: 9px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 120ms var(--ease-out); display: flex; align-items: center; justify-content: center; gap: 6px; }
.vtab.active { background: var(--card); color: var(--text); box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.bulk-bar { position: sticky; bottom: calc(12px + env(safe-area-inset-bottom)); z-index: 40; background: var(--card); border: 1px solid var(--primary); border-radius: 14px; padding: 10px 14px; box-shadow: 0 8px 24px rgba(0,0,0,0.25); display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.site-check { width: 34px; height: 34px; border-radius: 8px; border: 1.5px solid var(--border); background: var(--bg); color: #fff; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-inline-end: 8px; align-self: center; transition: all 120ms; }
.site-check.checked { background: var(--primary); border-color: var(--primary); }
.site-card.selected { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 8%, var(--card)); }
.profile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; margin: 8px 0; }
.profile-btn { padding: 10px 12px; border-radius: 12px; border: 1px solid var(--border); background: var(--bg); color: var(--text); cursor: pointer; text-align: start; display: flex; flex-direction: column; gap: 3px; min-height: 52px; transition: all 120ms; }
.profile-btn:hover, .profile-btn.active { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 12%, var(--card)); }
.profile-btn b { font-size: 12.5px; display: flex; align-items: center; gap: 4px; }
.profile-btn small { font-size: 11px; color: var(--muted); line-height: 1.35; }
</style>
</head>
<body>
<a class="skip-link" href="#main">پرش به محتوای اصلی</a>
<header class="top">
  <button class="brand" onclick="showHome()" aria-label="بازگشت به صفحهٔ اصلی">
    <span class="brand-icon" aria-hidden="true">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="9"></circle>
        <circle cx="12" cy="12" r="4"></circle>
        <path d="M12 3v3M21 12h-3M12 12l5.2-5.2"></path>
      </svg>
    </span>
    <span class="brand-text">
      <h1 id="nav-title">مانیتور سایت‌ها</h1>
      <small id="nav-sub">در حال اتصال…</small>
    </span>
  </button>
  <div class="top-actions">
    <button class="btn icon-btn" onclick="openSettingsModal()" aria-label="تنظیمات کلی" title="تنظیمات کلی">⚙️</button>
    <button class="btn primary" onclick="openAddModal()" aria-label="افزودن سایت جدید">➕ سایت</button>
  </div>
</header>

<main class="container" id="main">
  <!-- HOME -->
  <div id="view-home">
    <div id="challenge-banner"></div>
    <button class="health" id="health-strip" aria-expanded="false" aria-controls="health-detail" onclick="toggleHealth()" hidden>
      <span class="dot" aria-hidden="true"></span>
      <span class="txt" id="health-text"></span>
      <span class="chev" aria-hidden="true">▾</span>
    </button>
    <div class="health-detail" id="health-detail" hidden></div>

    <div class="view-switch" role="tablist" aria-label="انتخاب نمای اصلی داشبورد">
      <button class="vtab active" role="tab" id="view-tab-sites" aria-selected="true" onclick="setHomeView('sites')">📋 لیست سایت‌ها</button>
      <button class="vtab" role="tab" id="view-tab-events" aria-selected="false" onclick="setHomeView('events')">⚡ جریان رویدادها</button>
      <button class="vtab" type="button" id="btn-bulk-mode" onclick="toggleBulkMode()">☑️ انتخاب گروهی</button>
    </div>

    <div class="chips" id="filter-chips" role="group" aria-label="فیلتر سایت‌ها"></div>
    <div class="toolbar">
      <input class="input" id="site-q" type="search" aria-label="جستجوی نام یا آدرس سایت" placeholder="🔍 نام سایت یا آدرس… (کلید /)" oninput="onSearchInput()">
      <button class="btn" type="button" onclick="openCmdModal()" title="فرمان سریع و پرش به سایت (Ctrl+K)" aria-label="فرمان سریع و پرش به سایت">⌘</button>
      <button class="btn" type="button" onclick="runHistorySearch()" title="جستجو در تاریخچهٔ تغییرات" aria-label="جستجو در تاریخچهٔ تغییرات">🕘</button>
      <button class="btn" type="button" onclick="checkAllSites()" title="بررسی فوری همهٔ سایت‌ها" aria-label="بررسی فوری همهٔ سایت‌ها">🔄</button>
    </div>
    <div id="search-results" aria-live="polite"></div>
    <div id="sites-list" role="list"></div>
    <div id="events-feed-panel" hidden>
      <div class="chips" id="events-filter-chips" style="margin-bottom:8px">
        <button class="fchip active-chip" id="ef-all" aria-pressed="true" onclick="loadEventsFeed('all')">همه رویدادها</button>
        <button class="fchip" id="ef-changes" aria-pressed="false" onclick="loadEventsFeed('changes')">🔔 فقط تغییرات</button>
        <button class="fchip" id="ef-errors" aria-pressed="false" onclick="loadEventsFeed('errors')">⚠️ فقط خطاها</button>
      </div>
      <div id="events-feed-list"></div>
    </div>
    <div id="bulk-bar" class="bulk-bar" hidden>
      <div style="display:flex;align-items:center;gap:8px">
        <b id="bulk-count">۰ سایت انتخاب شد</b>
        <button class="btn sm" type="button" onclick="selectAllSites(true)">انتخاب همه</button>
        <button class="btn sm" type="button" onclick="selectAllSites(false)">لغو انتخاب</button>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn sm primary" type="button" onclick="runBulkAction('check')">🔄 بررسی</button>
        <button class="btn sm" type="button" onclick="runBulkAction('pause')">⏸ توقف</button>
        <button class="btn sm" type="button" onclick="runBulkAction('resume')">▶️ ادامه</button>
        <button class="btn sm" type="button" onclick="runBulkAction('silent_on')">🔕 بی‌صدا</button>
        <button class="btn sm" type="button" onclick="runBulkAction('silent_off')">🔔 صدادار</button>
        <button class="btn sm danger" type="button" onclick="runBulkAction('delete')">🗑 حذف</button>
      </div>
    </div>
  </div>

  <!-- ONE SITE -->
  <div id="view-site" hidden>
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px">
      <button class="btn sm" onclick="showHome()">➡️ همهٔ سایت‌ها</button>
      <div id="site-top-badges"></div>
    </div>
    <div class="panel-box" id="site-header-card"></div>
    <div class="tabs" role="tablist" aria-label="بخش‌های سایت" id="site-tabs">
      <button class="tab" role="tab" id="tab-btn-overview" aria-controls="site-tab-overview" aria-selected="true" onclick="switchSiteTab('overview')">📊<br>وضعیت</button>
      <button class="tab" role="tab" id="tab-btn-diffs" aria-controls="site-tab-diffs" aria-selected="false" tabindex="-1" onclick="switchSiteTab('diffs')">🕘<br>تاریخچه</button>
      <button class="tab" role="tab" id="tab-btn-settings" aria-controls="site-tab-settings" aria-selected="false" tabindex="-1" onclick="switchSiteTab('settings')">⚙️<br>تنظیمات</button>
      <button class="tab" role="tab" id="tab-btn-subpages" aria-controls="site-tab-subpages" aria-selected="false" tabindex="-1" onclick="switchSiteTab('subpages')">📂<br>صفحات و کوکی</button>
    </div>
    <div id="site-tab-overview" role="tabpanel" aria-labelledby="tab-btn-overview"></div>
    <div id="site-tab-diffs" role="tabpanel" aria-labelledby="tab-btn-diffs" hidden></div>
    <div id="site-tab-settings" role="tabpanel" aria-labelledby="tab-btn-settings" hidden></div>
    <div id="site-tab-subpages" role="tabpanel" aria-labelledby="tab-btn-subpages" hidden></div>
  </div>
</main>

<!-- ADD SITE -->
<div class="modal-backdrop" id="modal-add" role="dialog" aria-modal="true" aria-labelledby="add-title" aria-hidden="true">
  <div class="modal">
    <h2 id="add-title">➕ افزودن سایت جدید</h2>
    <div style="display:flex;flex-direction:column;gap:12px">
      <div id="add-profiles-box"></div>
      <div><label class="lbl" for="add-url">🔗 آدرس صفحه یا @کانال تلگرام</label>
        <div class="row-inline">
          <input class="input" id="add-url" dir="ltr" inputmode="url" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="https://teheran.diplo.de/ir-fa" oninput="onAddUrlEdit()" style="flex:1">
          <button class="btn sm" type="button" id="btn-analyze" onclick="runSmartAnalyze()">🔎 بررسی هوشمند</button>
        </div>
      </div>
      <div id="add-analysis-box" hidden></div>
      <div><label class="lbl" for="add-name">📝 نام دلخواه</label>
        <input class="input" id="add-name" placeholder="مثلاً: سفارت آلمان — بخش ویزا"></div>
      <div><label class="lbl" for="add-type">🧭 نوع پایش</label>
        <select class="input" id="add-type">
          <option value="page">📄 کل صفحه یا بخش انتخابی (کلمه‌به‌کلمه)</option>
          <option value="headlines">📰 تیترهای خبری جدید</option>
          <option value="items">📌 فهرست آیتم‌ها / کانال تلگرام</option>
          <option value="feed">📡 خبرخوان RSS/Atom</option>
          <option value="json">🎓 ظرفیت آزمون / دادهٔ API</option>
        </select></div>
      <div><label class="lbl" for="add-interval">⏱ فاصلهٔ بررسی</label>
        <select class="input" id="add-interval">
          <option value="60">هر ۱ دقیقه</option><option value="120">هر ۲ دقیقه</option><option value="180">هر ۳ دقیقه</option>
          <option value="300">هر ۵ دقیقه</option><option value="900" selected>هر ۱۵ دقیقه</option><option value="1800">هر ۳۰ دقیقه</option>
          <option value="3600">هر ۱ ساعت</option><option value="7200">هر ۲ ساعت</option><option value="10800">هر ۳ ساعت</option>
          <option value="21600">هر ۶ ساعت</option><option value="43200">هر ۱۲ ساعت</option><option value="86400">هر ۲۴ ساعت</option>
        </select></div>
      <div><label class="lbl" for="add-keywords">🔑 کلمات کلیدی مهم (با ویرگول جدا کنید)</label>
        <input class="input" id="add-keywords" placeholder="نوبت, ویزا, Termin, appointment"></div>
      <div class="setting-row" style="padding:0">
        <div class="setting-info"><b id="add-crawl-lbl">🕷 خزش خودکار زیرصفحه‌ها</b><small>پایش لینک‌ها و زیرصفحه‌های داخلی این بخش</small></div>
        <button class="switch on" id="add-crawl" role="switch" aria-checked="true" aria-labelledby="add-crawl-lbl" onclick="toggleSwitch(this)"></button>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn" type="button" onclick="closeModals()">انصراف</button>
        <button class="btn primary" id="btn-submit-add" type="button" onclick="submitAddSite()">✅ ذخیره و شروع پایش</button>
      </div>
    </div>
  </div>
</div>

<!-- GLOBAL SETTINGS -->
<div class="modal-backdrop" id="modal-settings" role="dialog" aria-modal="true" aria-labelledby="gs-title" aria-hidden="true">
  <div class="modal">
    <h2 id="gs-title">⚙️ تنظیمات کلی</h2>
    <div id="global-settings-body"></div>
    <div style="display:flex;justify-content:flex-end;margin-top:14px"><button class="btn primary" onclick="closeModals()">بستن</button></div>
  </div>
</div>

<!-- COMMAND PALETTE -->
<div class="modal-backdrop" id="modal-cmd" role="dialog" aria-modal="true" aria-labelledby="cmd-title" aria-hidden="true">
  <div class="modal">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px">
      <h2 id="cmd-title" style="margin:0;font-size:15px">⌘ فرمان سریع و پرش به سایت</h2>
      <button class="btn sm" type="button" onclick="closeModals()">بستن</button>
    </div>
    <input class="input" id="cmd-q" type="search" autocomplete="off" aria-label="جستجوی فرمان یا سایت" placeholder="نام سایت، آدرس یا عملیات…" oninput="renderCmdList()" onkeydown="onCmdKeydown(event)">
    <div class="cmd-list" id="cmd-list" role="listbox" aria-label="نتایج فرمان سریع"></div>
  </div>
</div>

<!-- LIVE CAPTCHA -->
<div class="modal-backdrop" id="modal-challenge" role="dialog" aria-modal="true" aria-labelledby="ch-title" aria-hidden="true">
  <div class="modal" style="max-width:680px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap">
      <h2 id="ch-title" style="margin:0">🛡 حل زندهٔ کپچا</h2>
      <div style="display:flex;gap:6px;align-items:center">
        <span class="badge neutral" id="ch-coords" dir="ltr">1280×900</span>
        <span class="badge neutral" id="ch-timer" role="timer">--:--</span>
      </div>
    </div>
    <p style="font-size:12px;color:var(--muted);margin:0 0 8px">روی مربع تیک کپچا یا دکمهٔ داخل تصویر لمس کنید تا کلیک شما مستقیماً در مرورگر سرور اعمال شود:</p>
    <div style="position:relative;background:#000;border-radius:10px;overflow:hidden;border:1px solid var(--border)">
      <img id="ch-img" style="width:100%;display:block;cursor:crosshair" alt="صفحهٔ چالش" onmousemove="onChallengeImageMove(event)" onclick="onChallengeImageClick(event)">
      <span id="ch-ripple" class="ch-ripple" aria-hidden="true"></span>
    </div>
    <div class="row-inline" style="margin-top:8px">
      <input class="input" id="ch-text" placeholder="تایپ متن در صفحهٔ کپچا (اختیاری)…" style="flex:1">
      <button class="btn sm" type="button" onclick="sendChallengeText()">⌨️ ارسال متن</button>
      <button class="btn sm" type="button" onclick="sendChallengeKey('Tab')" aria-label="ارسال کلید Tab">⇥</button>
      <button class="btn sm" type="button" onclick="sendChallengeKey('Enter')" aria-label="ارسال کلید Enter">⏎</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;justify-content:space-between">
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn sm" onclick="refreshChallengeFrame()">🔄 تصویر جدید</button>
        <button class="btn sm" onclick="clickTurnstileCenter()">🎯 کلیک روی مربع کپچا</button>
        <button class="btn sm" type="button" onclick="sendChallengeKey('PageDown')" aria-label="اسکرول به پایین">⬇ پایین</button>
        <button class="btn sm" type="button" onclick="sendChallengeKey('PageUp')" aria-label="اسکرول به بالا">⬆ بالا</button>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn sm danger" onclick="finishChallenge('cancel')">❌ لغو</button>
        <button class="btn sm success" onclick="finishChallenge('done')">✅ حل شد</button>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast" role="status" aria-live="polite"></div>

<script>
const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (tg) {
  tg.ready();
  tg.expand();
  if (tg.BackButton) tg.BackButton.onClick(() => showHome());
  if (tg.onEvent) tg.onEvent("themeChanged", () => applyTheme());
}

// ---- theme: Telegram's own scheme first, then its colour variables, then the system setting
function applyTheme() {
  let light = null;
  const pref = localStorage.getItem("wm_theme_preference");
  if (pref === "dark") light = false;
  else if (pref === "light") light = true;
  if (light === null && tg && tg.colorScheme) light = tg.colorScheme === "light";
  if (light === null) {
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--tg-theme-bg-color").trim();
    const m = /^#([0-9a-f]{6})$/i.exec(bg);
    if (m) {
      const n = parseInt(m[1], 16);
      light = (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) > 150;
    }
  }
  if (light === null) light = !!(window.matchMedia && matchMedia("(prefers-color-scheme: light)").matches);
  document.documentElement.classList.toggle("light", light);
  document.documentElement.classList.toggle("dark", !light);
  const metaTheme = document.getElementById("meta-theme-color");
  if (metaTheme) metaTheme.setAttribute("content", light ? "#eef1f6" : "#0b0f17");
}
applyTheme();

function svgIcon(name, size = 16) {
  const icons = {
    check: '<path d="M20 6 9 17l-5-5"/>',
    refresh: '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
    settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
    clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  };
  const body = icons[name] || '';
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;display:inline-block">${body}</svg>`;
}

const FALLBACK_PROFILES = [
  {id: "embassy", icon: "landmark", label: "نوبت سفارت و ویزا", desc: "هشدار و بیدارباش فوری + خزش صفحات نوبت",
   type_hint: "page", defaults: {interval_seconds: 120, alarm: true, crawl_enabled: true, report_style: "before_after", keywords: ["نوبت", "ویزا", "Termin", "appointment"]}},
  {id: "exam", icon: "graduation", label: "ظرفیت آزمون (گوته و آیلتس)", desc: "پایش برخط و سریع ظرفیت‌ها",
   type_hint: "json", defaults: {interval_seconds: 60, alarm: true, crawl_enabled: false, keywords: ["جای خالی", "buchbar", "verfügbar"]}},
  {id: "official", icon: "building", label: "اطلاعیهٔ دانشگاه و سازمان", desc: "فهرست اطلاعیه‌ها با خزش زیرصفحه‌ها",
   type_hint: "page", defaults: {interval_seconds: 900, crawl_enabled: true, report_style: "inline"}},
  {id: "news", icon: "newspaper", label: "اخبار و رسانه", desc: "فقط تیترهای تازه به‌صورت بی‌صدا",
   type_hint: "headlines", defaults: {interval_seconds: 300, silent: true, crawl_enabled: false}},
  {id: "telegram", icon: "send", label: "کانال عمومی تلگرام", desc: "پست‌های تازه و اطلاعیه‌ها",
   type_hint: "items", defaults: {interval_seconds: 180, crawl_enabled: false}},
  {id: "price_api", icon: "chart", label: "قیمت، موجودی و API", desc: "مقایسهٔ دوطرفه همراه عکس صفحه",
   type_hint: "page", defaults: {interval_seconds: 600, crawl_enabled: false, report_style: "side_by_side", notify_mode: "both"}}
];
const allProfiles = FALLBACK_PROFILES;
const PROFILE_EMOJIS = {landmark: "🏛", graduation: "🎓", building: "🏢", newspaper: "📰", send: "✈️", chart: "📈"};

let homeView = "sites"; // 'sites' | 'events'
let bulkMode = false;
const selectedSiteKeys = new Set();
let eventsFeed = [];
let eventsFeedKind = "all";
let activeProfileId = null;

const params = new URLSearchParams(window.location.search);
// the admin token (only used outside a Telegram Web App button) arrives in the URL fragment, which is never
// sent to the server; it is read once and removed from the address bar
const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
const urlToken = hashParams.get("t") || "";
if (urlToken && window.history && history.replaceState) {
  history.replaceState(null, "", window.location.pathname + window.location.search);
}
const initialSiteKey = params.get("site") ? parseInt(params.get("site"), 10) : null;
const initialSiteTab = params.get("tab") || "overview";

let appState = null;
let appSig = "";
let curFilter = "all";
let currentSiteKey = null;
let currentSiteData = null;
let currentSiteTab = "overview";
let diffSplitMode = false;
let lastOpener = null;
let wizardData = null;
let wizardChoiceIndex = -1;
let wizardCity = "";
let challengeForceDone = false;
let cmdItems = [];
let cmdActiveIndex = 0;

const INTERVAL_PRESETS = [
  [30, "هر ۳۰ ثانیه"], [60, "هر ۱ دقیقه"], [90, "هر ۹۰ ثانیه"], [120, "هر ۲ دقیقه"], [180, "هر ۳ دقیقه"],
  [300, "هر ۵ دقیقه"], [600, "هر ۱۰ دقیقه"], [900, "هر ۱۵ دقیقه"], [1800, "هر ۳۰ دقیقه"], [3600, "هر ۱ ساعت"],
  [7200, "هر ۲ ساعت"], [10800, "هر ۳ ساعت"], [14400, "هر ۴ ساعت"], [21600, "هر ۶ ساعت"], [43200, "هر ۱۲ ساعت"], [86400, "هر ۲۴ ساعت"],
];

// ---------------------------------------------------------------- helpers
function escHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function fa(n) {
  try { return Number(n).toLocaleString("fa-IR"); } catch (_) { return String(n); }
}
function faDur(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  if (sec < 60) return fa(sec) + " ثانیه";
  if (sec < 3600) return fa(Math.round(sec / 60)) + " دقیقه";
  if (sec < 86400) return fa(Math.round(sec / 3600)) + " ساعت";
  return fa(Math.round(sec / 86400)) + " روز";
}
function hostOf(url) {
  try { return new URL(url).host; } catch (_) { return url || ""; }
}
function syncUrlState() {
  if (!window.history || !history.replaceState) return;
  const sp = new URLSearchParams();
  if (currentSiteKey) {
    sp.set("site", String(currentSiteKey));
    if (currentSiteTab && currentSiteTab !== "overview") sp.set("tab", currentSiteTab);
  }
  const q = sp.toString();
  history.replaceState(null, "", window.location.pathname + (q ? "?" + q : ""));
}
function openExternalLink(url) {
  if (!url) return;
  try {
    const abs = new URL(url, window.location.origin).href;
    if (tg && typeof tg.openLink === "function" && /^https?:\/\//i.test(abs)) {
      tg.openLink(abs);
      return;
    }
    window.open(abs, "_blank", "noopener");
  } catch (_) {
    window.open(url, "_blank", "noopener");
  }
}
document.addEventListener("click", ev => {
  const a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
  if (!a) return;
  const href = a.getAttribute("href") || "";
  if (a.target === "_blank" && /^https?:\/\//i.test(href) && tg && typeof tg.openLink === "function") {
    ev.preventDefault();
    tg.openLink(href);
  }
});
function triggerBlobDownload(filename, content, mimeType) {
  const blob = new Blob([content], {type: mimeType});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}
function renderActivitySvg(buckets, titleText) {
  if (!Array.isArray(buckets) || !buckets.length) return "";
  const totalChanges = buckets.reduce((acc, b) => acc + (b.changes || 0), 0);
  const totalErrors = buckets.reduce((acc, b) => acc + (b.errors || 0), 0);
  const peak = Math.max(1, ...buckets.map(b => (b.changes || 0) + (b.errors || 0)));
  const n = buckets.length;
  const step = 224 / n;
  const barW = Math.max(10, Math.floor(step - 8));
  const bars = buckets.map((b, idx) => {
    const ch = b.changes || 0;
    const er = b.errors || 0;
    const sum = ch + er;
    const x = Math.round(idx * step + (step - barW) / 2);
    if (!sum) {
      return `<rect x="${x}" y="37" width="${barW}" height="3" rx="1.5" fill="var(--border)"></rect>`;
    }
    const totalH = Math.max(5, Math.round((sum / peak) * 34));
    const errH = er ? Math.max(3, Math.round((er / sum) * totalH)) : 0;
    const chH = Math.max(0, totalH - errH);
    const yTop = 40 - totalH;
    let parts = "";
    if (er) parts += `<rect x="${x}" y="${yTop}" width="${barW}" height="${errH}" rx="2" fill="var(--danger)"></rect>`;
    if (chH > 0) parts += `<rect x="${x}" y="${yTop + errH}" width="${barW}" height="${chH}" rx="2" fill="var(--primary)"></rect>`;
    return parts;
  }).join("");
  const summaryLabel = `${fa(totalChanges)} تغییر` + (totalErrors ? ` · ${fa(totalErrors)} خطا` : " · بدون خطا");
  return `<div class="spark-card">
    <div class="spark-head">
      <b>📈 ${escHtml(titleText)}</b>
      <span class="spark-meta">${summaryLabel}</span>
    </div>
    <svg class="spark-svg" viewBox="0 0 224 42" preserveAspectRatio="none" role="img" aria-label="${escHtml(titleText)} — ${summaryLabel}">${bars}</svg>
  </div>`;
}
function buildIntervalOptions(currentSec, currentHuman) {
  const seen = new Set(INTERVAL_PRESETS.map(p => p[0]));
  let html = "";
  if (currentSec && !seen.has(currentSec)) {
    html += `<option value="${currentSec}" selected>هر ${escHtml(currentHuman || (currentSec + " ثانیه"))} (سفارشی)</option>`;
  }
  return html + INTERVAL_PRESETS.map(([sec, label]) =>
    `<option value="${sec}" ${currentSec === sec ? "selected" : ""}>${label}</option>`).join("");
}
function haptic(kind = "light") {
  try {
    if (tg && tg.HapticFeedback) {
      if (kind === "success" || kind === "error") tg.HapticFeedback.notificationOccurred(kind);
      else tg.HapticFeedback.impactOccurred(kind);
    }
  } catch (_) {}
}
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.style.display = "block";
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => { el.style.display = "none"; }, 3200);
}
function askConfirm(message) {
  return new Promise(resolve => {
    if (tg && tg.showConfirm) tg.showConfirm(message, ok => resolve(!!ok));
    else resolve(window.confirm(message));
  });
}
function toggleSwitch(btn) {
  btn.classList.toggle("on");
  btn.setAttribute("aria-checked", btn.classList.contains("on") ? "true" : "false");
}
// a labelled on/off row; `onclick` is the JavaScript to run when it is switched
function switchRow(id, title, desc, on, onclick) {
  return `<div class="setting-row">
    <div class="setting-info"><b id="${id}-l">${title}</b><small>${desc}</small></div>
    <button class="switch ${on ? "on" : ""}" role="switch" aria-checked="${on ? "true" : "false"}" aria-labelledby="${id}-l" onclick="${onclick}"></button>
  </div>`;
}
function formatDiffHtml(html) {
  if (!diffSplitMode || !html) return html;
  return html.replace(
    /🟡[^\n]*\n\s*(?:⫷|🔴)[^:]*:\s*(?:<\/[bi]>\s*)?<s>([\s\S]*?)<\/s>\n\s*(?:⫸|🟢)[^:]*:\s*(?:<\/[bi]>\s*)?<b><u>([\s\S]*?)<\/u><\/b>/g,
    '<div class="sbs-grid"><div class="sbs-cell sbs-old"><b>⫷ قبل:</b><br>$1</div><div class="sbs-cell sbs-new"><b>⫸ بعد:</b><br>$2</div></div>'
  );
}
async function api(path, opts = {}) {
  const headers = Object.assign({"Content-Type": "application/json"}, opts.headers || {});
  if (tg && tg.initData) headers["X-Telegram-Init-Data"] = tg.initData;
  if (urlToken) headers["X-Admin-Token"] = urlToken;
  const res = await fetch(path, Object.assign({}, opts, {headers}));
  const data = await res.json().catch(() => ({ok: false, error: "خطای ارتباط با سرور"}));
  if (!res.ok || !data.ok) {
    const err = new Error(data.error || `HTTP ${res.status}`);
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

// ---------------------------------------------------------------- loading
let pollFailures = 0;
async function loadState(silent = false) {
  try {
    const fresh = await api("/api/app/state");
    pollFailures = 0;
    const sig = JSON.stringify(Object.assign({}, fresh, {uptime_human: ""}));
    const changed = sig !== appSig;
    appSig = sig;
    appState = fresh;
    document.getElementById("nav-sub").textContent = `روشن از ${appState.uptime_human} پیش · ${fa(appState.sites.length)} سایت`;
    if (changed || !silent) renderHome();
    if (initialSiteKey && !currentSiteKey && !window._initialOpened) {
      window._initialOpened = true;
      if (TAB_IDS.includes(initialSiteTab)) currentSiteTab = initialSiteTab;
      openSite(initialSiteKey, TAB_IDS.includes(initialSiteTab));
    }
  } catch (err) {
    pollFailures += 1;
    if (!silent) toast("❌ " + err.message);
    document.getElementById("nav-sub").textContent = pollFailures >= 2
      ? "⚠️ اتصال قطع شده — نمایش آخرین دادهٔ ذخیره‌شده"
      : "ارتباط برقرار نشد";
    if (!appState) {
      document.getElementById("sites-list").innerHTML = `<div class="notice err"><div class="grow"><b>اتصال به مانیتور برقرار نشد</b><small>${escHtml(err.message)}</small></div>
        <button class="btn sm" onclick="loadState()">🔄 تلاش دوباره</button></div>`;
    }
  }
}

// ---------------------------------------------------------------- home
function siteRank(s) {
  const challenge = (appState.challenges || []).some(c => c.watch_id === s.id);
  if (s.status === "error" || s.status === "broken" || challenge) return 0;
  if (s.suggestion) return 1;
  if (s.drift) return 2;
  if (s.status === "pending") return 3;
  if (s.changes_24h) return 4;
  if (s.status === "ok") return 5;
  return 6;
}
function matchesFilter(s) {
  const r = siteRank(s);
  if (curFilter === "error") return r === 0 || r === 1;
  if (curFilter === "changed") return s.changes_24h > 0 || !!s.drift;
  if (curFilter === "ok") return s.status === "ok";
  if (curFilter === "paused") return s.status === "paused";
  return true;
}
function setFilter(f) {
  haptic("light");
  curFilter = f;
  renderHome();
}
function renderFilters(sites) {
  const count = fn => sites.filter(fn).length;
  const items = [
    ["all", "همه", sites.length],
    ["error", "⚠️ نیاز به توجه", count(s => { const r = siteRank(s); return r === 0 || r === 1; })],
    ["changed", "🔔 تغییر ۲۴ساعت", count(s => s.changes_24h > 0 || !!s.drift)],
    ["ok", "🟢 سالم", count(s => s.status === "ok")],
    ["paused", "⏸ متوقف", count(s => s.status === "paused")],
  ];
  document.getElementById("filter-chips").innerHTML = items
    .filter(([key, , n]) => key === "all" || n > 0 || curFilter === key)
    .map(([key, label, n]) => `<button class="fchip" aria-pressed="${curFilter === key}" onclick="setFilter('${key}')">${label}<span class="n">${fa(n)}</span></button>`)
    .join("");
}

function healthItems(h) {
  const label = id => { const s = (appState.sites || []).find(x => x.id === id); return s ? s.label : id; };
  const open = id => { const s = (appState.sites || []).find(x => x.id === id); return s ? `openSite(${s.key})` : ""; };
  const items = [];
  const link = (id, text) => open(id) ? `<button class="link-btn" onclick="${open(id)}">${escHtml(text)}</button>` : escHtml(text);
  if (h.db && h.db.integrity && !["ok", "unchecked"].includes(h.db.integrity)) items.push(["error", "🛑 دیتابیس سالم نیست؛ از نسخهٔ پشتیبان استفاده کنید."]);
  for (const p of (h.watches && h.watches.problem_sites) || []) {
    if (p.problem === "failing") items.push(["warn", `⚠️ ${link(p.id, label(p.id))} — ${fa(p.errors)} خطای پیاپی${p.error ? ": " + escHtml(p.error) : ""}`]);
    else if (p.problem === "stale") items.push(["warn", `⏳ ${link(p.id, label(p.id))} — مدت‌هاست بررسی موفق نداشته`]);
    else if (p.problem === "never_checked") items.push(["warn", `⏳ ${link(p.id, label(p.id))} — هنوز بررسی موفقی نداشته`]);
  }
  if (h.outbox && h.outbox.overdue_s >= 300) items.push([h.outbox.overdue_s >= 1800 ? "error" : "warn", `📨 پیام‌ها دیر به تلگرام می‌رسند (قدیمی‌ترین: ${faDur(h.outbox.overdue_s)} در صف)`]);
  for (const [name, t] of Object.entries(h.tasks || {})) {
    if (!t.running) items.push(["error", `🧩 بخش «${escHtml(name)}» متوقف است`]);
    else if (t.last_crash_s !== null && t.last_crash_s < 3600) items.push(["warn", `🔁 بخش «${escHtml(name)}» ${faDur(t.last_crash_s)} پیش دوباره راه‌اندازی شد`]);
  }
  if (h.db && h.db.last_backup_age_s !== null && h.db.last_backup_age_s > 2 * 86400) items.push(["warn", `💾 آخرین نسخهٔ پشتیبان ${faDur(h.db.last_backup_age_s)} پیش بوده`]);
  for (const d of h.drift || []) items.push(["info", `🧱 ${link(d.watch, label(d.watch))} — ${d.level === "redesign" ? "بازطراحی احتمالی" : d.level === "collapse" ? "کوتاه شدن ناگهانی محتوا" : "تغییر گسترده"} (${faDur(d.age_s)} پیش)`]);
  return items;
}
function renderHealth() {
  const strip = document.getElementById("health-strip");
  const detail = document.getElementById("health-detail");
  const h = appState && appState.health;
  if (!h) { strip.hidden = true; detail.hidden = true; return; }
  const items = healthItems(h);
  const level = h.status === "down" ? "error" : h.status === "degraded" ? "warn" : "ok";
  const attention = items.filter(i => i[0] !== "info").length;
  let title, sub = "";
  if (level === "ok") {
    title = "همه‌چیز سالم است";
    const b = h.db && h.db.last_backup_age_s;
    sub = b !== null && b !== undefined ? `آخرین نسخهٔ پشتیبان ${faDur(b)} پیش` : "";
    if (items.length) sub = `${fa(items.length)} رویداد اخیر برای مشاهده` + (sub ? " · " + sub : "");
  } else {
    title = level === "error" ? "مانیتور مشکل جدی دارد" : "نیاز به توجه";
    sub = attention ? `${fa(attention)} مورد` : "";
  }
  strip.hidden = false;
  strip.className = "health " + (level === "ok" ? "" : level);
  document.getElementById("health-text").innerHTML = `${escHtml(title)}${sub ? `<small>${escHtml(sub)}</small>` : ""}`;
  const pulseSvg = renderActivitySvg(appState.activity_7d || [], "نبض ۷ روز اخیر کل سامانه");
  const listHtml = items.length ? `<ul>${items.map(i => `<li>${i[1]}</li>`).join("")}</ul>` : "";
  detail.innerHTML = listHtml + pulseSvg;
  if (!detail.innerHTML) { strip.setAttribute("aria-expanded", "false"); detail.hidden = true; }
}
function toggleHealth() {
  const strip = document.getElementById("health-strip");
  const detail = document.getElementById("health-detail");
  const open = strip.getAttribute("aria-expanded") !== "true";
  strip.setAttribute("aria-expanded", open ? "true" : "false");
  detail.hidden = !open || !detail.innerHTML;
}

function siteCard(s) {
  const r = siteRank(s);
  const cls = r === 0 ? "st-error" : r <= 2 ? "st-warn" : s.status === "paused" ? "st-paused" : s.status === "ok" ? "st-ok" : "";
  const isSelected = selectedSiteKeys.has(s.key);
  const badges = [`<span class="badge ${escHtml(s.status)}">${escHtml(s.status_label)}</span>`];
  if (s.checking) badges.push(`<span class="badge info">${svgIcon('refresh', 11)} بررسی زنده…</span>`);
  if (s.drift) badges.push(`<span class="badge warn">🧱 ${s.drift.level === "redesign" ? "بازطراحی" : s.drift.level === "collapse" ? "محتوا کوتاه شد" : "تغییر گسترده"}</span>`);
  if (s.changes_24h) badges.push(`<span class="badge info">🔔 ${fa(s.changes_24h)} تغییر</span>`);
  if (s.only_keywords) badges.push(`<span class="badge neutral">🎯 کلیدی</span>`);
  const never = /^هنوز/.test(s.last_ok_ago || "");
  const times = [never ? "⏳ هنوز بررسی موفقی نشده" : `✅ بررسی ${escHtml(s.last_ok_ago)}`];
  if (s.last_change_ago && s.last_change_ago !== "بدون تغییر") times.push(`🔔 تغییر ${escHtml(s.last_change_ago)}`);
  if (s.next_due_in !== null && s.next_due_in !== undefined && s.status !== "paused") {
    times.push(`⏳ نوبت بعد: ${faDur(s.next_due_in)}`);
  }
  times.push(`⏱ هر ${escHtml(s.interval_human)}`);
  let note = "";
  if (s.suggestion) note = `<span class="card-note warn">💡 پیشنهاد: انتخابگر ${escHtml(s.suggestion.selector)} (${fa(Math.round(s.suggestion.cover * 100))}٪)</span>`;
  else if (s.last_error && (s.status === "error" || s.status === "broken")) note = `<span class="card-note err">❌ ${escHtml(s.last_error)}</span>`;
  else if (s.last_change_summary && s.changes_24h) note = `<span class="card-note">${escHtml(s.last_change_summary)}</span>`;

  const checkHtml = bulkMode ? `
    <button type="button" class="site-check ${isSelected ? 'checked' : ''}" role="checkbox" aria-checked="${isSelected}" aria-label="انتخاب «${escHtml(s.label)}»" onclick="toggleSiteSelect(${s.key}, event)">
      ${isSelected ? svgIcon('check', 13) : ''}
    </button>` : '';

  return `<article class="site-card ${cls} ${isSelected ? 'selected' : ''}" data-key="${s.key}" role="listitem">
    ${checkHtml}
    <button class="card-open" onclick="${bulkMode ? `toggleSiteSelect(${s.key}, event)` : `openSite(${s.key})`}" aria-label="باز کردن «${escHtml(s.label)}» — ${escHtml(s.status_label)}">
      <span class="card-title">${escHtml(s.label)}</span>
      <span class="card-badges">${badges.join("")}</span>
      <span class="card-host">${escHtml(hostOf(s.page_url))}</span>
      <span class="card-times">${times.map(t => `<span>${t}</span>`).join("")}</span>
      ${note}
    </button>
    <span class="card-side"><button class="btn icon-btn" onclick="quickCheck(${s.key}, this)" aria-label="بررسی فوری «${escHtml(s.label)}»" title="بررسی فوری">${svgIcon('refresh', 18)}</button></span>
  </article>`;
}

function renderHome() {
  if (!appState) return;
  const sites = appState.sites || [];
  renderHealth();
  renderFilters(sites);

  let banners = "";
  if (appState.pending_outbox && appState.pending_outbox > 0) {
    banners += `<div class="notice warn"><div class="grow"><b>📨 ${fa(appState.pending_outbox)} پیام در صف ارسال به تلگرام</b></div>
      <button class="btn sm danger" onclick="clearPendingOutbox()">🧹 پاکسازی صف</button></div>`;
  }
  banners += (appState.challenges || []).map(c => `<div class="notice warn"><div class="grow"><b>🛡 چالش کپچا برای «${escHtml(c.watch_label)}»</b>
      <small>یک لمس برای حل زنده داخل مینی‌اپ</small></div>
      <button class="btn sm primary" onclick="openChallengeModal('${escHtml(c.token)}')">🔓 حل کپچا</button></div>`).join("");
  document.getElementById("challenge-banner").innerHTML = banners;

  const bulkBar = document.getElementById("bulk-bar");
  if (bulkBar) {
    bulkBar.hidden = (!bulkMode || selectedSiteKeys.size === 0);
    const bulkCount = document.getElementById("bulk-count");
    if (bulkCount) bulkCount.textContent = `${fa(selectedSiteKeys.size)} سایت انتخاب شد`;
  }
  const btnBulk = document.getElementById("btn-bulk-mode");
  if (btnBulk) {
    btnBulk.classList.toggle("active", bulkMode);
    btnBulk.textContent = bulkMode ? "❌ خروج از انتخاب گروهی" : "☑️ انتخاب گروهی";
  }

  if (homeView === "events") {
    document.getElementById("filter-chips").hidden = true;
    document.getElementById("sites-list").hidden = true;
    document.getElementById("events-feed-panel").hidden = false;
    return;
  }
  document.getElementById("filter-chips").hidden = false;
  document.getElementById("sites-list").hidden = false;
  document.getElementById("events-feed-panel").hidden = true;

  const q = (document.getElementById("site-q").value || "").trim().toLowerCase();
  const list = sites.filter(s => matchesFilter(s) && (!q || s.label.toLowerCase().includes(q) || s.url.toLowerCase().includes(q)))
    .sort((a, b) => siteRank(a) - siteRank(b) || (b.last_change_ts || 0) - (a.last_change_ts || 0) || a.label.localeCompare(b.label, "fa"));
  const el = document.getElementById("sites-list");
  if (!sites.length) {
    el.innerHTML = `<div class="empty"><span class="big" aria-hidden="true">🛰</span><b>هنوز سایتی اضافه نکرده‌اید</b><br>
      <small>آدرس یک صفحه (مثلاً صفحهٔ نوبت‌دهی) را اضافه کنید تا مانیتور هر تغییر آن را به تلگرام بفرستد.</small><br><br>
      <button class="btn primary" onclick="openAddModal()">➕ افزودن نخستین سایت</button></div>`;
    return;
  }
  el.innerHTML = list.length ? list.map(siteCard).join("")
    : `<div class="empty"><span class="big" aria-hidden="true">🔎</span>هیچ سایتی با این فیلتر پیدا نشد.</div>`;
}

function onSearchInput() {
  document.getElementById("search-results").innerHTML = "";
  renderHome();
}

async function runHistorySearch() {
  const q = (document.getElementById("site-q").value || "").trim();
  if (!q) { toast("عبارتی برای جستجو بنویسید"); document.getElementById("site-q").focus(); return; }
  haptic("light");
  const box = document.getElementById("search-results");
  box.innerHTML = `<div class="panel-box">⏳ در حال جستجوی «${escHtml(q)}» در تاریخچه…</div>`;
  try {
    const res = await api(`/api/app/search?q=${encodeURIComponent(q)}`);
    if (!res.results.length) { box.innerHTML = `<div class="panel-box">نتیجه‌ای برای «${escHtml(q)}» یافت نشد.</div>`; return; }
    box.innerHTML = `<div class="panel-box">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px">
        <b>🔍 ${fa(res.results.length)} نتیجه در تاریخچه</b>
        <button class="btn sm" onclick="document.getElementById('search-results').innerHTML=''">بستن</button>
      </div>
      ${res.results.map(ev => `
        <div class="diff-block">
          <div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--muted);gap:8px;flex-wrap:wrap">
            <span>🕒 ${escHtml(ev.created_human)} · #${fa(ev.id)}</span>
            <span style="display:flex;gap:8px;align-items:center">
              ${ev.url ? `<a href="${escHtml(ev.url)}" target="_blank" rel="noopener">🔗 صفحه</a>` : ""}
              ${(ev.blocks_html && ev.blocks_html.length) ? `<button class="btn sm" type="button" onclick="downloadEventReport(${ev.id}, this)">📄 گزارش HTML</button>` : ""}
            </span>
          </div>
          <div>${ev.header_html}</div>
          ${(ev.blocks_html || []).slice(0, 3).map(b => `<div style="margin-top:6px">${formatDiffHtml(b)}</div>`).join("")}
        </div>`).join("")}
    </div>`;
  } catch (e) {
    box.innerHTML = "";
    toast("❌ " + e.message);
  }
}

async function downloadEventReport(eventId, btn) {
  haptic("light");
  const orig = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "⏳ آماده‌سازی…"; }
  try {
    const res = await api(`/api/app/event/${eventId}/report`);
    triggerBlobDownload(res.filename || `event-${eventId}.html`, res.html, "text/html;charset=utf-8");
    haptic("success");
    toast("📄 فایل گزارش HTML دانلود شد");
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = orig; }
  }
}

async function quickCheck(key, btn) {
  haptic("light");
  const origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = btn.classList.contains("icon-btn") ? "⏳" : "⏳ در حال بررسی…";
  try {
    const r = await api(`/api/app/site/${key}/check`, {method: "POST"});
    haptic("success");
    toast(`✅ بررسی شد (${fa(r.elapsed)} ثانیه): ${r.outcome}`);
    await loadState(true);
    if (currentSiteKey === key) await openSite(key, true);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHtml;
  }
}

async function checkAllSites() {
  haptic("medium");
  toast("🔄 بررسی فوری همهٔ سایت‌ها شروع شد");
  try {
    await api("/api/app/check-all", {method: "POST"});
    setTimeout(() => loadState(true), 2500);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function clearPendingOutbox(watchId = null) {
  haptic("medium");
  try {
    const res = await api("/api/app/clear-outbox", {method: "POST", body: JSON.stringify(watchId ? {watch_id: watchId} : {})});
    haptic("success");
    toast(`🧹 ${fa(res.cleared)} پیام از صف پاک شد`);
    await loadState(true);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

// ================================================================= ONE SITE
const TAB_IDS = ["overview", "diffs", "settings", "subpages"];

async function openSite(key, keepTab = false) {
  haptic("light");
  currentSiteKey = key;
  if (!keepTab) currentSiteTab = "overview";
  syncUrlState();
  document.getElementById("view-home").hidden = true;
  document.getElementById("view-site").hidden = false;
  if (tg && tg.BackButton) tg.BackButton.show();
  if (!keepTab) window.scrollTo(0, 0);
  document.getElementById("site-header-card").innerHTML = `<div class="skeleton" style="margin:0;height:70px"></div>`;
  try {
    currentSiteData = await api(`/api/app/site/${key}`);
    renderSiteProfile();
  } catch (e) {
    toast("❌ " + e.message);
    showHome();
  }
}

function showHome() {
  currentSiteKey = null;
  syncUrlState();
  document.getElementById("view-site").hidden = true;
  document.getElementById("view-home").hidden = false;
  if (tg && tg.BackButton) tg.BackButton.hide();
  loadState(true);
}

function switchSiteTab(tab, focus = false) {
  haptic("light");
  currentSiteTab = tab;
  syncUrlState();
  TAB_IDS.forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    btn.setAttribute("aria-selected", t === tab ? "true" : "false");
    btn.tabIndex = t === tab ? 0 : -1;
    document.getElementById(`site-tab-${t}`).hidden = t !== tab;
  });
  if (focus) document.getElementById(`tab-btn-${tab}`).focus();
}
document.getElementById("site-tabs").addEventListener("keydown", ev => {
  // the layout is right-to-left: the key that points left reaches the NEXT tab in the markup
  const step = ev.key === "ArrowLeft" ? 1 : ev.key === "ArrowRight" ? -1 : 0;
  if (!step) return;
  ev.preventDefault();
  const i = TAB_IDS.indexOf(currentSiteTab);
  switchSiteTab(TAB_IDS[(i + step + TAB_IDS.length) % TAB_IDS.length], true);
});

const EVENT_ICONS = {change: "🔔", error: "⚠️", recovery: "✅", recovered: "✅", new_items: "🆕", removed: "🗑", removed_page: "🗑", new_page: "🆕", file: "📎", info: "ℹ️", baseline: "📌"};

function toggleDiffSplit() {
  diffSplitMode = !diffSplitMode;
  renderSiteProfile();
}

function renderSiteProfile() {
  if (!currentSiteData) return;
  const s = currentSiteData.site;
  const ch = currentSiteData.challenge;
  document.getElementById("site-top-badges").innerHTML = `<span class="badge ${escHtml(s.status)}">${escHtml(s.status_label)}</span>`;

  let alerts = "";
  if (ch) alerts += `<div class="notice warn"><div class="grow"><b>🛡 این سایت منتظر حل کپچا / کلودفلر است</b><small>زمان باقی‌مانده: ${fa(ch.remaining)} ثانیه</small></div>
      <button class="btn sm primary" onclick="openChallengeModal('${escHtml(ch.token)}')">🔓 حل زنده</button></div>`;
  if (s.suggestion) alerts += `<div class="notice info"><div class="grow"><b>💡 ساختار صفحه عوض شده است</b>
      <small>انتخابگر فعلی (<code dir="ltr">${escHtml(s.selector || "")}</code>) دیگر چیزی پیدا نمی‌کند؛ بخش <code dir="ltr">${escHtml(s.suggestion.selector)}</code>
      همان محتوای قبلی را دارد (${fa(Math.round(s.suggestion.cover * 100))}٪ هم‌پوشانی).</small></div>
      <button class="btn sm primary" onclick="applySuggestion(${s.key}, this)">اعمال این انتخابگر</button></div>`;
  if (s.drift) alerts += `<div class="notice warn"><div class="grow"><b>🧱 ${s.drift.level === "redesign" ? "این صفحه احتمالاً بازطراحی شده" : s.drift.level === "collapse" ? "محتوای این صفحه ناگهان کوتاه شد" : "بخش بزرگی از این صفحه یکجا عوض شد"}</b>
      <small>${faDur(s.drift.age_s)} پیش؛ وضعیت جدید به‌عنوان مبنا ذخیره شده است.</small></div>
      <button class="btn sm" onclick="switchSiteTab('diffs', true)">دیدن تغییر</button></div>`;
  if (s.status === "error" && s.last_error && !s.suggestion) alerts += `<div class="notice err"><div class="grow"><b>❌ آخرین خطا</b><small>${escHtml(s.last_error)}</small></div></div>`;

  document.getElementById("site-header-card").innerHTML = `
    ${alerts}
    <h2 style="font-size:18px;line-height:1.5">${escHtml(s.label)}</h2>
    <a href="${escHtml(s.page_url)}" target="_blank" rel="noopener" dir="ltr" style="font-size:12px;word-break:break-all;display:inline-block">🔗 ${escHtml(s.page_url)}</a>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
      <button class="btn primary" onclick="quickCheck(${s.key}, this)">🔄 بررسی الان</button>
      <button class="btn" onclick="captureSiteScreenshot(${s.key}, this)">📸 عکس زنده</button>
      <button class="btn" onclick="diagnoseSite(${s.key}, this)">🧪 تست دسترسی</button>
      <button class="btn" onclick="toggleSiteField('enabled', ${!s.enabled})">${s.enabled ? "⏸ توقف موقت" : "▶️ ادامهٔ پایش"}</button>
    </div>`;

  const lastChange = s.last_change_summary ? `<div class="notice info" style="margin:10px 0 0"><div class="grow"><b>آخرین تغییر (${escHtml(s.last_change_ago)})</b><small>${escHtml(s.last_change_summary)}</small></div>
      <button class="btn sm" onclick="switchSiteTab('diffs', true)">تاریخچه</button></div>` : "";
  const routeBadge = s.proxy ? `پروکسی اختصاصی` : (s.route === "fallback" ? "پروکسی پشتیبان (WARP)" : "مستقیم");
  const sitePulse = renderActivitySvg(currentSiteData.activity_7d || [], "فعالیت ۷ روز اخیر این سایت");
  document.getElementById("site-tab-overview").innerHTML = `
    <div class="panel-box">
      <div class="facts">
        <div class="fact"><span>✅ آخرین بررسی موفق</span><b>${/^هنوز/.test(s.last_ok_ago || "") ? "هنوز موفق نبوده" : escHtml(s.last_ok_ago)}</b></div>
        <div class="fact"><span>🔔 آخرین تغییر</span><b>${escHtml(s.last_change_ago)}</b></div>
        <div class="fact"><span>⏱ فاصلهٔ بررسی</span><b>هر ${escHtml(s.interval_human)}</b></div>
        <div class="fact"><span>⚙️ موتور و مسیر</span><b>${escHtml(s.engine_label)} · ${escHtml(routeBadge)}</b></div>
        <div class="fact"><span>🧭 نوع پایش</span><b>${escHtml(s.type_label)}</b></div>
        <div class="fact"><span>📂 زیرصفحه‌ها</span><b>${fa(s.subpages_count)}</b></div>
        <div class="fact"><span>🎯 کلمات کلیدی</span><b>${s.keywords.length ? escHtml(s.keywords.join("، ")) : "همهٔ تغییرات"}</b></div>
        <div class="fact"><span>🍪 کوکی</span><b>${s.has_cookies ? "دارد" : "ندارد"}</b></div>
      </div>
      ${sitePulse}
      ${lastChange}
      <div id="diag-box" style="margin-top:10px" aria-live="polite"></div>
      <div id="live-shot-box" style="margin-top:10px" aria-live="polite"></div>
    </div>`;

  const evs = currentSiteData.events || [];
  document.getElementById("site-tab-diffs").innerHTML = `
    <div class="panel-box">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
        <h3 style="margin:0;font-size:15px">🕘 تاریخچه (${fa(evs.length)})</h3>
        <div class="row-inline" style="flex-wrap:wrap">
          <button class="btn sm ${diffSplitMode ? "primary" : ""}" onclick="toggleDiffSplit()">◫ نمای دوطرفه</button>
          <input class="input" style="max-width:210px" type="search" aria-label="جستجو در تاریخچهٔ همین سایت" placeholder="جستجو در همین سایت…" oninput="filterSiteDiffs(this.value)">
        </div>
      </div>
      ${evs.length === 0 ? `<div class="empty">هنوز تغییری برای این سایت ثبت نشده است.</div>` : evs.map((ev, i) => `
        <details class="event site-diff-item" ${i === 0 ? "open" : ""}>
          <summary>
            <span aria-hidden="true">${EVENT_ICONS[ev.kind] || "📌"}</span>
            <span class="when">${escHtml(ev.created_short || ev.created_human)} · شمارهٔ ${fa(ev.id)}</span>
            ${ev.drift_level ? `<span class="badge warn">🧱 ${ev.drift_level === "redesign" ? "بازطراحی" : ev.drift_level === "collapse" ? "محتوا کوتاه شد" : "تغییر گسترده"}</span>` : ""}
            ${ev.summary ? `<span class="sum">${escHtml(ev.summary)}</span>` : ""}
          </summary>
          <div class="body">
            <div class="diff-block">${ev.header_html}</div>
            ${(ev.blocks_html || []).map(b => `<div class="diff-block">${formatDiffHtml(b)}</div>`).join("")}
            <div class="ev-foot">
              ${ev.url ? `<a href="${escHtml(ev.url)}" target="_blank" rel="noopener">🔗 باز کردن صفحه</a>` : `<span></span>`}
              ${(ev.blocks_html && ev.blocks_html.length) ? `<button class="btn sm" type="button" onclick="downloadEventReport(${ev.id}, this)">📄 گزارش کامل HTML</button>` : ""}
            </div>
          </div>
        </details>`).join("")}
    </div>`;

  document.getElementById("site-tab-settings").innerHTML = `
    <div class="group-title">پایش</div>
    <div class="panel-box">
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="edit-name">📝 نام نمایشی سایت</label></b><small>نام دلخواه برای شناسایی سریع در اعلان‌ها و داشبورد</small></div>
        <div class="row-inline">
          <input class="input" id="edit-name" value="${escHtml(s.name || '')}" placeholder="نام دلخواه سایت" style="flex:1">
          <button class="btn" onclick="saveSiteName()">ذخیره نام</button>
        </div>
      </div>
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="edit-url">🔗 آدرس صفحه (URL)</label></b><small>تغییر آدرس بدون از دست رفتن تنظیمات یا تاریخچه</small></div>
        <div class="row-inline">
          <input class="input" id="edit-url" dir="ltr" autocapitalize="off" spellcheck="false" value="${escHtml(s.url || '')}" placeholder="https://example.com" style="flex:1">
          <button class="btn" onclick="saveSiteUrl()">تغییر آدرس</button>
        </div>
      </div>
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="set-profile-preset">🎯 اعمال الگوی آماده (پروفایل کاربری)</label></b><small>تنظیم فوری انتخابگرها، بازه و موتور متناسب با نوع سایت</small></div>
        <div class="row-inline">
          <select class="input" id="set-profile-preset" style="flex:1">
            <option value="">انتخاب الگوی متناسب با این سایت…</option>
            ${((appState && appState.profiles) || FALLBACK_PROFILES).map(p => `<option value="${p.id}">${PROFILE_EMOJIS[p.icon] || "🎯"} ${escHtml(p.label)} — ${escHtml(p.desc)}</option>`).join("")}
          </select>
          <button class="btn" onclick="applySelectedPreset()">اعمال الگو</button>
        </div>
      </div>
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="set-interval">⏱ فاصلهٔ بررسی</label></b><small>فعلی: هر ${escHtml(s.interval_human)} (صفحهٔ اصلی و زیرصفحه‌ها)</small></div>
        <select class="input" id="set-interval" onchange="toggleSiteField('interval_seconds', parseInt(this.value,10))">${buildIntervalOptions(s.interval_seconds, s.interval_human)}</select>
      </div>
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="custom-interval-val">✍️ زمان دلخواه</label></b><small>هر عددی بین ۱ دقیقه تا ۲۴ ساعت</small></div>
        <div class="row-inline">
          <input class="input" id="custom-interval-val" type="number" inputmode="decimal" min="1" max="1440" placeholder="مثلاً 3" style="flex:1">
          <select class="input" id="custom-interval-unit" aria-label="واحد زمان" style="width:96px"><option value="3600" selected>ساعت</option><option value="60">دقیقه</option></select>
          <button class="btn primary" onclick="saveCustomInterval()">ثبت</button>
        </div>
      </div>
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="set-engine">⚙️ موتور دریافت صفحه</label></b><small>پیشنهاد: خودکار (در صورت مسدودی به شبیه‌ساز کروم و مرورگر می‌رود)</small></div>
        <select class="input" id="set-engine" onchange="toggleSiteField('engine', this.value)">
          <option value="auto" ${s.engine === "auto" ? "selected" : ""}>خودکار (پیشنهادی)</option>
          <option value="http" ${s.engine === "http" ? "selected" : ""}>سریع (HTTP)</option>
          <option value="impersonate" ${s.engine === "impersonate" ? "selected" : ""}>شبیه‌ساز کروم (ضدکلودفلر)</option>
          <option value="browser" ${s.engine === "browser" ? "selected" : ""}>مرورگر کامل</option>
        </select>
      </div>
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="edit-proxy">🌐 پروکسی اختصاصی این سایت</label></b><small>خالی بگذارید تا از مسیر خودکار یا پروکسی پشتیبان استفاده شود</small></div>
        <div class="row-inline">
          <input class="input" id="edit-proxy" dir="ltr" autocapitalize="off" spellcheck="false" value="${escHtml(s.proxy || '')}" placeholder="socks5://127.0.0.1:40000" style="flex:1">
          <button class="btn" onclick="saveSiteProxy()">ذخیره</button>
        </div>
      </div>
      ${switchRow("sw-crawl", `🕷 خزش زیرصفحه‌ها (${fa(s.subpages_count)} صفحه)`, "پایش لینک‌های داخلی این بخش؛ خاموش کردن پیام‌ها را کم می‌کند", s.crawl_enabled, `toggleSiteField('crawl_enabled', ${!s.crawl_enabled})`)}
    </div>

    <div class="group-title">اعلان‌ها</div>
    <div class="panel-box">
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="edit-kw">🔑 کلمات کلیدی</label></b><small>با ویرگول جدا کنید؛ تغییرهای دارای این کلمه‌ها اولویت می‌گیرند</small></div>
        <div class="row-inline">
          <input class="input" id="edit-kw" value="${escHtml(s.keywords.join(', '))}" placeholder="نوبت, ویزا, Termin" style="flex:1">
          <button class="btn primary" onclick="saveKeywords()">ذخیره</button>
        </div>
      </div>
      ${switchRow("sw-onlykw", "🎯 فقط تغییرهای دارای کلمهٔ کلیدی", "بقیهٔ تغییرها ثبت می‌شوند ولی پیام نمی‌فرستند", s.only_keywords, `toggleOnlyKeywords(${!s.only_keywords})`)}
      ${switchRow("sw-alarm", "⏰ حالت بیدارباش", "تکرار هشدار تا وقتی «دیدم» را بزنید", s.alarm, `toggleSiteField('alarm', ${!s.alarm})`)}
      ${switchRow("sw-silent", "🔕 ارسال بی‌صدا", "بدون صدای اعلان (مگر کلمهٔ کلیدی داشته باشد)", s.silent, `toggleSiteField('silent', ${!s.silent})`)}
      ${switchRow("sw-shot", "📸 عکس صفحه همراه گزارش", "با هر تغییر، تصویر صفحه هم فرستاده شود", s.notify_mode === "both", `toggleSiteField('notify_mode', '${s.notify_mode === "both" ? "text" : "both"}')`)}
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="set-rstyle">📝 سبک نمایش تغییرات</label></b><small>نحوهٔ نمایش خطوط ویرایش‌شده در پیام‌ها و فایل HTML</small></div>
        <select class="input" id="set-rstyle" onchange="toggleSiteField('report_style', this.value)">
          <option value="inline" ${s.report_style === "inline" ? "selected" : ""}>درون‌خطی (فشرده و کلمه‌به‌کلمه)</option>
          <option value="before_after" ${s.report_style === "before_after" ? "selected" : ""}>قبل / بعد + مقایسهٔ کلمه‌به‌کلمه (کامل)</option>
          <option value="side_by_side" ${s.report_style === "side_by_side" ? "selected" : ""}>مقایسهٔ دوطرفه (قبل ⫷⫸ بعد)</option>
        </select>
      </div>
    </div>

    <div class="group-title">تشخیص تغییر</div>
    <div class="panel-box">
      ${switchRow("sw-links", "🔗 گزارش تغییر آدرس لینک‌ها", "اگر خاموش باشد فقط تغییر متن گزارش می‌شود", s.track_links, `toggleSiteField('track_links', ${!s.track_links})`)}
      ${switchRow("sw-reorder", "🔍 حساسیت حداکثری (حتی جابه‌جایی خطوط)", "کوچک‌ترین تغییرها و جابه‌جایی پاراگراف‌ها هم گزارش شود", !s.ignore_reorder, `toggleSiteField('ignore_reorder', ${!s.ignore_reorder})`)}
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="edit-sel">🎯 انتخابگر بخش صفحه (CSS Selector)</label></b><small>مثلاً <code>#main</code> یا <code>article</code> — خالی یعنی کل صفحه</small></div>
        <input class="input" id="edit-sel" dir="ltr" autocapitalize="off" spellcheck="false" value="${escHtml(s.selector || '')}" placeholder="#main">
      </div>
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="edit-excl">🚫 بخش‌های حذفی (Exclude Selectors)</label></b><small>حذف تبلیغات، شمارنده یا فوتر مزاحم (با ویرگول جدا کنید)</small></div>
        <input class="input" id="edit-excl" dir="ltr" autocapitalize="off" spellcheck="false" value="${escHtml((s.exclude_selectors || []).join(', '))}" placeholder=".ads, .cookie-banner">
      </div>
      <div class="setting-row stack">
        <div class="setting-info"><b><label for="edit-igpat">🔇 الگوهای نادیده‌گرفتن خط (Regex)</label></b><small>هر خط یک عبارت باقاعده (مثلاً تاریخ یا شمارندهٔ بازدید)</small></div>
        <textarea class="input" id="edit-igpat" dir="ltr" autocapitalize="off" spellcheck="false" rows="2" placeholder="^بازدید امروز:">${escHtml((s.ignore_patterns || []).join('\n'))}</textarea>
        <div style="display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap">
          <button class="btn" type="button" onclick="previewDetectionFilters(this)">👁 پیش‌نمایش استخراج</button>
          <button class="btn primary" onclick="saveDetectionFilters()">💾 ذخیره فیلترهای تشخیص</button>
        </div>
        <div id="extract-preview-box" aria-live="polite"></div>
      </div>
    </div>

    <div class="group-title">منطقهٔ خطر</div>
    <div class="panel-box">
      <div class="setting-row">
        <div class="setting-info"><b>📋 کپی کردن این سایت (Clone)</b><small>یک نسخهٔ مشابه با همین تنظیمات بسازید (برای بخش‌های دیگر همین سایت)</small></div>
        <button class="btn" onclick="cloneCurrentSite(${s.key})">کپی گرفتن</button>
      </div>
      <div class="setting-row">
        <div class="setting-info"><b>🧹 شروع از صفر</b><small>حافظه و نسخه‌های قبلی این سایت پاک می‌شود</small></div>
        <button class="btn danger" onclick="resetSiteMemory(${s.key})">ریست</button>
      </div>
      <div class="setting-row">
        <div class="setting-info"><b>🗑 حذف سایت</b><small>این سایت کامل از مانیتور برداشته می‌شود</small></div>
        <button class="btn danger" onclick="deleteSite(${s.key})">حذف</button>
      </div>
    </div>`;

  const subs = currentSiteData.subpages || [];
  document.getElementById("site-tab-subpages").innerHTML = `
    <div class="panel-box">
      <h3 style="font-size:15px">🍪 وارد کردن کوکی</h3>
      <p style="font-size:12px;color:var(--muted);margin:0 0 8px">اگر سایت لاگین یا کوکی <code>cf_clearance</code> می‌خواهد، خروجی JSON افزونهٔ Cookie-Editor، فرمت Netscape یا رشتهٔ کوکی را اینجا بچسبانید (برای هر دو موتور شبیه‌ساز کروم و مرورگر اعمال می‌شود):</p>
      <textarea class="input" id="cookie-input" rows="3" dir="ltr" autocapitalize="off" spellcheck="false" aria-label="متن کوکی" placeholder='[{"name":"cf_clearance","value":"..."}] یا cf_clearance=...;'></textarea>
      <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
        <button class="btn primary" onclick="submitCookies(${s.key})">🍪 ذخیره کوکی</button>
        ${s.has_cookies ? `<button class="btn danger" onclick="clearCookies(${s.key})">پاک کردن کوکی فعلی</button>` : ""}
      </div>
    </div>
    <div class="panel-box">
      <h3 style="font-size:15px">📂 صفحه‌های کشف‌شده (${fa(subs.length)})</h3>
      ${subs.length ? subs.map(p => `
        <div style="padding:8px 0;border-bottom:1px solid var(--border);font-size:12px">
          <div style="font-weight:700">${escHtml(p.title)}</div>
          <a href="${escHtml(p.url)}" target="_blank" rel="noopener" dir="ltr" style="display:inline-block;word-break:break-all">${escHtml(p.url)}</a>
          <div style="color:var(--muted)">آخرین بازدید: ${escHtml(p.last_seen)} · آخرین تغییر: ${escHtml(p.last_changed)}</div>
        </div>`).join("") : `<div class="empty">هنوز زیرصفحه‌ای کشف نشده است.</div>`}
    </div>`;

  switchSiteTab(currentSiteTab);
}

function filterSiteDiffs(q) {
  q = (q || "").toLowerCase();
  document.querySelectorAll(".site-diff-item").forEach(el => {
    const hit = !q || el.textContent.toLowerCase().includes(q);
    el.hidden = !hit;
    if (hit && q) el.open = true;
  });
}

async function diagnoseSite(key, btn) {
  haptic("light");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ در حال تست همهٔ مسیرها…";
  switchSiteTab("overview");
  const box = document.getElementById("diag-box");
  box.innerHTML = `<div class="notice info"><div class="grow"><b>🧪 در حال آزمایش موتورهای دریافت از روی سرور…</b><small>HTTP، شبیه‌ساز کروم و مرورگر بررسی می‌شوند.</small></div></div>`;
  try {
    const res = await api(`/api/app/site/${key}/diagnose`, {method: "POST"});
    haptic("success");
    const rec = res.recommended;
    box.innerHTML = `
      <div class="panel-box" style="margin:0;background:var(--bg)">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px">
          <b>🧪 نتیجهٔ تست دسترسی</b>
          ${rec ? `<button class="btn sm primary" onclick="applyDiagRecommendation(${key}, '${escHtml(rec.route)}', '${escHtml(rec.engine)}')">⚡ استفاده از ${escHtml(rec.engine_label)} (${rec.route === 'fallback' ? 'پروکسی پشتیبان' : 'مستقیم'})</button>` : ""}
        </div>
        ${res.results.map(r => `<div style="font-size:12.5px;padding:4px 0;border-bottom:1px solid var(--border)">
          ${r.ok ? "✅" : "❌"} <b>${escHtml(r.route_label)} · ${escHtml(r.engine_label)}:</b> <span style="color:var(--muted)">${escHtml(r.detail)}</span>
        </div>`).join("")}
      </div>`;
  } catch (e) {
    haptic("error");
    box.innerHTML = "";
    toast("❌ " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function applyDiagRecommendation(key, route, engine) {
  haptic("medium");
  try {
    await api(`/api/app/site/${key}/update`, {method: "POST", body: JSON.stringify({route, engine})});
    toast("✅ بهترین روش و مسیر دسترسی ذخیره شد");
    await openSite(key, true);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function captureSiteScreenshot(key, btn) {
  haptic("light");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "📸 در حال عکس‌برداری…";
  try {
    const res = await api(`/api/app/site/${key}/screenshot`, {method: "POST"});
    haptic("success");
    switchSiteTab("overview");
    const dlUrl = res.download_url || "";
    const fname = res.filename || `site-${key}.jpg`;
    const digest = res.digest || "";
    document.getElementById("live-shot-box").innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px">
        <div style="font-size:12px;color:var(--muted)">📸 تصویر زنده، ثبت‌شده در ${escHtml(res.taken_at)}:</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="btn sm primary" onclick="sendLiveShotToChat(${key}, '${escHtml(digest)}', this)">📨 ارسال به چت تلگرام</button>
          <button type="button" class="btn sm" onclick="downloadLiveShot('${escHtml(dlUrl)}', '${escHtml(fname)}')">📥 دانلود فایل عکس</button>
        </div>
      </div>
      <img class="live-shot" src="${res.image_data_url}" alt="تصویر زندهٔ صفحه">`;
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function sendLiveShotToChat(key, digest, btn) {
  haptic("light");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ در حال ارسال به چت…";
  try {
    await api(`/api/app/site/${key}/screenshot`, {
      method: "POST",
      body: JSON.stringify({digest, send_to_chat: true}),
    });
    haptic("success");
    toast("✅ عکس با کیفیت اصلی به چت تلگرام شما ارسال شد");
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

function downloadLiveShot(downloadUrl, filename) {
  haptic("light");
  if (!downloadUrl) {
    toast("⚠️ لینک دانلود در دسترس نیست؛ از «ارسال به چت تلگرام» استفاده کنید.");
    return;
  }
  const absUrl = new URL(downloadUrl, window.location.origin).href;
  if (tg && typeof tg.downloadFile === "function") {
    try {
      tg.downloadFile({url: absUrl, file_name: filename || "screenshot.jpg"});
      return;
    } catch (_) {}
  }
  openExternalLink(absUrl);
}

function _captureSiteDraft(excludeField) {
  const fieldToId = {
    name: "edit-name", url: "edit-url", selector: "edit-sel", exclude_selectors: "edit-excl",
    ignore_patterns: "edit-igpat", keywords: "edit-kw", proxy: "edit-proxy", interval_seconds: "custom-interval-val",
  };
  const skipId = fieldToId[excludeField] || "";
  const vals = {};
  Object.values(fieldToId).forEach(id => {
    if (id === skipId) return;
    const el = document.getElementById(id);
    if (el) vals[id] = el.value;
  });
  const pv = document.getElementById("extract-preview-box");
  return {vals, previewHtml: pv ? pv.innerHTML : ""};
}

function _restoreSiteDraft(draft) {
  if (!draft) return;
  Object.entries(draft.vals || {}).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el && val !== undefined) el.value = val;
  });
  if (draft.previewHtml) {
    const pv = document.getElementById("extract-preview-box");
    if (pv) pv.innerHTML = draft.previewHtml;
  }
}

async function toggleSiteField(field, value) {
  const targetKey = currentSiteKey;
  if (!targetKey) return;
  const draft = _captureSiteDraft(field);
  haptic("light");
  try {
    await api(`/api/app/site/${targetKey}/update`, {method: "POST", body: JSON.stringify({[field]: value})});
    haptic("success");
    toast("✅ ذخیره شد");
    if (currentSiteKey === targetKey) {
      await openSite(targetKey, true);
      if (currentSiteKey === targetKey) _restoreSiteDraft(draft);
    }
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
    if (currentSiteKey === targetKey) {
      await openSite(targetKey, true);
      if (currentSiteKey === targetKey) _restoreSiteDraft(draft);
    }
  }
}

async function saveSiteProxy() {
  const val = (document.getElementById("edit-proxy").value || "").trim();
  await toggleSiteField("proxy", val);
}

async function previewDetectionFilters(btn) {
  if (!currentSiteKey) return;
  haptic("light");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ دریافت پیش‌نمایش…";
  const box = document.getElementById("extract-preview-box");
  box.innerHTML = `<div class="notice info" style="margin:6px 0 0"><div class="grow"><b>👁 در حال استخراج آزمایشی با فیلترهای فعلی…</b><small>بدون تغییر در حافظهٔ پایش</small></div></div>`;
  const selector = (document.getElementById("edit-sel").value || "").trim();
  const exclude_selectors = (document.getElementById("edit-excl").value || "").trim();
  const ignore_patterns = (document.getElementById("edit-igpat").value || "").trim();
  try {
    const res = await api(`/api/app/site/${currentSiteKey}/preview`, {
      method: "POST",
      body: JSON.stringify({selector, exclude_selectors, ignore_patterns}),
    });
    haptic("success");
    const sample = (res.lines || []).length ? res.lines.map(escHtml).join("\n") : "(هیچ خطی با این انتخابگر/فیلتر باقی نماند)";
    const crawlMeta = res.crawl_count ? ` · ${fa(res.crawl_count)} لینک خزش` : "";
    box.innerHTML = `
      <div class="preview-box" style="color:var(--text)">
        <div style="font-size:11.5px;color:var(--muted);margin-bottom:4px">⚙️ ${escHtml(res.engine_label)} · HTTP ${res.status} · ${fa(res.elapsed)}s · ${fa(res.line_count)} خط (${fa(res.char_count)} کاراکتر · ${fa(res.links_count)} لینک${crawlMeta})</div>
        <div>${sample}</div>
      </div>`;
  } catch (e) {
    haptic("error");
    box.innerHTML = `<div class="notice warn" style="margin:6px 0 0"><div class="grow"><b>⚠️ پیش‌نمایش ناموفق بود</b><small>${escHtml(e.message)}</small></div></div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function saveDetectionFilters() {
  if (!currentSiteKey) return;
  haptic("light");
  const selector = (document.getElementById("edit-sel").value || "").trim();
  const exclude_selectors = (document.getElementById("edit-excl").value || "").trim();
  const ignore_patterns = (document.getElementById("edit-igpat").value || "").trim();
  try {
    await api(`/api/app/site/${currentSiteKey}/update`, {
      method: "POST",
      body: JSON.stringify({selector, exclude_selectors, ignore_patterns}),
    });
    haptic("success");
    toast("✅ فیلترهای تشخیص ذخیره شد");
    await openSite(currentSiteKey, true);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  }
}

async function applySuggestion(key, btn) {
  haptic("medium");
  btn.disabled = true;
  try {
    const r = await api(`/api/app/site/${key}/apply-suggestion`, {method: "POST"});
    haptic("success");
    toast(`✅ انتخابگر ${r.selector} اعمال شد: ${r.outcome}`);
    await loadState(true);
    await openSite(key, true);
  } catch (e) {
    haptic("error");
    btn.disabled = false;
    toast("❌ " + e.message);
  }
}

async function toggleOnlyKeywords(enable) {
  if (!currentSiteData || !currentSiteData.site) return;
  if (enable && (!currentSiteData.site.keywords || !currentSiteData.site.keywords.length)) {
    toast("⚠️ اول کلمات کلیدی را وارد و ذخیره کنید");
    return;
  }
  await toggleSiteField("only_keywords", enable);
}

async function saveCustomInterval() {
  const val = parseFloat(document.getElementById("custom-interval-val").value || "0");
  const unit = parseInt(document.getElementById("custom-interval-unit").value || "3600", 10);
  if (!val || val <= 0) { toast("یک عدد معتبر وارد کنید"); return; }
  await toggleSiteField("interval_seconds", Math.max(15, Math.min(86400, Math.round(val * unit))));
}

async function saveKeywords() {
  const raw = document.getElementById("edit-kw").value || "";
  await toggleSiteField("keywords", raw.replace(/،/g, ",").split(",").map(s => s.trim()).filter(Boolean));
}

async function resetSiteMemory(key) {
  if (!await askConfirm("حافظه و نسخه‌های قبلی این سایت پاک شود و از نو شروع کند؟")) return;
  haptic("medium");
  try {
    await api(`/api/app/site/${key}/reset`, {method: "POST"});
    toast("🧹 حافظهٔ سایت پاک شد و بررسی مجدد آغاز شد");
    await openSite(key, true);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function submitCookies(key) {
  const val = document.getElementById("cookie-input").value.trim();
  if (!val) { toast("متن کوکی را وارد کنید"); return; }
  try {
    const r = await api(`/api/app/site/${key}/cookies`, {method: "POST", body: JSON.stringify({cookies: val})});
    haptic("success");
    toast(`✅ ${fa(r.count)} کوکی ذخیره شد`);
    await openSite(key, true);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function clearCookies(key) {
  try {
    await api(`/api/app/site/${key}/cookies`, {method: "POST", body: JSON.stringify({cookies: "-"})});
    toast("🗑 کوکی‌های سایت پاک شد");
    await openSite(key, true);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function deleteSite(key) {
  if (!await askConfirm("این سایت کامل حذف شود؟")) return;
  try {
    await api(`/api/app/site/${key}/delete`, {method: "POST"});
    toast("🗑 سایت حذف شد");
    showHome();
  } catch (e) {
    toast("❌ " + e.message);
  }
}

// ================================================================= MODALS, COMMAND PALETTE & SMART WIZARD
function openModal(id, focusId) {
  haptic("light");
  lastOpener = document.activeElement;
  const el = document.getElementById(id);
  el.style.display = "flex";
  el.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  const target = focusId ? document.getElementById(focusId) : el.querySelector("button, input, select");
  if (target) {
    try { target.focus(); } catch (_) {}
    setTimeout(() => { try { target.focus(); } catch (_) {} }, 30);
  }
}
function closeModals() {
  if (typeof stopChallengeTimers === "function") stopChallengeTimers();
  document.querySelectorAll(".modal-backdrop").forEach(el => { el.style.display = "none"; el.setAttribute("aria-hidden", "true"); });
  document.body.style.overflow = "";
  if (lastOpener && lastOpener.focus) { try { lastOpener.focus(); } catch (_) {} }
  lastOpener = null;
}
document.addEventListener("keydown", ev => {
  if ((ev.ctrlKey || ev.metaKey) && (ev.key === "k" || ev.key === "K")) {
    ev.preventDefault();
    const cmd = document.getElementById("modal-cmd");
    if (cmd.getAttribute("aria-hidden") === "false") closeModals();
    else openCmdModal();
    return;
  }
  if (ev.key === "Escape") closeModals();
  if (ev.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
    const qEl = document.getElementById("site-q");
    const vHome = document.getElementById("view-home");
    if (qEl && vHome && !vHome.hidden) {
      ev.preventDefault();
      qEl.focus();
      qEl.select();
    }
  }
});
document.querySelectorAll(".modal-backdrop").forEach(el => el.addEventListener("click", ev => {
  if (ev.target === el && el.id !== "modal-challenge") closeModals();
}));

function openCmdModal() {
  const qEl = document.getElementById("cmd-q");
  qEl.value = "";
  cmdActiveIndex = 0;
  renderCmdList();
  openModal("modal-cmd", "cmd-q");
}
function renderCmdList() {
  const q = (document.getElementById("cmd-q").value || "").trim().toLowerCase();
  const baseActions = [
    {label: "➕ افزودن سایت جدید", sub: "Smart URL Analyzer", run: () => { closeModals(); openAddModal(); }},
    {label: "🔄 بررسی فوری همهٔ سایت‌ها", sub: "Check all now", run: () => { closeModals(); checkAllSites(); }},
    {label: "📊 جریان رویدادها و تغییرات سراسری", sub: "Events & Audit Timeline", run: () => { closeModals(); showHome(); setHomeView('events'); }},
    {label: "☑️ فعال‌سازی حالت عملیات گروهی (Bulk)", sub: "Multi-select actions", run: () => { closeModals(); showHome(); toggleBulkMode(); }},
    {label: "🎨 تغییر تم ظاهری (تیره / روشن)", sub: "Theme Toggle", run: () => {
      const cur = localStorage.getItem("wm_theme_preference") || (document.documentElement.classList.contains("dark") ? "dark" : "light");
      onThemePreferenceChange(cur === "dark" ? "light" : "dark");
      closeModals();
    }},
    {label: "⚙️ تنظیمات کلی و پشتیبان‌گیری", sub: "Settings & Export/Import", run: () => { closeModals(); openSettingsModal(); }},
    {label: "⚠️ نمایش سایت‌های نیازمند توجه", sub: "Filter: attention", run: () => { closeModals(); showHome(); setFilter("error"); }},
    {label: "🔔 نمایش تغییرات ۲۴ ساعت اخیر", sub: "Filter: changed", run: () => { closeModals(); showHome(); setFilter("changed"); }},
  ];
  const siteActions = ((appState && appState.sites) || []).map(s => ({
    label: `${s.status === "ok" ? "🟢" : s.status === "paused" ? "⏸" : "⚠️"} ${s.label}`,
    sub: hostOf(s.page_url),
    hay: `${s.label} ${s.url} ${s.id}`.toLowerCase(),
    run: () => { closeModals(); openSite(s.key); },
  }));
  cmdItems = [
    ...baseActions.filter(a => !q || a.label.toLowerCase().includes(q) || a.sub.toLowerCase().includes(q)),
    ...siteActions.filter(s => !q || s.hay.includes(q)),
  ].slice(0, 30);
  if (cmdActiveIndex >= cmdItems.length) cmdActiveIndex = 0;
  const listEl = document.getElementById("cmd-list");
  if (!cmdItems.length) {
    listEl.innerHTML = `<div class="empty" style="padding:14px">موردی یافت نشد.</div>`;
    return;
  }
  listEl.innerHTML = cmdItems.map((item, idx) => `
    <button type="button" class="cmd-item ${idx === cmdActiveIndex ? "active" : ""}" role="option" aria-selected="${idx === cmdActiveIndex}" onclick="runCmdItem(${idx})">
      <span>${escHtml(item.label)}</span>
      <small>${escHtml(item.sub || "")}</small>
    </button>`).join("");
  const activeBtn = listEl.querySelector(".cmd-item.active");
  if (activeBtn && activeBtn.scrollIntoView) activeBtn.scrollIntoView({block: "nearest"});
}
function runCmdItem(idx) {
  const item = cmdItems[idx];
  if (item && item.run) item.run();
}
function onCmdKeydown(ev) {
  if (!cmdItems.length) return;
  if (ev.key === "ArrowDown") {
    ev.preventDefault();
    cmdActiveIndex = (cmdActiveIndex + 1) % cmdItems.length;
    renderCmdList();
  } else if (ev.key === "ArrowUp") {
    ev.preventDefault();
    cmdActiveIndex = (cmdActiveIndex - 1 + cmdItems.length) % cmdItems.length;
    renderCmdList();
  } else if (ev.key === "Enter") {
    ev.preventDefault();
    runCmdItem(cmdActiveIndex);
  }
}

function resetAddWizard() {
  wizardData = null;
  wizardChoiceIndex = -1;
  wizardCity = "";
  activeProfileId = null;
  renderAddProfiles();
  const box = document.getElementById("add-analysis-box");
  if (box) { box.hidden = true; box.innerHTML = ""; }
}
function onAddUrlEdit() {
  if (wizardData && document.getElementById("add-url").value.trim() !== wizardData.url) {
    resetAddWizard();
  }
}
function openAddModal() {
  resetAddWizard();
  renderAddProfiles();
  openModal("modal-add", "add-url");
}

async function runSmartAnalyze() {
  const url = document.getElementById("add-url").value.trim();
  if (!url) { toast("اول آدرس صفحه یا @کانال را بنویسید"); document.getElementById("add-url").focus(); return; }
  const btn = document.getElementById("btn-analyze");
  const box = document.getElementById("add-analysis-box");
  btn.disabled = true;
  btn.textContent = "⏳ بررسی…";
  box.hidden = false;
  box.innerHTML = `<div class="notice info" style="margin:0"><div class="grow"><b>🔎 در حال تحلیل ساختار صفحه از روی سرور…</b><small>تشخیص بخش‌های مهم، خبرخوان، جدول آزمون گوته و محافظ ضدربات</small></div></div>`;
  try {
    const res = await api("/api/app/analyze", {method: "POST", body: JSON.stringify({url})});
    wizardData = res;
    document.getElementById("add-url").value = res.url;
    if (!document.getElementById("add-name").value.trim() && res.suggested_name) {
      document.getElementById("add-name").value = res.suggested_name;
    }
    const intervalEl = document.getElementById("add-interval");
    if (res.recommended_interval && Array.from(intervalEl.options).some(o => parseInt(o.value, 10) === res.recommended_interval)) {
      intervalEl.value = String(res.recommended_interval);
    }
    const recIdx = Math.max(0, res.choices.findIndex(c => c.recommended));
    selectWizardChoice(recIdx);
    haptic("success");
  } catch (e) {
    haptic("error");
    wizardData = null;
    wizardChoiceIndex = -1;
    box.innerHTML = `<div class="notice warn" style="margin:0"><div class="grow"><b>⚠️ ${escHtml(e.message)}</b></div></div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "🔎 بررسی هوشمند";
  }
}

function selectWizardChoice(idx) {
  if (!wizardData || !wizardData.choices[idx]) return;
  wizardChoiceIndex = idx;
  const ch = wizardData.choices[idx];
  document.getElementById("add-type").value = ch.type;
  if (ch.preset === "goethe" && wizardData.goethe_keywords && wizardData.goethe_keywords.length && !document.getElementById("add-keywords").value.trim()) {
    document.getElementById("add-keywords").value = wizardData.goethe_keywords.join(", ");
  }
  const crawlBtn = document.getElementById("add-crawl");
  if (ch.type !== "page" && crawlBtn.classList.contains("on")) toggleSwitch(crawlBtn);
  renderWizardBox();
}

async function onWizardCityChange(city) {
  wizardCity = city;
  if (!wizardData) return;
  try {
    const res = await api("/api/app/analyze", {method: "POST", body: JSON.stringify({url: wizardData.url, city})});
    wizardData = res;
    renderWizardBox();
  } catch (_) {}
}

function renderWizardBox() {
  const box = document.getElementById("add-analysis-box");
  if (!wizardData) return;
  const ch = wizardData.choices[wizardChoiceIndex] || wizardData.choices[0];
  const notes = [];
  notes.push(`⚙️ ${escHtml(wizardData.engine_label)} (${fa(wizardData.elapsed)} ثانیه)`);
  if (wizardData.route === "fallback") notes.push("🛡 از طریق پروکسی پشتیبان");
  if (wizardData.protected) notes.push("🛡 دارای محافظ ضدربات");
  const cityPicker = (ch && ch.cities && ch.cities.length) ? `
    <div style="margin-top:8px">
      <label class="lbl" for="add-city">📍 فیلتر شهر آزمون</label>
      <select class="input" id="add-city" onchange="onWizardCityChange(this.value)">
        <option value="">🌍 همهٔ شهرها</option>
        ${ch.cities.map(c => `<option value="${escHtml(c)}" ${wizardCity === c ? "selected" : ""}>${escHtml(c)}</option>`).join("")}
      </select>
    </div>` : "";
  const previewText = (ch && ch.preview && ch.preview.length) ? ch.preview.map(escHtml).join("\n") : "(پیش‌نمایش خالی است)";
  box.hidden = false;
  box.innerHTML = `
    <div class="panel-box" style="margin:0;padding:10px 12px">
      <div style="font-size:12px;color:var(--muted);margin-bottom:4px">${notes.join(" · ")}</div>
      <b style="font-size:13px">🎯 پیشنهادهای پایش (یکی را انتخاب کنید):</b>
      <div class="choice-list">
        ${wizardData.choices.map((c, i) => `
          <button type="button" class="choice-btn ${i === wizardChoiceIndex ? "active" : ""}" onclick="selectWizardChoice(${i})">
            <b>${c.recommended ? "⭐ " : ""}${escHtml(c.label)}</b>
            ${c.desc ? `<small>${escHtml(c.desc)}</small>` : ""}
          </button>`).join("")}
      </div>
      ${cityPicker}
      <div class="preview-box" aria-label="پیش‌نمایش محتوای انتخابی"><b>👁 پیش‌نمایش:</b>\n${previewText}</div>
    </div>`;
}

function openSettingsModal() {
  if (!appState) return;
  const st = appState.settings;
  const customFp = (st.fallback_proxy && st.fallback_proxy !== "auto" && st.fallback_proxy !== "off") ? st.fallback_proxy : "";
  document.getElementById("global-settings-body").innerHTML = `
    <div class="setting-row stack">
      <div class="setting-info"><b><label for="gs-rstyle">📝 سبک پیش‌فرض گزارش تغییرات</label></b><small>برای سایت‌های جدید و گزارش‌های پیش‌فرض</small></div>
      <select class="input" id="gs-rstyle" onchange="saveGlobalSetting('report_style', this.value)">
        <option value="inline" ${st.report_style === "inline" ? "selected" : ""}>درون‌خطی (فشرده و کلمه‌به‌کلمه)</option>
        <option value="before_after" ${st.report_style === "before_after" ? "selected" : ""}>قبل / بعد + کلمه‌به‌کلمه (کامل)</option>
        <option value="side_by_side" ${st.report_style === "side_by_side" ? "selected" : ""}>مقایسهٔ دوطرفه (قبل ⫷⫸ بعد)</option>
      </select>
    </div>
    ${switchRow("gs-shot", "📸 عکس خودکار با همهٔ تغییرها", "همراه هر گزارش تغییر، تصویر صفحه هم می‌آید", st.auto_screenshot, `saveGlobalSetting('auto_screenshot', ${!st.auto_screenshot})`)}
    ${switchRow("gs-quiet", "🌙 ساعت سکوت شبانه (۰۰:۰۰ تا ۰۷:۰۰)", "تغییرهای عادی بی‌صدا می‌آیند؛ بیدارباش‌ها با صدا", st.quiet_hours, `saveGlobalSetting('quiet_hours', ${!st.quiet_hours})`)}
    ${switchRow("gs-daily", "📊 گزارش خلاصهٔ روزانه", "هر روز آمار سلامت پایش ارسال شود", st.daily_digest, `saveGlobalSetting('daily_digest', ${!st.daily_digest})`)}
    ${switchRow("gs-start", "🚀 پیام شروع‌به‌کار سرویس", "هنگام ری‌استارت سرور اطلاع بده", st.startup_notify, `saveGlobalSetting('startup_notify', ${!st.startup_notify})`)}
    <div class="setting-row stack">
      <div class="setting-info"><b><label for="gs-fp-mode">🛡 پروکسی پشتیبان ضدمسدودی</label></b><small>وقتی سایتی IP سرور را مسدود کند، خودکار از این مسیر می‌رود</small></div>
      <select class="input" id="gs-fp-mode" onchange="onFallbackModeChange(this.value)">
        <option value="auto" ${st.fallback_proxy === "auto" ? "selected" : ""}>خودکار (Cloudflare WARP)</option>
        <option value="off" ${st.fallback_proxy === "off" ? "selected" : ""}>خاموش</option>
        <option value="custom" ${customFp ? "selected" : ""}>آدرس پروکسی دلخواه</option>
      </select>
      <div class="row-inline" id="gs-fp-custom-row" ${customFp ? "" : "hidden"}>
        <input class="input" id="gs-fp-url" dir="ltr" autocapitalize="off" spellcheck="false" value="${escHtml(customFp)}" placeholder="socks5://127.0.0.1:40000" style="flex:1">
        <button class="btn sm primary" onclick="saveGlobalSetting('fallback_proxy', document.getElementById('gs-fp-url').value.trim())">ذخیره</button>
      </div>
    </div>
    <div class="setting-row stack">
      <div class="setting-info"><b><label for="gs-theme-pref">🎨 تم ظاهری مینی‌اپ</label></b><small>خودکار هماهنگ با تلگرام یا تم روشن/تیرهٔ ثابت</small></div>
      <select class="input" id="gs-theme-pref" onchange="onThemePreferenceChange(this.value)">
        <option value="auto" ${(localStorage.getItem("wm_theme_preference") || "auto") === "auto" ? "selected" : ""}>خودکار (پیروی از تلگرام یا سیستم)</option>
        <option value="dark" ${localStorage.getItem("wm_theme_preference") === "dark" ? "selected" : ""}>همیشه تیره (Dark)</option>
        <option value="light" ${localStorage.getItem("wm_theme_preference") === "light" ? "selected" : ""}>همیشه روشن (Light)</option>
      </select>
    </div>
    <div class="setting-row stack">
      <div class="setting-info"><b>💾 پشتیبان‌گیری و انتقال سایت‌ها</b><small>خروجی JSON بدون افشای رمز پروکسی · درون‌ریزی هوشمند با حذف تکراری‌ها</small></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn sm" type="button" onclick="exportWatchesJson(this)">📤 دانلود پشتیبان JSON</button>
        <button class="btn sm" type="button" onclick="document.getElementById('gs-import-file').click()">📥 درون‌ریزی فایل JSON</button>
        <input type="file" id="gs-import-file" accept=".json,application/json" hidden onchange="importWatchesFile(this)">
      </div>
    </div>
    <div class="setting-row">
      <div class="setting-info"><b>🧹 صف پیام‌های در انتظار</b><small>${fa(appState.pending_outbox || 0)} پیام منتظر ارسال است</small></div>
      <button class="btn danger" onclick="clearPendingOutbox()">پاکسازی</button>
    </div>`;
  openModal("modal-settings");
}

async function exportWatchesJson(btn) {
  haptic("light");
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ آماده‌سازی…";
  try {
    const res = await api("/api/app/export?redact=1");
    triggerBlobDownload(res.filename || "watches-backup.json", JSON.stringify(res.bundle, null, 2), "application/json;charset=utf-8");
    haptic("success");
    toast(`📤 پشتیبان ${fa(res.count)} سایت دانلود شد`);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function importWatchesFile(input) {
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return;
  haptic("medium");
  try {
    const raw = await file.text();
    const res = await api("/api/app/import", {method: "POST", body: JSON.stringify({raw})});
    haptic("success");
    toast(`✅ ${fa(res.added)} سایت اضافه شد · ${fa(res.duplicates)} تکراری · ${fa(res.invalid)} ردشده`);
    await loadState(true);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  }
}

function onFallbackModeChange(val) {
  if (val === "custom") {
    document.getElementById("gs-fp-custom-row").hidden = false;
    document.getElementById("gs-fp-url").focus();
  } else {
    saveGlobalSetting("fallback_proxy", val);
  }
}

async function saveGlobalSetting(k, v) {
  haptic("light");
  try {
    await api("/api/app/settings", {method: "POST", body: JSON.stringify({[k]: v})});
    await loadState(true);
    openSettingsModal();
    toast("✅ ذخیره شد");
  } catch (e) {
    toast("❌ " + e.message);
  }
}

function onThemePreferenceChange(val) {
  if (val === "dark" || val === "light") {
    localStorage.setItem("wm_theme_preference", val);
  } else {
    localStorage.removeItem("wm_theme_preference");
  }
  applyTheme();
  haptic("light");
  toast("🎨 تم با موفقیت تغییر کرد");
}

function setHomeView(view) {
  homeView = view;
  const sitesTab = document.getElementById("view-tab-sites");
  const eventsTab = document.getElementById("view-tab-events");
  if (sitesTab) {
    sitesTab.classList.toggle("active", view === "sites");
    sitesTab.setAttribute("aria-selected", view === "sites" ? "true" : "false");
  }
  if (eventsTab) {
    eventsTab.classList.toggle("active", view === "events");
    eventsTab.setAttribute("aria-selected", view === "events" ? "true" : "false");
  }
  renderHome();
  if (view === "events") {
    loadEventsFeed();
  }
}

async function loadEventsFeed(kind) {
  if (kind !== undefined) eventsFeedKind = kind;
  const listEl = document.getElementById("events-feed-list");
  if (!listEl) return;
  ["all", "changes", "errors"].forEach(k => {
    const btn = document.getElementById(`ef-${k}`);
    if (btn) {
      const active = (eventsFeedKind || "all") === k;
      btn.classList.toggle("active-chip", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    }
  });
  listEl.innerHTML = `<div class="empty"><span class="big">⏳</span>در حال بارگذاری رویدادها…</div>`;
  try {
    const res = await api(`/api/app/events?filter=${encodeURIComponent(eventsFeedKind || "all")}&limit=50`);
    eventsFeed = res.events || [];
    renderEventsFeed();
  } catch (e) {
    listEl.innerHTML = `<div class="empty"><span class="big">⚠️</span>خطا در بارگذاری رویدادها: ${escHtml(e.message)}</div>`;
  }
}

const EVENT_KIND_LABELS = {
  change: "تغییر", new_page: "صفحهٔ جدید", removed_page: "صفحهٔ حذف‌شده",
  new_items: "مورد جدید", file: "فایل جدید", error: "خطا",
  recovered: "رفع خطا", info: "اطلاع‌رسانی", baseline: "نسخهٔ مرجع",
};
function renderEventsFeed() {
  const listEl = document.getElementById("events-feed-list");
  if (!listEl) return;
  if (!eventsFeed || !eventsFeed.length) {
    listEl.innerHTML = `<div class="empty"><span class="big">📭</span>رویدادی یافت نشد.</div>`;
    return;
  }
  listEl.innerHTML = eventsFeed.map(ev => {
    const kind = ev.kind || "";
    const isErr = kind.includes("error") || kind.includes("fail");
    const isChange = kind.includes("change") || kind.includes("new_") || kind === "file" || kind === "removed_page";
    const badgeClass = isErr ? "danger" : (isChange ? "warn" : "neutral");
    const kindLabel = EVENT_KIND_LABELS[kind] || kind || "رویداد";
    const siteKey = ev.site_key;
    const siteLabel = ev.site_label || "سامانه";
    const hasSite = siteKey !== null && siteKey !== undefined;
    return `
      <article class="panel-box" style="margin-bottom:8px;padding:10px 12px">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap">
          <div style="display:flex;align-items:center;gap:6px;min-width:0">
            <span class="badge ${badgeClass}">${escHtml(kindLabel)}</span>
            ${hasSite
              ? `<button type="button" class="btn sm" style="padding:2px 8px;min-height:28px;font-weight:700" onclick="openSite(${siteKey})">${escHtml(siteLabel)}</button>`
              : `<b style="font-size:13px">${escHtml(siteLabel)}</b>`}
          </div>
          <span style="font-size:11px;color:var(--muted)">${escHtml(ev.created_human || "")}</span>
        </div>
        <div style="font-size:12px;line-height:1.6;color:var(--text)">${escHtml(ev.summary || "")}</div>
        ${ev.url ? `<div style="font-size:11px;color:var(--muted);direction:ltr;text-align:left;word-break:break-all;margin-top:2px"><a href="${escHtml(ev.url)}" target="_blank" rel="noopener">${escHtml(ev.url)}</a></div>` : ""}
        ${ev.has_report ? `<div style="margin-top:6px"><button type="button" class="btn sm" onclick="downloadEventReport(${ev.id}, this)">📄 گزارش HTML</button></div>` : ""}
      </article>`;
  }).join("");
}

function toggleBulkMode() {
  bulkMode = !bulkMode;
  if (!bulkMode) selectedSiteKeys.clear();
  const btn = document.getElementById("btn-bulk-mode");
  if (btn) btn.classList.toggle("active", bulkMode);
  renderHome();
}

function toggleSiteSelect(key, ev) {
  if (ev) ev.stopPropagation();
  key = parseInt(key, 10);
  if (selectedSiteKeys.has(key)) selectedSiteKeys.delete(key);
  else selectedSiteKeys.add(key);
  updateBulkBar();
  const card = document.querySelector(`.site-card[data-key="${key}"]`);
  if (card) {
    card.classList.toggle("selected", selectedSiteKeys.has(key));
    const chk = card.querySelector(".site-check");
    if (chk) {
      chk.classList.toggle("checked", selectedSiteKeys.has(key));
      chk.setAttribute("aria-checked", selectedSiteKeys.has(key) ? "true" : "false");
      chk.innerHTML = selectedSiteKeys.has(key) ? svgIcon("check", 13) : "";
    }
  }
}

function selectAllSites(select) {
  if (!appState || !appState.sites) return;
  if (select) {
    appState.sites.forEach(s => selectedSiteKeys.add(s.key));
  } else {
    selectedSiteKeys.clear();
  }
  renderHome();
}

function updateBulkBar() {
  const bar = document.getElementById("bulk-bar");
  const countSpan = document.getElementById("bulk-count");
  if (countSpan) countSpan.textContent = `${fa(selectedSiteKeys.size)} سایت انتخاب شد`;
  if (bar) bar.hidden = (!bulkMode || selectedSiteKeys.size === 0);
}

async function runBulkAction(action) {
  if (!selectedSiteKeys.size) {
    toast("ابتدا حداقل یک سایت را انتخاب کنید");
    return;
  }
  const keys = Array.from(selectedSiteKeys);
  const labels = {
    check: "بررسی فوری",
    pause: "توقف پایش",
    resume: "ادامهٔ پایش",
    silent_on: "بی‌صدا کردن",
    silent_off: "باصدا کردن",
    delete: "حذف کامل"
  };
  const label = labels[action] || action;
  if (action === "delete" && !(await askConfirm(`آیا از حذف ${fa(keys.length)} سایت انتخاب‌شده مطمئن هستید؟`))) {
    return;
  }
  haptic("medium");
  try {
    const res = await api("/api/app/bulk", {
      method: "POST",
      body: JSON.stringify({keys, action})
    });
    haptic("success");
    toast(`✅ عملیات «${label}» برای ${fa(res.affected)} سایت انجام شد`);
    selectedSiteKeys.clear();
    await loadState(true);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  }
}

function renderAddProfiles() {
  const box = document.getElementById("add-profiles-box");
  if (!box) return;
  const profiles = (appState && appState.profiles && appState.profiles.length) ? appState.profiles : (allProfiles || FALLBACK_PROFILES);
  box.innerHTML = `
    <div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <label class="lbl" style="margin:0">🎯 الگوهای آماده (پرسونای کاربری)</label>
        ${activeProfileId ? `<button type="button" class="btn sm" onclick="selectAddProfile(null)">پاک کردن انتخاب</button>` : ""}
      </div>
      <div class="profile-grid">
        ${profiles.map(p => `
          <button type="button" class="profile-btn ${activeProfileId === p.id ? "active" : ""}" onclick="selectAddProfile('${p.id}')">
            <b>${PROFILE_EMOJIS[p.icon] || "🎯"} ${escHtml(p.label)}</b>
            <small>${escHtml(p.desc)}</small>
          </button>`).join("")}
      </div>
    </div>`;
}

function selectAddProfile(id) {
  haptic("light");
  if (!id || activeProfileId === id) {
    activeProfileId = null;
    renderAddProfiles();
    return;
  }
  activeProfileId = id;
  renderAddProfiles();
  const profiles = (appState && appState.profiles) || (allProfiles || FALLBACK_PROFILES);
  const p = profiles.find(x => x.id === id);
  if (!p) return;
  const d = p.defaults || {};
  const nextType = p.type_hint || d.type;
  if (nextType) document.getElementById("add-type").value = nextType;
  if (d.interval_seconds) document.getElementById("add-interval").value = String(d.interval_seconds);
  if (d.keywords && !document.getElementById("add-keywords").value.trim()) {
    document.getElementById("add-keywords").value = d.keywords.join(", ");
  }
  const crawlBtn = document.getElementById("add-crawl");
  if (crawlBtn) {
    const crawlOn = Boolean(d.crawl_enabled);
    crawlBtn.classList.toggle("on", crawlOn);
    crawlBtn.setAttribute("aria-checked", crawlOn ? "true" : "false");
  }
}

async function saveSiteName() {
  if (!currentSiteData) return;
  const name = (document.getElementById("edit-name").value || "").trim();
  haptic("light");
  try {
    await api(`/api/app/site/${currentSiteData.site.key}/update`, {
      method: "POST",
      body: JSON.stringify({name})
    });
    haptic("success");
    toast("✅ نام نمایشی ذخیره شد");
    await loadState(true);
    await openSite(currentSiteData.site.key);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  }
}

async function saveSiteUrl() {
  if (!currentSiteData) return;
  const url = (document.getElementById("edit-url").value || "").trim();
  if (!url) { toast("آدرس سایت نمی‌تواند خالی باشد"); return; }
  haptic("light");
  try {
    await api(`/api/app/site/${currentSiteData.site.key}/update`, {
      method: "POST",
      body: JSON.stringify({url})
    });
    haptic("success");
    toast("✅ آدرس سایت به‌روزرسانی شد");
    await loadState(true);
    await openSite(currentSiteData.site.key);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  }
}

async function applySelectedPreset() {
  if (!currentSiteData) return;
  const sel = document.getElementById("set-profile-preset");
  const pid = sel ? sel.value : "";
  if (!pid) { toast("لطفاً یک الگو انتخاب کنید"); return; }
  const profiles = (appState && appState.profiles) || (allProfiles || FALLBACK_PROFILES);
  const p = profiles.find(x => x.id === pid);
  if (!p || !p.defaults) return;
  const d = p.defaults;
  const patch = {};
  if (d.interval_seconds) patch.interval_seconds = d.interval_seconds;
  if (d.type) patch.type = d.type;
  if (d.engine) patch.engine = d.engine;
  if (d.selector !== undefined) patch.selector = d.selector;
  if (d.exclude_selectors) patch.exclude_selectors = d.exclude_selectors;
  if (d.ignore_patterns) patch.ignore_patterns = d.ignore_patterns;
  if (d.alarm !== undefined) patch.alarm = d.alarm;
  if (d.only_keywords !== undefined) patch.only_keywords = d.only_keywords;
  if (d.keywords && d.keywords.length) {
    const existing = currentSiteData.site.keywords || [];
    const merged = Array.from(new Set([...existing, ...d.keywords]));
    patch.keywords = merged;
  }
  haptic("medium");
  try {
    await api(`/api/app/site/${currentSiteData.site.key}/update`, {
      method: "POST",
      body: JSON.stringify(patch)
    });
    haptic("success");
    toast(`✅ الگوی «${p.label}» با موفقیت اعمال شد`);
    await loadState(true);
    await openSite(currentSiteData.site.key);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  }
}

async function cloneCurrentSite(key) {
  key = (key !== undefined) ? key : (currentSiteData && currentSiteData.site.key);
  if (key === undefined || key === null) return;
  haptic("medium");
  try {
    const res = await api(`/api/app/site/${key}/clone`, {method: "POST"});
    haptic("success");
    const clonedName = res.name || (currentSiteData && currentSiteData.site && currentSiteData.site.label) || "";
    toast(clonedName ? `📋 سایت کپی شد: ${clonedName}` : "📋 سایت کپی شد");
    await loadState(true);
    openSite(res.key);
  } catch (e) {
    haptic("error");
    toast("❌ " + e.message);
  }
}

let addSitePending = false;
async function submitAddSite() {
  if (addSitePending) return;
  const url = document.getElementById("add-url").value.trim();
  if (!url) { toast("آدرس سایت را وارد کنید"); document.getElementById("add-url").focus(); return; }
  addSitePending = true;
  const submitBtn = document.getElementById("btn-submit-add");
  const origSubmit = submitBtn ? submitBtn.textContent : "";
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "⏳ در حال ذخیره…"; }
  haptic("medium");
  const payload = {
    url,
    name: document.getElementById("add-name").value.trim(),
    type: document.getElementById("add-type").value,
    interval_seconds: parseInt(document.getElementById("add-interval").value, 10),
    keywords: document.getElementById("add-keywords").value,
    crawl_enabled: document.getElementById("add-crawl").classList.contains("on"),
  };
  if (activeProfileId) payload.profile = activeProfileId;
  if (wizardData && wizardData.choices[wizardChoiceIndex]) {
    const ch = wizardData.choices[wizardChoiceIndex];
    payload.type = ch.type;
    if (ch.type === "feed" || ch.type === "json") payload.url = ch.url || url;
    if (ch.type === "json") {
      payload.link = ch.page || wizardData.url;
      payload.alarm = true;
      if (wizardCity && ch.filter_field) payload.json_filter = {[ch.filter_field]: wizardCity};
    } else if (ch.type === "items") {
      payload.item_selector = ch.selector;
      if (ch.link_selector) payload.item_link_selector = ch.link_selector;
      if (ch.exclude && ch.exclude.length) payload.exclude_selectors = ch.exclude;
    } else if (ch.selector) {
      payload.selector = ch.selector;
    }
    if (ch.type === "page" && ch.preview_total > 0 && ch.preview_total < 90) {
      payload.min_content_length = Math.max(1, Math.floor(ch.preview_total / 3));
    }
    if (wizardData.route) payload.route = wizardData.route;
    if (wizardData.engine) payload.preferred_engine = wizardData.engine;
  }
  try {
    const res = await api("/api/app/add", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    resetAddWizard();
    closeModals();
    toast("✅ سایت اضافه شد و پایش آغاز شد");
    await loadState(true);
    openSite(res.key);
  } catch (e) {
    toast("❌ " + e.message);
  } finally {
    addSitePending = false;
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = origSubmit || "✅ ذخیره و شروع پایش"; }
  }
}

let activeChallengeToken = null;
let challengeRemaining = 0;
let challengeCountdownTimer = null;
let challengeFrameTimer = null;
let challengeFrameInFlight = false;
function stopChallengeTimers() {
  if (challengeCountdownTimer) { clearInterval(challengeCountdownTimer); challengeCountdownTimer = null; }
  if (challengeFrameTimer) { clearTimeout(challengeFrameTimer); challengeFrameTimer = null; }
  activeChallengeToken = null;
}
function _scheduleNextChallengeFrame(token) {
  if (challengeFrameTimer) { clearTimeout(challengeFrameTimer); challengeFrameTimer = null; }
  if (!activeChallengeToken || activeChallengeToken !== token) return;
  challengeFrameTimer = setTimeout(async () => {
    challengeFrameTimer = null;
    if (!activeChallengeToken || activeChallengeToken !== token) return;
    if (!document.hidden) await refreshChallengeFrame(true);
    _scheduleNextChallengeFrame(token);
  }, 3000);
}
function _renderChallengeTimer() {
  const el = document.getElementById("ch-timer");
  if (!el) return;
  const s = Math.max(0, Math.floor(challengeRemaining));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  el.textContent = `${fa(m)}:${fa(String(rem).padStart(2, "0"))}`;
}
async function openChallengeModal(token, label) {
  stopChallengeTimers();
  activeChallengeToken = token;
  challengeForceDone = false;
  if (!label) {
    const found = (appState && appState.challenges || []).find(c => c.token === token);
    label = (found && found.watch_label) || (currentSiteData && currentSiteData.site && currentSiteData.site.label) || "";
  }
  document.getElementById("ch-title").textContent = label ? `🛡 حل کپچا — «${label}»` : "🛡 حل زندهٔ کپچا";
  document.getElementById("ch-coords").textContent = "1280×900";
  openModal("modal-challenge");
  await refreshChallengeFrame();
  if (activeChallengeToken !== token) return;
  challengeCountdownTimer = setInterval(() => {
    if (!activeChallengeToken || activeChallengeToken !== token) { stopChallengeTimers(); return; }
    if (challengeRemaining > 0) {
      challengeRemaining -= 1;
      _renderChallengeTimer();
    } else {
      stopChallengeTimers();
      toast("⌛ زمان چالش به پایان رسید");
    }
  }, 1000);
  _scheduleNextChallengeFrame(token);
}

async function refreshChallengeFrame(silent = false) {
  const token = activeChallengeToken;
  if (!token || challengeFrameInFlight) return;
  challengeFrameInFlight = true;
  try {
    const res = await api(`/api/app/challenge/${token}/frame`);
    if (activeChallengeToken !== token) return;
    document.getElementById("ch-img").src = res.image_data_url;
    challengeRemaining = Math.max(0, Number(res.remaining || 0));
    _renderChallengeTimer();
  } catch (e) {
    if (e.status === 404 || e.status === 410) stopChallengeTimers();
    if (!silent) toast("❌ " + e.message);
  } finally {
    challengeFrameInFlight = false;
  }
}

function onChallengeImageMove(ev) {
  const img = document.getElementById("ch-img");
  const rect = img.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const x = Math.round((ev.clientX - rect.left) * ((img.naturalWidth || 1280) / rect.width));
  const y = Math.round((ev.clientY - rect.top) * ((img.naturalHeight || 900) / rect.height));
  const badge = document.getElementById("ch-coords");
  if (badge) badge.textContent = `${x}, ${y}`;
}

async function onChallengeImageClick(ev) {
  if (!activeChallengeToken) return;
  const img = document.getElementById("ch-img");
  const rect = img.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const relX = ev.clientX - rect.left;
  const relY = ev.clientY - rect.top;
  const ripple = document.getElementById("ch-ripple");
  if (ripple) {
    ripple.style.left = relX + "px";
    ripple.style.top = relY + "px";
    ripple.style.display = "block";
    clearTimeout(window._rippleTimer);
    window._rippleTimer = setTimeout(() => { ripple.style.display = "none"; }, 900);
  }
  const x = Math.round(relX * ((img.naturalWidth || 1280) / rect.width));
  const y = Math.round(relY * ((img.naturalHeight || 900) / rect.height));
  const badge = document.getElementById("ch-coords");
  if (badge) badge.textContent = `${x}, ${y}`;
  haptic("light");
  toast(`🖱 کلیک در (${x}, ${y}) ارسال شد…`);
  try {
    await api(`/api/app/challenge/${activeChallengeToken}/action`, {method: "POST", body: JSON.stringify({action: "click", x, y})});
    setTimeout(() => refreshChallengeFrame(), 1800);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function sendChallengeText() {
  if (!activeChallengeToken) return;
  const input = document.getElementById("ch-text");
  const text = (input.value || "").trim();
  if (!text) return;
  try {
    await api(`/api/app/challenge/${activeChallengeToken}/action`, {method: "POST", body: JSON.stringify({action: "type", text})});
    input.value = "";
    toast("⌨️ متن ارسال شد");
    setTimeout(() => refreshChallengeFrame(), 1200);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function sendChallengeKey(key) {
  if (!activeChallengeToken) return;
  try {
    await api(`/api/app/challenge/${activeChallengeToken}/action`, {method: "POST", body: JSON.stringify({action: "key", key})});
    setTimeout(() => refreshChallengeFrame(), 1200);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function clickTurnstileCenter() {
  if (!activeChallengeToken) return;
  haptic("medium");
  toast("🎯 کلیک روی چک‌باکس کپچا ارسال شد…");
  try {
    await api(`/api/app/challenge/${activeChallengeToken}/action`, {method: "POST", body: JSON.stringify({action: "turnstile"})});
    setTimeout(() => refreshChallengeFrame(), 2000);
  } catch (e) {
    toast("❌ " + e.message);
  }
}

async function finishChallenge(mode) {
  if (!activeChallengeToken) return;
  haptic("success");
  try {
    await api(`/api/app/challenge/${activeChallengeToken}/action`, {
      method: "POST",
      body: JSON.stringify({action: mode, force: mode === "done" && challengeForceDone}),
    });
    activeChallengeToken = null;
    challengeForceDone = false;
    closeModals();
    toast(mode === "done" ? "✅ چالش ثبت شد و کوکی ذخیره گردید" : "❌ چالش لغو شد");
    await loadState(true);
  } catch (e) {
    if (mode === "done" && e.payload && e.payload.still_blocked) {
      challengeForceDone = true;
      await refreshChallengeFrame();
    }
    toast("❌ " + e.message);
  }
}

document.getElementById("sites-list").innerHTML = `<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>`;
loadState();
setInterval(() => { if (!currentSiteKey) loadState(true); }, 15000);
</script>
</body>
</html>
"""

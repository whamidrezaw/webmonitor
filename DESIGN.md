---
version: "2.0"
name: WebMonitor-Operational-Design-System
description: "Precision operational design system for WebMonitor — an enterprise RTL Persian + bidirectional technical website change intelligence platform (Telegram Mini App /app, standalone HTML diff reports, and live browser challenge studio). Synthesizes Linear's four-step surface ladder, Vercel's tabular metric clarity and strict interaction physics, Supabase's high-contrast semantic status polarity, and UI/UX Pro Max vector-icon & persona-adaptive ergonomics."

colors:
  dark:
    canvas: "#090d14"
    surface-1: "#111722"
    surface-2: "#171f2e"
    surface-3: "#1e293b"
    hairline: "rgba(148, 163, 184, 0.18)"
    hairline-strong: "rgba(148, 163, 184, 0.32)"
    surface-top-edge: "rgba(255, 255, 255, 0.04)"
    ink: "#f1f5f9"
    ink-muted: "#9fb0c7"
    primary: "#2563eb"
    primary-hover: "#3b82f6"
    on-primary: "#ffffff"
    link: "#7cb3ff"
    success: "#34d399"
    success-bg: "rgba(52, 211, 153, 0.14)"
    danger: "#f87171"
    danger-bg: "rgba(248, 113, 113, 0.14)"
    warn: "#fbbf24"
    warn-bg: "rgba(251, 191, 36, 0.14)"
  light:
    canvas: "#f2f5f9"
    surface-1: "#ffffff"
    surface-2: "#f8fafc"
    surface-3: "#eef2f7"
    hairline: "rgba(15, 23, 42, 0.14)"
    hairline-strong: "rgba(15, 23, 42, 0.26)"
    surface-top-edge: "rgba(255, 255, 255, 0.7)"
    ink: "#0f172a"
    ink-muted: "#4b5669"
    primary: "#1d4ed8"
    primary-hover: "#1e40af"
    on-primary: "#ffffff"
    link: "#1d4ed8"
    success: "#047857"
    success-bg: "rgba(4, 120, 87, 0.11)"
    danger: "#b91c1c"
    danger-bg: "rgba(185, 28, 28, 0.10)"
    warn: "#92400e"
    warn-bg: "rgba(180, 83, 9, 0.11)"

typography:
  sans: "Vazirmatn, system-ui, -apple-system, 'Segoe UI', Tahoma, sans-serif"
  mono: "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
  title-lg: { fontSize: "18px", fontWeight: 700, lineHeight: 1.45 }
  title-md: { fontSize: "16px", fontWeight: 700, lineHeight: 1.4 }
  card-title: { fontSize: "15px", fontWeight: 700, lineHeight: 1.45 }
  body: { fontSize: "14px", fontWeight: 400, lineHeight: 1.65 }
  label: { fontSize: "12px", fontWeight: 600, lineHeight: 1.4 }
  mono-code: { fontSize: "12.5px", fontWeight: 400, lineHeight: 1.55 }

rounded:
  xs: "4px"
  sm: "6px"
  md: "9px"
  lg: "12px"
  xl: "14px"
  sheet: "18px"
  pill: "999px"

spacing:
  xxs: "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"

motion:
  ease-out: "cubic-bezier(0.23, 1, 0.32, 1)"
  ease-drawer: "cubic-bezier(0.32, 0.72, 0, 1)"
  press-scale: "0.97"
  button-ms: "140ms"
  sheet-ms: "200ms"
---

# DESIGN.md — WebMonitor Design System

This document is the single visual and interaction contract for all WebMonitor user surfaces:
1. **Telegram Mini App & Web Dashboard (`/app`)** — [`webmonitor/miniapp_ui.py`](webmonitor/miniapp_ui.py)
2. **Standalone Interactive Diff & Evidence Viewer** — [`webmonitor/report.py`](webmonitor/report.py)
3. **Live Remote Browser Challenge Studio (`/c/{token}`)** — [`webmonitor/challenge.py`](webmonitor/challenge.py)

---

## 1. Aesthetic Direction: Operational Precision & Calm Vigilance

WebMonitor watches high-stakes targets (embassy appointment portals, Goethe exam seats, official notices). Users open it at 390px inside Telegram on phones or at 1440px on desktop when an urgent alert arrives.

- **Attention-First Hierarchy**: Failing sites, CAPTCHA challenges, selector self-healing suggestions, and layout drift appear first; healthy monitors recede quietly.
- **Surface Ladder Over Heavy Shadows**: Hierarchy is carried by four distinct surface steps (`canvas` → `surface-1` → `surface-2` → `surface-3`) with crisp 1px hairlines and a subtle top-edge highlight on dark panels—never neon glow blobs, purple AI gradients, or nested card-in-card clutter.
- **Telegram Native Harmony**: Inside Telegram WebApp, `--tg-theme-bg-color`, `--tg-theme-secondary-bg-color`, `--tg-theme-text-color`, `--tg-theme-hint-color`, and `--tg-theme-button-color` take precedence while semantic status tokens (`ok`, `warn`, `error`) adapt automatically to dark or light polarity with verified **≥ 4.5:1 WCAG AA contrast**.

---

## 2. Bidirectional RTL + Technical LTR Discipline

- Primary chrome,prose, labels, and Jalali dates flow **RTL (`lang="fa" dir="rtl"`)**.
- URLs, CSS selectors (`#main`, `.cookie-banner`), regular expressions, proxy URIs (`socks5://...`), JSON cookies, coordinates, and countdown timers enforce **`dir="ltr"`**, `spellcheck="false"`, `autocapitalize="off"`, and `unicode-bidi: plaintext` inside diff blocks so mixed Persian/German/English lines never scramble.
- All numeric counters, timers, percentages, and 7-day telemetry bars use **`font-variant-numeric: tabular-nums`** so figures never jitter on live updates.

---

## 3. Interaction Physics & Motion Rules (Emil Kowalski + Vercel Guidelines)

1. **Never `transition: all`**: Declare exact compositor-safe properties (`transform`, `opacity`, `background-color`, `border-color`).
2. **Tactile Press Feedback**: Interactive buttons respond immediately with `:active { transform: scale(0.97) }` over `140ms var(--ease-out)`.
3. **Zero Animation on Keyboard Shortcuts**: Command Palette (`Ctrl+K` / `⌘K`) and `/` search focus open and filter instantaneously (`0ms`).
4. **Origin & Entrance Discipline**: Modals and bottom sheets enter from `opacity: 0; transform: translateY(10px) scale(0.98)` (never `scale(0)`), use `overscroll-behavior: contain`, trap Escape/backdrop dismissal, and restore focus to their trigger button.
5. **Touch & Reduced Motion**:
   - All `:hover` highlights are gated behind `@media (hover: hover) and (pointer: fine)`.
   - All interactive controls set `touch-action: manipulation` and meet a **≥ 40–44px** tap target height.
   - `@media (prefers-reduced-motion: reduce)` disables shimmer and movement transitions while keeping state visibility intact.

---

## 4. Accessibility & Security Guardrails

- Every interactive element MUST be a semantic `<button>`, `<a href>`, `<input>`, `<select>`, or `<summary>`—never `<div onclick>`.
- Every custom toggle switch MUST carry `role="switch"`, `aria-checked="true|false"`, and `aria-labelledby` pointing to its visible label.
- Strict Content Security Policy (`Content-Security-Policy`: `script-src 'self' https://telegram.org 'unsafe-inline'` without `'unsafe-eval'`, `object-src 'none'`, `frame-ancestors` restricted) and zero external chart/font CDNs so every surface works fast, offline-resilient, and leak-free.

---

## 5. Unified Vector Icon System (`ui-ux-pro-max` Discipline)

- Structural UI controls (header actions, search/command/refresh toolbar, profile tabs, quick-check actions, empty states, report viewer toolbar, and challenge controls) use crisp inline 24×24 vector SVGs (`stroke="currentColor"`, `stroke-width="1.85"`, `stroke-linecap="round"`, `stroke-linejoin="round"`, `aria-hidden="true"`).
- Every icon-only button carries an explicit Persian `aria-label` and `title`.
- Semantic text diff markers (`🟢 `, `🟡 `, `🔴 `) in [`webmonitor/report.py`](webmonitor/report.py) remain plain Unicode so Telegram Bot messages and standalone HTML hunk counters stay 100% compatible.

---

## 6. Multi-Persona Progressive Disclosure

WebMonitor serves distinct user personas—from visa applicants watching a single embassy page to power operators managing dozens of portals, feeds, and JSON APIs:

1. **One-Tap Use-Case Profiles**: Both the Add-Site dialog and Per-Site Settings offer 6 calibrated domain templates (`embassy` نوبت سفارت و ویزا, `exam` ظرفیت آزمون گوته/زبان, `official` اطلاعیه دانشگاه و سازمان‌ها, `news` اخبار و رسانه, `telegram` کانال تلگرام, `price_api` موجودی/قیمت و API) that pre-configure `type`, `interval_seconds`, `alarm`, `silent`, `only_keywords`, `report_style`, `crawl_enabled`, and starter `keywords` without hiding manual overrides.
2. **Progressive Complexity**: Everyday actions (Add URL, Smart Analyze, Quick Check, Pause/Resume, Diff History) sit on the primary surface; advanced controls (CSS selectors, Exclude selectors, Regex line filters with live dry-run preview, Cookie import, Per-site SOCKS5/HTTP proxy, Watch cloning) live cleanly inside structured settings cards.

---

## 7. Real-Time Operational Workflows

- **Truthful Live Schedule Telemetry**: Cards and site overviews surface real scheduler state from `Monitor.schedule_info()` (`checking` live indicator and `next_due_in` countdown) alongside 7-day SVG change/error spark-bars.
- **Cross-Site Activity Stream**: Operators can switch the Home view between **لیست سایت‌ها** (ranked watch cards) and **جریان رویدادها** (`/api/app/events` filterable timeline across all watches with 1-tap jump to site or HTML report download).
- **Multi-Select Bulk Operations**: Activating **انتخاب گروهی** enables non-destructive multi-site selection with a sticky safe-area bottom bar (`بررسی`, `توقف`, `ادامه`, `بی‌صدا`, `حذف` via `/api/app/bulk`).
- **Explicit Theme Polarity Control**: Defaults to `auto` (following `Telegram.WebApp.colorScheme` → `--tg-theme-bg-color` luminance → OS `prefers-color-scheme`) while allowing explicit `dark` or `light` override in Global Settings.

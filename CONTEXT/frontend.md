# Frontend Dashboard — Detailed Context

## Overview

A minimal, dark-themed operator dashboard that lets a human operator trigger outbound AI broker calls. Built with plain HTML, CSS, and vanilla JavaScript, bundled with **Vite**.

---

## Stack

| Technology | Version | Role |
|---|---|---|
| HTML / CSS / JS | Vanilla | Core UI |
| Vite | ^5.0.0 | Dev server + bundler |
| Inter (Google Fonts) | — | Typography |

**Entry point:** `frontend/index.html`
**Styles:** `frontend/style.css`
**Logic:** `frontend/script.js` (loaded as ES module)

---

## UI Layout

```
┌─────────────────────────────────────────┐
│          Stock Market Voice             │  ← .project-title (gradient)
│        AUTOMATED BROKER AGENT           │  ← .project-subtitle (muted)
├─────────────────────────────────────────┤
│    [ Orchestrate ]  [ Single Call ]     │  ← .tab-bar with .tab-btn
├─────────────────────────────────────────┤
│  ┌───────────────────────────────────┐  │
│  │       Trigger All Calls           │  │  ← Orchestrate tab (.card)
│  │   [ Initiate Calls ] ←primary-btn │  │
│  └───────────────────────────────────┘  │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │       Trigger One Call            │  │  ← Single Call tab (.card)
│  │  Phone Number: [______________]   │  │
│  │  Client Name:  [______________]   │  │
│  │   [ Initiate Call ] ←primary-btn  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
         Toast notification (fixed, bottom)
```

---

## Tab Behaviour

`switchTab(tabId)` — defined in `script.js`. Removes `.active` from all `.tab-content` and `.tab-btn`, then adds `.active` to the selected tab and button.

---

## API Calls (from `script.js`)

| Button | Endpoint | Method | Payload |
|---|---|---|---|
| Initiate Calls (Orchestrate) | `/orchestrate-calls` | `POST` | `{}` |
| Initiate Call (Single) | `/test-single-call` | `POST` | `{ phone_number, client_name }` |

Responses are shown via the `.toast` notification component (success = green left border, error = red left border).

---

## Color Palette (style.css)

The entire theme is anchored to **HSL 210–215 (sky/ocean blue)**. No slate/indigo hues.

| Variable | Value | Usage |
|---|---|---|
| `--bg-color` | `#07111f` | Page background |
| `--card-bg` | `#0d2038` | Card & tab bar background |
| `--primary` | `#1a7fe8` | Buttons, active tab, focus rings |
| `--primary-hover` | `#1467c4` | Button hover state |
| `--text-main` | `#e8f4ff` | Primary text |
| `--text-muted` | `#7aa8cc` | Labels, subtitle, muted text |
| `--border-color` | `#1a3d5c` | Card & input borders |
| `--success` | `#22c55e` | Toast success border |
| `--error` | `#ef4444` | Toast error border |

**Title gradient:** `linear-gradient(135deg, #6ec6ff, #1a7fe8)` applied as `background-clip: text`.

---

## Key Design Rules

- **No framework / no Tailwind** — pure CSS variables for the design system.
- **Responsive**: max-width 480px (mobile), scales to 650px (desktop ≥768px).
- **Tab browser title:** `<title>Stock Market Voice</title>`
- **Favicon:** inline SVG emoji ₹ (Rupee symbol).
- **Font:** Inter (400, 500, 600 weights) from Google Fonts.

---

## Files Involved

| File | Role |
|---|---|
| `frontend/index.html` | HTML structure, title, favicon, font import |
| `frontend/style.css` | All styling — color palette, layout, components |
| `frontend/script.js` | Tab switching, API calls, toast notifications |
| `frontend/package.json` | `name: voice-frontend`, Vite dev/build scripts |
| `frontend/.env` | `VITE_API_URL` — backend base URL for API calls |

# Handoff: Proxmox Homelab Assistant — Web GUI

## Overview
A chat-first, mobile-friendly web GUI for a Proxmox homelab management **agent**. A Python
backend runs on a BananaPi (`192.168.0.134`), connects to a Proxmox node (`192.168.0.91`) over
SSH + the Proxmox REST API, and exposes **6 tools** the LLM calls autonomously:

`get_inventory` · `check_patches` / `apply_patches` · `check_backups` · `check_pbs` · `security_audit`

The user talks to the assistant in plain English; the agent decides which tools to run, streams the
tool calls live, and renders results (Markdown-table-style data) as cards in the conversation. The UI
is **dark, single-column, phone-readable**, and is meant to be served from the Pi with low RAM
(FastAPI + vanilla JS, no Node/React build step).

## About the Design Files
The files in this bundle are **design references created in HTML/CSS/vanilla-JS** — a working
prototype that demonstrates the intended look, layout, and interaction model. They are **not a
finished product to ship as-is**. Your task is to **recreate this design in the target environment**.

Conveniently, the intended production stack here is the *same* as the prototype's: **FastAPI serving
static HTML + vanilla JS** (a deliberate constraint — must run on a low-RAM Pi, no build step). So you
can lift the markup/CSS/JS structurally, but you must:
- Replace the simulated streaming in `assistant.js` with **real backend calls** (SSE/WebSocket stream
  from the agent loop, or chunked `fetch`).
- Replace `data.js` (static placeholder) with **live data** from the agent / `env_profile.json`.
- Wire the 6 tools to the actual Python tool implementations.

If you instead drop this into an existing framework (React/Vue/Svelte), reproduce the same screens and
behavior using that codebase's patterns and component library.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, severity system, and interactions are all
specified below and present in the CSS. Recreate pixel-faithfully. The separate
`Proxmox Assistant Wireframes.html` is **low-fidelity** and included only to show the exploration and
the A/B decisions that led here — do not implement from the wireframes.

---

## Layout Shell
A single centered **app column**, `max-width: 480px`, full viewport height (`min-height: 100dvh`),
flex-column. On screens ≤ 520px the side borders drop and it fills the width (true mobile). Three
sticky regions stacked vertically:

1. **Header** (`.hdr`, sticky top) — brand, connection/provider status, New-chat + Settings icon
   buttons, and a horizontally-scrolling **status-chip strip**.
2. **Chat stream** (`.stream`, `flex: 1`, scrolls) — the conversation. This is the only growing
   region; everything else is fixed height.
3. **Dock** (`.dock`, sticky bottom) — an optional agent-working bar, a collapsible **tool-log
   console**, the **composer** (textarea + send), and a one-line hint.

Two overlays sit outside the column: a bottom **drawer** (backup report) and a full-screen
**settings sheet**. Both are centered to `max-width: 480px` to match the column.

`viewport-fit=cover` + `env(safe-area-inset-*)` padding on header (top) and dock (bottom) handle
notches/home-indicators.

---

## Screens / Views

### 1. Welcome / First-run (Google-like landing)
- **Purpose:** zero-state entry point; pick a starter or type.
- **Layout:** centered block (`margin: auto 0`) inside the stream: 54px rounded app mark, an `<h1>`
  ("How can I help with your homelab?"), one muted line naming the node, then a vertical stack of
  **suggestion buttons** (`.suggest`, `max-width: 320px`).
- **Components:**
  - **Primary suggestion** `.sug.go` — "Run a full health check" (accent-tinted, accent glyph). Triggers
    the agentic multi-tool flow.
  - Four secondary `.sug` rows: "What's running right now?", "Any patches…", "Are my backups healthy?",
    "Run a security audit". Each: 26px rounded glyph tile, label, trailing `→`.
- **Behavior:** clicking a suggestion injects the matching user message and runs that tool/flow. The
  welcome block is removed on first message.

### 2. Conversation (chat stream)
- **Purpose:** the main surface; user prompts + agent responses + inline tool results.
- **Components:**
  - **User bubble** `.bubble.me` — right-aligned, `surface-2` bg, radius `14px 14px 4px 14px`.
  - **AI line** `.ai-line` — 27px square avatar "AI" (teal), then `.ai-body` holding any mix of:
    a streamed **tool-log block**, **result cards**, and **AI text** paragraphs.
  - **Thinking indicator** `.thinking` — three blinking dots + "reading env_profile…", shown briefly
    before a tool runs.
- **Tool-log block** `.toollog` — terminal-styled, monospace, dark `#0c0e12`. Header: pulsing accent
  dot + `[tool]` + tool signature + "running"→"done". Body: lines stream in one at a time
  (`› command` in faint, `✓ result` in green). Each line is **echoed to the dock console** too.

### 3. Inventory result (inline card)
- Card titled "Cluster inventory", `get_inventory` kicker, "10 up" ok-pill.
- Table columns: VMID · Name · Node · State · Mem · Load. Stopped rows dimmed. Shows 6 rows with a
  "Show all 11 ▾" toggle in the footer (expands/collapses).

### 4. Patch report (inline card)
- Card titled "Patch report · pve-1", warn-pill "14 pending".
- Table: Package · → Version · Type. Security rows tagged with an accent "security" `.sevtag`,
  routine rows faint.
- Footer actions: **Apply security (3)** (primary), **Apply all (14)** (ghost), **Dry run** (ghost).
- **Apply behavior:** footer swaps to a "applying…" thinking row; the dock console auto-expands and
  streams per-package `✓ pkg unpacked & configured` lines, then `✓ done · no reboot required`; the
  card pill flips to ok "applied" and the footer shows a success pill. The Patches **status chip**
  updates to "up to date".

### 5. Backup report (DRAWER — slides up over chat)
- Triggered by the backups flow ("Open report ▸" button + auto-opens). Bottom sheet, `max-height:
  86dvh`, slides from `translateY(100%)` to `0` over `.26s cubic-bezier(.22,.9,.3,1)`; dimmed scrim
  behind. Grab handle + "Backup health" title + ✕.
- **Body:** two **mini stat cards** (Coverage `9 / 11` + warn pill; PBS `61%` with a progress bar +
  "GC ok · passed" pill), then a table: VMID · Name · Last backup · Size · Status (fresh/stale/overdue
  with colored dots).
- **Footer:** "Back up stale (2)" primary + "Close" ghost.

### 6. Security findings (inline card)
- Card "Findings", `security_audit` kicker, bad-pill "score B+".
- **Severity = icon + colored label + text** (the chosen system — readable without relying on color
  alone). Each finding `.finding`: a 28px glyph tile (`▲` critical / `●` high / `◆` medium / `○` low,
  color-coded bg+border), an uppercase severity `.sevtag`, bold title, monospace "where" location,
  detail line, and an "Ask agent to fix ▸" button. Findings are sorted critical→low.

### 7. Agentic full health check (autonomous multi-tool loop)
- The headline "agentic" interaction. Triggered by the primary suggestion or phrases like "full
  check", "health check", "status report".
- The agent posts a short intent line, then an **agent-plan card** `.agentplan`: header "Agent plan ·
  full health check" with a live `n / 4` progress counter, and 4 step rows
  (`get_inventory` → `check_patches` → `check_backups` → `security_audit`).
- It runs the four tools **in sequence, autonomously**: each step row goes `pending` (numbered box) →
  `active` (spinning accent box, "Agent running · tool() · step n/4" shown in the **agent-working bar**
  above the composer) → `done` (green ✓ + a result meta like "2 stale" with a status dot). Every call
  streams to the dock console.
- On completion: the working bar disappears and a **consolidated summary card** "Recommended actions"
  appears — the 3 prioritized issues (critical root SSH, high patches, medium stale backups) each with
  a one-tap action button, plus ok-pills ("10/11 VMs healthy", "PBS verified"). Action buttons open the
  relevant flow (backups → drawer) or toast a drafted fix.

### 8. Settings (full-screen sheet)
- Opened via the gear icon; fades/slides in.
- **LLM provider** — a 3-way **segmented control** (Claude / OpenAI / Ollama), each showing the model
  name. Selecting one updates the provider-specific field group (API key/host, model, tokens/context),
  the header status label, and a live **`.env` preview** block.
- **Connection** — fields for `PROXMOX_HOST`, `SSH_USER`, `PBS_HOST`, `AGENT_BIND`.
- **.env preview** — monospace block mirroring what the Pi reads.
- **Save & reload agent** primary button → toast "Saved · agent reloaded env_profile", closes sheet.

### Dock console (ambient, every screen)
- Collapsible terminal strip pinned above the composer. Header: pulsing dot + "tool log" + call count
  badge + chevron. Body (max-height 96px, scrolls) shows timestamped `[tool] …()`, `› command`, and
  `✓ result` lines as the agent works. Starts collapsed with an "idle — waiting for a prompt" line.

---

## Interactions & Behavior
- **Routing:** `classify(text)` keyword-matches the prompt to one of `checkup | patches | backups |
  inventory | security | fallback`. In production, this is the LLM tool-choice — keep the same
  rendering targets.
- **Streaming:** `streamLog()` reveals tool-log lines on `~420–620ms` delays and mirrors them to the
  console; `aiText()` appends summary paragraphs. Replace these timers with real stream chunks.
- **Send:** Enter submits, Shift+Enter newlines; textarea auto-grows to 120px; send button disabled
  when empty or while the agent is busy (`state.busy`).
- **Drawer:** open via button/auto; close via scrim tap, ✕, or "Close". Transform-based slide.
- **Settings sheet / toast:** opacity+translate transitions (`.2s`). Toast auto-hides after 2.6s.
- **Auto-scroll:** stream scrolls to bottom on each append (`requestAnimationFrame`).
- **Responsive:** single column always; ≤520px fills width, bumps base font to 15.5px, enlarges
  suggestions and tap targets. Tables get horizontal scroll (`.card-body{overflow-x:auto}`) so 6-column
  tables never overflow a 360px phone. Send button 44px, icon buttons 38px (touch-friendly).

## State Management
- `state = { provider, busy, started, calls }` — current LLM provider, whether the agent is mid-run
  (locks input), whether the welcome has been cleared, and the running tool-call count (console badge).
- A fake monotonic `clock` generates plausible timestamps — replace with real server time.
- Per-flow local state: inventory "show all" toggle, patch "applied" status, plan step progress.
- **Data fetching (production):** stream the agent loop from the backend (tool-call events → render a
  tool-log block; tool-result events → render the matching card; assistant tokens → `aiText`). Load
  initial dashboard chips from `env_profile.json`. `apply_patches` and any write action must confirm
  before executing (the UI already frames actions as "ask first").

## Design Tokens
All defined as CSS variables in `assistant.css :root`.

**Colors**
- Backgrounds: page `--bg #0e1014`, app column `--app #12151b`, surfaces `--surface #171b22`,
  `--surface-2 #1d222b`, `--surface-3 #232934`.
- Lines/borders: `--line #262d38`, `--line-2 #313a47`.
- Text: `--text #e7eaef`, `--text-2 #b3bccb`, `--muted #7d8799`, `--faint #5a6373`.
- Accent (amber): `--accent #f0883e`, on-accent ink `--accent-ink #1a1206`, soft
  `--accent-soft rgba(240,136,62,.14)`.
- Status: `--ok #56c08d`, `--warn #e3b341`, `--crit #e8625a`, `--info #5b9cf0`, AI accent `--ai #58c2b0`
  (each with a matching `*-soft` rgba at ~.14 alpha).
- Terminal/console surface: `#0c0e12` / `#0a0c0f`.

**Typography**
- UI sans: **Hanken Grotesk** (400/500/600/700). Mono: **Spline Sans Mono** (400/500/700). Both Google
  Fonts. Base body 15px / line-height 1.5.
- Sizes: h1 21px/600; bubble & ai-text 14px; card title 13px/600; table 12.5px (mono cells 11.5px);
  kickers 10px uppercase letter-spacing .7px; severity tags 9.5px uppercase 700; console 11px mono.

**Radius:** `--r 14px`, `--r-sm 10px`, `--r-lg 20px`; bubbles 14px (one corner 4px); pills 20px; full
circles for the send button & dots.

**Shadow:** `--shadow 0 18px 50px -20px rgba(0,0,0,.7)` (app column + overlays).

**Spacing:** stream gap 14px; card padding ~11–13px; chip strip gap 7px; dock padding 8/14px + safe-area.

**Motion:** fades `.2–.4s ease`; drawer `.26s cubic-bezier(.22,.9,.3,1)`; status-dot `pulse` 1.8s;
thinking-dot `blink` 1.4s; active-step `spin` 1s linear; caret `caret` 1s step-end.

## Assets
No raster/image assets. The app "logo" is the unicode glyph **◈**; tool/severity glyphs are unicode
(`▤ ⬇ ⛁ ⚿ ◆ ▲ ● ◆ ○ ✓ ➜ →`). Swap for your icon set (e.g. Lucide/Phosphor) if preferred — sizes and
tiles are specified above. Fonts load from Google Fonts (self-host for an offline Pi).

## Files
In this bundle (and in the project root):
- `Proxmox Assistant.html` — **hifi prototype** shell (header, stream, dock, drawer, settings sheet).
- `assistant.css` — all hifi styles + tokens (`:root`), responsive rules, animations.
- `assistant.js` — chat routing, simulated tool streaming, all 6 tool renderers, the agentic checkup
  loop, drawer, settings, console, toast. **The file to gut + rewire to the real backend.**
- `data.js` — placeholder `env_profile`-shaped data + tool outputs. **Replace with live data.**
- `Proxmox Assistant Wireframes.html` + `wireframe.css` — **lofi** A/B exploration, reference only.

### Implementation notes
- Per-screen direction chosen during design: Home = ambient console strip (ops feel); Chat/Inventory/
  Patches/Security = inline cards; **Backups = drawer**. Keep these.
- Keep it buildless and light (Pi/low-RAM constraint): static files from FastAPI, no bundler.
- Treat all tool *data* as untrusted display content — escape before injecting (the prototype's
  `esc()` shows the intent).

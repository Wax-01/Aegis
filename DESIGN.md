---
version: alpha
name: "AegisVolt · Línea de carga"
description: "Operations console where every charge is a trip on a transit line: the environment is the line, each SAGA step a station, and a failure opens a red return branch through the compensations."
colors:
  ink: "#1b1f3b"
  ink-2: "#3a4060"
  ink-3: "#555c7c"
  ink-4: "#8a90a6"
  rule: "#dadde6"
  rule-2: "#eef0f4"
  ground: "#ffffff"
  ground-2: "#f6f7fa"
  line: "#0072ce"
  line-dev: "#0072ce"
  line-test: "#7a4fbf"
  line-prod: "#00838f"
  line-fallback: "#596080"
  ok: "#00965e"
  ok-ink: "#00754a"
  bad: "#d52b1e"
  bad-ink: "#b3241a"
  bad-wash: "#fdeeed"
  run: "#f2b705"
  run-ink: "#7d5c00"
  run-wash: "#fff6dc"
typography:
  body:
    fontFamily: "Archivo Variable, Archivo, system-ui, sans-serif"
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tabular-nums"
  headline-lg:
    fontFamily: "Archivo Variable"
    fontSize: 30px
    fontWeight: 750
    lineHeight: 1.15
    letterSpacing: -0.015em
    fontStretch: 87.5%
  headline-md:
    fontFamily: "Archivo Variable"
    fontSize: 19px
    fontWeight: 700
    lineHeight: 1.15
    fontStretch: 87.5%
  headline-sm:
    fontFamily: "Archivo Variable"
    fontSize: 15px
    fontWeight: 700
    lineHeight: 1.15
    fontStretch: 87.5%
  station-name:
    fontFamily: "Archivo Variable"
    fontSize: 22px
    fontWeight: 750
    letterSpacing: -0.01em
    fontStretch: 87.5%
  figure-lg:
    fontFamily: "Archivo Variable"
    fontSize: 26px
    fontWeight: 700
    fontStretch: 87.5%
  label:
    fontFamily: "Archivo Variable"
    fontSize: 13px
    fontWeight: 600
  caption:
    fontFamily: "Archivo Variable"
    fontSize: 12px
    fontWeight: 600
    letterSpacing: 0.02em
  serial:
    fontFamily: "Archivo Variable"
    fontSize: 13px
    fontWeight: 600
    letterSpacing: 0.04em
rounded:
  xs: 4px
  sm: 8px
  md: 10px
  lg: 12px
  xl: 14px
  chip: 17px
  connector: 18px
  pill: 999px
  dot: 50%
spacing:
  s1: 4px
  s2: 8px
  s3: 12px
  s4: 16px
  s5: 24px
  s6: 32px
  s7: 48px
components:
  shell-header:
    backgroundColor: "{colors.ink}"
    textColor: "#ffffff"
    height: 64px
  roundel:
    backgroundColor: "{colors.line}"
    textColor: "#ffffff"
    rounded: "{rounded.dot}"
    size: 36px
  tab:
    textColor: "#c4c8dc"
    typography: "{typography.body}"
  tab-active:
    textColor: "#ffffff"
  button-primary:
    backgroundColor: "{colors.line}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    height: 44px
    padding: "0 24px"
  button-quiet:
    backgroundColor: "#ffffff"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    height: 36px
    padding: "0 16px"
  field-input:
    backgroundColor: "#ffffff"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    height: 44px
    padding: "0 12px"
  connector-chip:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    rounded: "{rounded.connector}"
    height: 32px
    padding: "4px 10px"
  connector-chip-faulted:
    backgroundColor: "{colors.bad-wash}"
  filter-chip:
    backgroundColor: "#ffffff"
    textColor: "{colors.ink}"
    rounded: "{rounded.chip}"
    height: 34px
    padding: "0 12px"
  filter-chip-pressed:
    backgroundColor: "{colors.ink}"
    textColor: "#ffffff"
  pill-state-on:
    backgroundColor: "{colors.ink}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
  pill-state-off:
    backgroundColor: "{colors.rule-2}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
  charge-form:
    backgroundColor: "{colors.ground-2}"
    rounded: "{rounded.xl}"
    padding: 24px
  failure-note:
    backgroundColor: "{colors.bad-wash}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
  recover-banner:
    backgroundColor: "{colors.run-wash}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
  train-marker:
    backgroundColor: "{colors.ink}"
    textColor: "#ffffff"
    rounded: "{rounded.lg}"
    size: 38px
  stop-dot:
    backgroundColor: "#ffffff"
    rounded: "{rounded.dot}"
    size: 30px
  switch:
    backgroundColor: "{colors.line}"
    rounded: 13px
    width: 48px
    height: 26px
---

# AegisVolt · Línea de carga

## Overview

**Thesis.** A charge is a trip on a transit line. The console borrows the grammar of Latin American metro maps (Santiago Metro, TransMilenio): the deployed environment *is* a line with its own colour, each SAGA step is a station, the live run is a train marker that travels the line, and a failure opens a **red return branch** (*Ramal de retorno · compensaciones*) that runs back underneath the main line through Reembolso and Liberación.

It deliberately refuses the default SaaS dashboard: no KPI card grid, no gradient hero, no status-pill soup. Information sits on a white ground, separated by hairline rules, with one dark navy shell band on top and one saturated line colour doing all the identity work.

**Personality:** wayfinding signage. Flat, thick, high-contrast, legible at a distance (the console is demoed over a shared screen). Semi-condensed Archivo headlines read like station nameplates; tabular numerals keep money, kWh and times aligned.

**The environment is always obvious** (Product Principle 2). At boot `App.tsx` writes the environment's colour into `--line` on `:root`, so the header underline, roundel, the run track, primary button, focus ring, selection tint, meter, switches and timeline all re-tint per deployment. Dev never looks like prod.

**Failure is a first-class state** (Principle 4). Red is reserved for the return branch and for failures; it is drawn with the same weight (12 px track, full stop dots) as success, never as a small badge.

Copy is Spanish throughout (`lang="es"`); numbers use the `es-CO` locale.

## Colors

All colour lives as custom properties on `:root` in `frontend/src/styles.css`. The palette is light-only (`color-scheme: light`); there is no dark mode.

### Neutrals (navy-tinted ink ramp)

| Token | Value | Role |
|---|---|---|
| `--ink` | `#1b1f3b` | Navy shell band, primary text, train marker, pressed chips, ON pills, flag-matrix header rule. Also `<meta name="theme-color">`. |
| `--ink-2` | `#3a4060` | Secondary text: field labels, stop details, quotes, `code`. |
| `--ink-3` | `#555c7c` | Muted text: captions, city names, table headers, pending station names. |
| `--ink-4` | `#8a90a6` | Faintest text (return-branch label), offline connector dot. |
| `--rule` | `#dadde6` | Hairlines, unreached track, unreached stop-dot border, scrollbar thumb. |
| `--rule-2` | `#eef0f4` | Row separators, skeleton blocks, meter trough, OFF pill. |
| `--ground` | `#ffffff` | Page ground. |
| `--ground-2` | `#f6f7fa` | Stations rail, launch form panel, row hover. |

Un-tokenized literals that appear in the code and are part of the world: `#c4c8dc` (secondary text and inactive tabs on the navy shell), `#c5cad8` (input / quiet button / filter chip border, switch off track), `#f2c2be` (faulted connector border), `#3ddc97` (connected "En vivo" dot on navy), `#ffffff` (on-colour text, stop-dot fill, roundel halo).

### Environment lines (identity)

Defined in `frontend/src/config.ts` (`LINE`), applied to `--line` at runtime. Each environment is a line with a colour, a letter (for the roundel) and a Spanish label.

| Env | Colour | Letter | Label |
|---|---|---|---|
| dev | `#0072CE` (blue) | D | Desarrollo |
| test | `#7A4FBF` (violet) | T | Pruebas |
| prod | `#00838F` (teal) | P | Producción |
| unknown | `#596080` | first letter | env name |

`--line` defaults to `#0072ce` in CSS. Derived tints are computed with `color-mix(in srgb, var(--line) N%, white)`: 6% (current env column in the flag matrix), 8% (active history row), 9% / 40% (charging connector fill / border), 22% (text selection, empty-state track). Hover on the primary button darkens with `color-mix(… 82%, black)`.

### Signal colours

Each signal has a saturated mark colour, a darker `-ink` for text on white, and (where needed) a `-wash` background.

| Signal | Mark | Text | Wash | Meaning |
|---|---|---|---|---|
| ok | `--ok #00965e` | `--ok-ink #00754a` | — | Available connector, healthy service, Completada, refunds in the ledger. |
| bad | `--bad #d52b1e` | `--bad-ink #b3241a` | `--bad-wash #fdeeed` | The return branch, failed stations, faulted connectors, compensated / failed SAGAs, warnings. |
| run | `--run #f2b705` | `--run-ink #7d5c00` | `--run-wash #fff6dc` | In progress: reserved connector, current station pulse, in-flight SAGA, surge note, admin-token and recovery panels. |

Rules: red never decorates; amber is "moving", never "warning" (warnings are red ink). The line colour, not green, marks a completed station: green is reserved for "free / healthy".

## Typography

One family: **Archivo Variable** loaded with its width axis (`@fontsource-variable/archivo/wdth.css`), stack `"Archivo Variable", "Archivo", system-ui, sans-serif` (`--font`). `code` also uses Archivo (weight 600), not a monospace.

- **Semi-condensed display.** All `h1–h3`, station names, the brand wordmark, roundel letters, big figures and money totals use `font-stretch: var(--narrow)` (87.5%). Body text stays at normal width.
- **Tabular numerals everywhere** (`font-variant-numeric: tabular-nums` on `body`).
- Heavy weights are the voice: 750 for nameplates and totals, 700 for headings, 650 for status labels, 600 for labels and captions. Intermediate variable weights (650, 750) are intentional.
- Headings use `text-wrap: balance`, line-height 1.15.

| Role | Size / weight | Notes |
|---|---|---|
| Body | 15px / 400, lh 1.45 | |
| h1 (trip title, view title) | 30px / 750, -0.015em, narrow | 24px under 720px |
| h2 (section) | 19px / 700, narrow | |
| h3 | 15px / 700, narrow | |
| Brand wordmark | 20px / 750, -0.01em, narrow | |
| Main station name (LineDiagram) | 22px / 750, -0.01em, narrow | 17px in containers ≤760px, 15px ≤520px |
| Return station name | 17px / 700, narrow, `--bad-ink` | |
| Session figures | 26px / 700, narrow | units in 14px / 500 `--ink-3` |
| Quote total | 24px / 750, narrow | |
| Wallet balance | 20px / 750, narrow | |
| Env head (flag matrix) | 18px / 750, narrow | |
| Station name (rail) | 16px / 700, narrow | |
| Status label | 14px / 650 | |
| Label / field label | 13px / 600 | |
| Serial (correlation id, short id) | 13px / 600, +0.04em | |
| Caption / service name | 12px / 600, +0.02–0.03em | |
| Pill state | 12px / 750, +0.04em | |

## Layout

- **Spacing scale** `--s1…--s7`: 4, 8, 12, 16, 24, 32, 48 px. Odd values (2, 6, 10 px) appear only inside chips and dense rows.
- **Shell:** sticky 64px navy header (roundel + "AegisVolt / Línea {env} · {label}", tabs Operación / Transacciones / Feature flags / Salud, "En vivo" status at the far right). A 4px inset underline in `--line` runs the full width of the header: the line itself.
- **Operación:** `340px | 1fr` grid. Left rail (`--ground-2`, sticky, scrolls independently) lists stations with connector chips in a 2-column grid; stations with a faulted connector sort first. Main column (`.work`, padding 24/32/48): trip title → LineDiagram (340px tall, 200px when settled without compensations) → failure note → session strip → launch form panel → "Últimos recorridos" table.
- **Transacciones / Salud:** `.work-split` grid `1.25fr | 1fr`, the right column a sticky `.detail` panel separated by a 1px rule.
- **Feature flags:** a full-width matrix (flag × env), the connected env's column tinted with 6% line colour, header underlined with a 2px `--ink` rule.
- **Breakpoints:** ≤1180px detail panel stacks under the list, form becomes 2 columns; ≤960px rail stops being sticky and becomes an auto-fill grid of stations above the work area; ≤720px header wraps with tabs on their own 44px row, form becomes 1 column, history rows become a two-line grid with the MiniLine on the left, the Salud service line turns vertical.
- **Container queries** on `.line-diagram` (`container-type: inline-size`): ≤760px hides main stop details and shrinks names; ≤520px also hides service names and return details.
- Reading measure capped with `max-width` in `ch` (52–90ch) for notes and prose.

## Elevation & Depth

Flat. Depth comes from rules and colour bands, not shadows. The only shadows in the system:

- Header: `inset 0 -4px 0 var(--line)` (the line underline, not a shadow in spirit).
- Roundel halo: `0 0 0 2px #fff`.
- Selected connector ring: `0 0 0 2px var(--line)`.
- Train marker: `0 6px 14px -4px rgb(27 31 59 / 0.5)`, the one object that floats, because it moves.
- Switch knob: `0 1px 3px rgb(27 31 59 / 0.3)`.
- Current station pulse: animated `box-shadow` ring in 60% amber fading to 14px.

No cards with drop shadows. Grouping is by `--ground-2` panels (rail, launch form) or tinted washes (failure, recovery, token form).

## Shapes

- **Round** for anything that is a station or a state: stop dots, connector dots, status dots, timeline dots, service dots, roundels (`50%`).
- **Thick flat tracks with round caps**: 12px strokes on the large diagram, 3px on MiniLine, 10px bar on the Salud service line, 4px timeline spine. Corners of the return branch use round joins.
- **Capsules** for interactive chips: connector chips (18px radius), filter chips (17px), ON/OFF pills (999px), switch track (13px).
- **Soft rectangles** for controls and panels: inputs and buttons 8px, washes 10px, train marker 12px, launch form 14px, skeleton blocks 4px.
- Focus: 3px solid `--line` outline, 2px offset (white on the navy shell, inset on table rows).

## Components

### LineDiagram (signature)
`components/LineDiagram.tsx` + `saga-model.ts`. The SAGA drawn as a metro line in a `viewBox 0 0 100 320` SVG stretched to width (`preserveAspectRatio="none"`, `vector-effect: non-scaling-stroke`), with HTML stops positioned on top in percentages.
- Four main stations at x = 7 / 35 / 63 / 91 %, y = 116: **Reserva** (station-reservation), **Cobro** (billing-wallet), **Activación** (energy-dispatch), **Carga** (energy-dispatch, the physical session). Name above the track, service below the name, detail text below the dot (clamped to 3 lines; error code in bold `--bad-ink`).
- `track-base` in `--rule`; `track-run` in `--line` grows to the reached station (`x2` transition 700ms ease-out).
- A dotted **ghost return branch** (`--rule`, 3px, dash 1/9) is always drawn so the viewer knows a way back exists; it hides once a trip settles cleanly.
- On compensation the **return branch** (`--bad`, 12px) drops from the failed/last station down to y = 246 and runs left; it *draws itself* via `pathLength=1` and `stroke-dashoffset` (900ms ease-out) proportional to compensations executed. Return stops (Aborto / Reembolso / Liberación) sit under the station they undo: 26px white dots with 5px red border, filled red when done, navy fill when the compensation itself failed.
- Stop states: pending (white, `--rule` border), current (amber border, pulsing ring), done (filled `--line`, white check), failed (filled `--bad`, white X).
- **Train marker:** 38px navy rounded square with a lucide `TrainFront` icon and a white 3px border; travels with `left 750ms / top 450ms` ease-out, turns `--bad-ink` when the trip failed and rides the return branch.
- Accessible as `role="img"` with a full Spanish `aria-label` describing every station and compensation.

### MiniLine
`components/MiniLine.tsx`. An 84×26 SVG miniature of the same grammar for history rows: 3px tracks, 3.6px stop dots, the red return branch underneath. Lets a column of trips be scanned for "which ones came back".

### Roundel
`Roundel` in `Header.tsx`. Circle in the environment's line colour with its white letter (D / T / P), 800 weight, narrow, white 2px halo. Size 36 in the header, 26 in the flag matrix heads; letter at 44% of the size.

### Shell header and tabs
Navy band, 64px, sticky. Tabs are bare text buttons (`#c4c8dc`, white on hover/current) with a 4px white bar under the current tab sitting on the line-coloured underline. "En vivo" with a blinking green dot; amber dot and "Reconectando…" when the socket drops.

### Stations rail and connector chips
Legend (Libre green / Reservado amber / Cargando line colour, blinking / En falla red) above the list. Each connector is a capsule button: status dot, short id (C1…) bold, tier + kW (or live kW · SoC %) right-aligned. Selected = line-colour ring; charging = 9% line wash; faulted = `--bad-wash` with `#f2c2be` border; non-free chips are disabled. Skeleton chips while loading.

### Launch form (charge-form)
`--ground-2` panel, 14px radius, 4-column grid (Flota / Vehículo / Conector / Energía), then the fast-charge checkbox (accent `--line`) and the live quote right-aligned (tier rate × kWh, surge note in `--run-ink`, total 24/750). Primary button "Reservar y activar" with lucide `Zap`, min 240px. Inline red-ink warnings for insufficient balance, ULTRA without boost, and an active hardware-fault flag.

### Buttons
- `btn-primary`: `--line` fill, white 16px/700, 44px, 8px radius; darkens 18% on hover; 1px press-down; 55% opacity when disabled.
- `btn-quiet`: white, `#c5cad8` border → `--ink` on hover, 36px, 14px text.
- `btn-link`: ink text, underline in `--line` at 3px offset.

### Status label
`SagaStatusLabel`: 10px dot (currentColor) + 14px/650 Spanish label. Tones: ok (Completada), run (Iniciada, Conector reservado, Pago capturado — amber dot blinking), warn (Compensando — red, blinking), bad (Compensada, Fallida, Compensación fallida). Text only, no filled pill.

### Trips table
Hairline table, 14px; headers 13/600 `--ink-3`; first column is the MiniLine; serial short ids; right-aligned money; hover `--ground-2`; active row 8% line wash; rows keyboard-focusable. Collapses to a two-line grid on mobile.

### Transaction detail and timeline
Sticky detail panel with facts grid (3 cols), a LineDiagram replay, a recovery banner (`--run-wash`, lucide `RotateCcw`) for recoverable SAGAs, then a vertical timeline: 72px time column, 18px dots on a 4px spine in `--line`; compensation entries switch the spine to `--bad` and use red-ring dots. Wallet movements table with refunds in `--ok-ink`.

### Feature-flag matrix
Flag × environment table; each column head carries a roundel and env name (18/750 narrow). The connected env shows a working switch (48×26, track `--line` when on, `#c5cad8` off, knob slides 22px); other envs show solid ON/OFF pills when reachable or ghost outline pills for the expected policy when not. Divergence from policy is called out in red ink. Admin token requested in an amber-wash inline form (lucide `KeyRound`).

### Salud service line
Services drawn as three stations on a 10px line-coloured bar (30px white dots with 7px green ring, solid red when down); turns vertical on mobile. Wallet list with 20/750 balances, red when low (<20).

### Washes
`failure-note` (`--bad-wash`, lucide `TriangleAlert` in `--bad`), `recover` and `token-form` (`--run-wash`), 10px radius, no border.

## Motion

- Easing token `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)` for everything that travels (track growth 700ms, return branch draw 900ms, train 750/450ms, switch knob 220ms).
- UI feedback 120–200ms `ease` (colours, borders, button press); state dots 300ms.
- Meter fill `width 1.8s linear` (energy delivered).
- Loops: `blink` (opacity to 0.35) at 2.4s for "En vivo", 1.6s for charging connectors, 1s for in-flight/compensating status; `pulse` 1.4s ring on the current station.
- `prefers-reduced-motion: reduce` collapses all animations and transitions to 0.01ms.

## Iconography

lucide-react only, stroke icons at 13–18px: `TrainFront` (train), `Check` / `X` (stop outcomes, stroke 3), `Zap` (launch), `Square` (stop charge), `TriangleAlert` (failures/warnings), `RotateCcw` (recover), `KeyRound` (admin token), `Plus` (top-up). Decorative icons are `aria-hidden`.

## Do's and Don'ts

**Do**
- Drive every identity surface from `--line`; set it once from `config.ts` `LINE` and let `color-mix` derive tints.
- Draw a SAGA, anywhere it appears, with the line grammar: stations, run track, return branch underneath (LineDiagram large, MiniLine small, timeline vertical).
- Keep red for the return branch and failures, amber for "in motion", green for "free / healthy", the line colour for "done on this line".
- Use Archivo semi-condensed (87.5%) and heavy weights for nameplates and figures; keep tabular numerals.
- Separate with hairline rules and `--ground-2` panels; keep the ground white.
- Write UI copy in Spanish and give every diagram a full spoken `aria-label`.

**Don't**
- Don't introduce KPI card grids, drop-shadowed cards, gradients or glassmorphism.
- Don't use green to mean "step completed" on the line, or red as an accent.
- Don't add a second typeface or a monospace; serials are Archivo 600 with letter-spacing.
- Don't hard-code an environment colour in a component; read it from `LINE` / `--line`.
- Don't render status as filled coloured pills in tables; use the dot + coloured text label.
- Don't hide a compensation: if a step ran, its undo appears on the return branch.

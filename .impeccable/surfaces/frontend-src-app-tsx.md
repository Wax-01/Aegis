---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: []
---

## Scope

AegisVolt operations console (React + Vite SPA in `frontend/`), mode: Operate. One environment per deployment (dev/test/prod), chosen at runtime by `/config.js`.

## Audience and task

Fleet operator and platform engineer, same person, laptop or shared screen. Tasks: watch connectors live, start a charge (SAGA) and follow every step and compensation, compare feature flags across environments, inspect and recover transactions. Required panels: live stations/connectors, SAGA trigger flow, per-environment flag visualizer, transaction/compensation history.

## Direction contract

THESIS: A charge is a trip on a transit line. Each SAGA step is a station; a failure opens a red return branch that runs back through the compensations. Refuses the default SaaS dashboard of KPI cards and status pills.

OWN-WORLD: Santiago Metro and TransMilenio line diagrams. White ground, navy #1B1F3B shell, each environment owns a line colour (dev #0072CE, test #7A4FBF, prod #00838F) shown as a roundel with its letter. Return/failure red #D52B1E, success green #00965E, in-progress amber #F2B705. Archivo (semi-condensed headings, tabular numerals), thick flat lines, round station dots, lucide icons.

STORY: The visitor sees which line (environment) they are on, picks a free connector, launches a charge and watches the train move station to station; on failure they watch the return branch refund and release. They then find that trip in the history and can compare flags across lines.

FIRST VIEWPORT: Navy header (roundel, AegisVolt, environment, tabs Operación / Transacciones / Feature flags / Salud). Left 360px rail: stations with connector dots, live. Main: the charge title, the line diagram large (3 stations + return branch), the launch form below it, recent trips table under that.

FORM: Pick card, position 1 of the grounded list. seed:f44f267dd6f7b394. Signature interaction: the live train marker travelling the line and the return branch drawing itself on compensation; history rows carry a miniature of the same line.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

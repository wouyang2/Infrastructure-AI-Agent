---
name: Infrastructure AI Agent
description: A corridor command workspace for durable bridge inspection runs and traceable engineering decisions.
colors:
  mist-paper: "#e8ece8"
  working-surface: "#fbfcfa"
  muted-surface: "#f1f4f1"
  white-surface: "#ffffff"
  route-ink: "#18231f"
  secondary-ink: "#52615b"
  tertiary-ink: "#74817b"
  corridor-rail: "#0d2e29"
  corridor-rail-deep: "#08231f"
  rail-text: "#f4f7f5"
  rail-muted: "#aac0b8"
  route-teal: "#176b62"
  action-teal: "#248e7e"
  teal-signal: "#dcebe6"
  work-amber: "#d79a24"
  amber-signal: "#fff2d5"
  failure-red: "#b64a48"
  red-signal: "#f9e4e2"
  divider: "#cfd7d2"
  divider-strong: "#aebbb4"
typography:
  workspace-title:
    fontFamily: "Avenir Next, Avenir, sans-serif"
    fontSize: "21px"
    fontWeight: 700
    lineHeight: 1.2
  report-title:
    fontFamily: "Georgia, Times New Roman, serif"
    fontSize: "28px"
    fontWeight: 600
  section-title:
    fontFamily: "Avenir Next, Avenir, sans-serif"
    fontSize: "13px"
    fontWeight: 700
  body:
    fontFamily: "Avenir Next, Avenir, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Avenir Next, Avenir, sans-serif"
    fontSize: "11px"
    fontWeight: 700
  micro:
    fontFamily: "Avenir Next, Avenir, sans-serif"
    fontSize: "10px"
    fontWeight: 600
  route-detail:
    fontFamily: "Avenir Next, Avenir, sans-serif"
    fontSize: "9px"
    fontWeight: 400
rounded:
  xs: "4px"
  sm: "6px"
  md: "10px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  compact: "10px"
  md: "14px"
  lg: "20px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.action-teal}"
    textColor: "{colors.white-surface}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "8px 15px"
    height: "38px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.route-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.xs}"
    padding: "7px 11px"
    height: "36px"
  input:
    backgroundColor: "{colors.white-surface}"
    textColor: "{colors.route-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.xs}"
    padding: "8px 10px"
    height: "38px"
  status-chip:
    backgroundColor: "{colors.muted-surface}"
    textColor: "{colors.secondary-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "5px 9px"
---

# Design System: Infrastructure AI Agent

## Overview

**Creative North Star: "Corridor Command Map"**

The interface treats each inspection as a durable point moving through an infrastructure operations route. A dark run ledger keeps concurrent and historical work visible; a pale technical workspace gives one selected case enough room for evidence, retrieval, planning, scheduling, review, and reporting.

The system is compact, calm, and operational. Its identity comes from topology, thin route lines, status signals, and precise information hierarchy rather than decorative imagery. It deliberately avoids the stacked demo dashboard and keeps the intake form in a slide-over drawer so results remain the primary working surface.

**Key Characteristics:**

- Persistent dark run ledger paired with a pale selected-case workspace.
- Seven-stage horizontal route connecting intake through report.
- One result domain visible at a time through accessible tabs.
- Restrained teal, amber, and red used only for actual workflow state.
- Formal reports rendered on a separate white document surface.

## Colors

The palette combines mist-gray engineering paper with a deep green route ledger. Teal communicates completion and primary action, amber marks work in progress, and red is reserved for failure or rejection.

### Primary

- **Route Teal** (`#176b62`): completed route nodes, active tabs, confidence bars, and selected operational text.
- **Action Teal** (`#248e7e`): the New inspection and Run Inspection commands.

### Secondary

- **Work-Zone Amber** (`#d79a24`): active workflow stages, queued run dots, and scheduling attention.
- **Failure Red** (`#b64a48`): failed workflows, export errors, and rejection actions.

### Neutral

- **Mist Paper** (`#e8ece8`): the result workspace ground.
- **Working Surface** (`#fbfcfa`): the selected case shell.
- **White Surface** (`#ffffff`): data sections, controls, and formal documents.
- **Route Ink** (`#18231f`): primary text.
- **Corridor Rail** (`#0d2e29`): persistent run navigation.
- **Divider** (`#cfd7d2`): section and table rules.

**The Signal Color Rule.** Teal, amber, and red must communicate a real action or state. Neutral content remains neutral.

## Typography

**Display Font:** Avenir Next with Avenir and sans-serif fallback  
**Body Font:** Avenir Next with Avenir and sans-serif fallback  
**Report Font:** Georgia with Times New Roman fallback for formal report titles only

**Character:** The workspace uses a compact humanist sans with clear numerals and a restrained weight range. The report title switches to a conventional document serif to separate exported engineering records from the live console.

### Hierarchy

- **Workspace Title** (`700`, `21px`, `1.2`): selected asset name.
- **Report Title** (`600`, `28px`): formal inspection document title only.
- **Section Title** (`700`, `13px`): result sections and operational blocks.
- **Body** (`400`, `14px`, `1.45`): form values and narrative content; prose should stay within `72ch` where practical.
- **Label** (`700`, `11px`): controls, field names, route stages, and compact actions.
- **Micro** (`600`, `10px`): run metadata, event details, and table headers.
- **Route Detail** (`400`, `9px`): stage status beneath route nodes.

**The Compact Hierarchy Rule.** Hierarchy comes from weight and placement, not oversized type or labels floating above headings.

## Layout

Desktop uses a `284px` full-height run ledger and a flexible selected-case workspace. The workspace begins with the case header, then the seven-stage route, tab navigation, and a result viewport. Overview uses a `1.65fr / 0.85fr` asymmetric grid; detail views use full-width tables or two-column result blocks.

At `1080px`, the ledger narrows to `240px`. At `820px`, the ledger becomes a top region with a horizontally scrollable run list and the workspace stacks below. At `620px`, filters, metrics, result grids, forms, and report columns become single-column or two-up where the data remains readable. Workflow routes and tabs scroll horizontally instead of compressing their labels.

Spacing follows a compact `4 / 8 / 10 / 14 / 20 / 24px` rhythm. Data rows use tighter spacing than section boundaries.

## Elevation & Depth

The workspace is flat and line-driven. Borders and tonal surfaces establish hierarchy. Shadows are reserved for the slide-over inspection drawer and the white formal-report sheet, where physical separation is meaningful.

### Shadow Vocabulary

- **Drawer Lift** (`-18px 0 48px rgba(7, 24, 20, 0.2)`): separates the protected intake task from the selected case.
- **Document Lift** (`0 18px 44px rgba(36, 47, 41, 0.09)`): separates the printable report sheet from the operations ground.

**The Flat Operations Rule.** Routine data sections use borders and surface changes; they do not receive decorative shadows.

## Shapes

Controls and operational sections use practical `4px` or `6px` corners. The `10px` radius is reserved for larger document or workspace surfaces. Status indicators use circles or pill geometry because their compact silhouette is useful for scanning. Lines remain one pixel and directional route geometry stays thin.

## Components

### Buttons

- **Shape:** compact rectangle with `4px` or `6px` radius.
- **Primary:** action teal fill, white label, minimum `38px` height.
- **Secondary:** transparent or white surface with a strong neutral border.
- **Hover / Focus:** hover deepens the action color or promotes the border to teal; keyboard focus uses a visible teal ring.
- **Danger:** red text and border, with a pale red hover surface.

### Status Chips

- **Style:** small pill with both text and tonal background.
- **State:** teal for complete, amber for running or queued, red for failed. Color never replaces the written state.

### Containers

- **Corner Style:** `6px` for data sections and `10px` for large document surfaces.
- **Background:** white over mist paper; deep corridor green for the run ledger.
- **Border:** one-pixel neutral rule.
- **Internal Padding:** `10–14px` for dense data and `20–24px` for major regions.

### Inputs / Fields

- **Style:** white field, strong neutral stroke, `4px` radius, and `38px` minimum height.
- **Focus:** visible teal ring with offset.
- **Density:** labels stay close to controls; runtime options are contained in a native disclosure.

### Navigation

- **Run Ledger:** compact rows preserve asset, run identity, stage, and percent. Selection changes the row surface and adds a one-pixel route signal.
- **Result Tabs:** text tabs use a two-pixel teal underline when active and remain horizontally scrollable on narrow screens.
- **Workflow Route:** seven circular nodes connect through a one-pixel line; completed nodes fill teal, the current node fills amber, and failed nodes fill red.

### Inspection Drawer

The drawer enters from the right and preserves the selected case beneath a dark overlay. Asset and evidence fields remain visible; advanced runtime settings stay collapsed until requested. The submit action remains fixed to the drawer footer.

### Formal Report

The report is a white, printable document with a serif title, strong horizontal rules, restrained callouts, and compact tables. Markdown syntax is removed before narrative text enters this surface.

## Do's and Don'ts

### Do:

- **Do** keep run identity and status visible while the operator changes result tabs.
- **Do** use the workflow route for durable execution state and recovery visibility.
- **Do** keep evidence, RAG sources, planning, scheduling, reporting, and activity isolated by the selected run.
- **Do** stack filters and data grids deliberately at phone width.

### Don't:

- **Don't** reintroduce sample-image browsing into the operator workspace.
- **Don't** stack every result domain into one scrolling dashboard.
- **Don't** use status colors as decoration or without a written label.
- **Don't** place the intake form permanently beside completed results.
- **Don't** add kickers, decorative gradients, glass effects, or oversized marketing typography.

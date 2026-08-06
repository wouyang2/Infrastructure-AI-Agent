# Inspection Workspace

- Scope: `static/index.html`, `static/styles.css`, and `static/app.js`.
- Mode: Operate.
- Audience: infrastructure inspectors, maintenance engineers, and case reviewers.
- Primary job: submit media, monitor multiple durable runs, inspect result provenance, review recommendations, and export a formal report.
- Primary action: create a new inspection from a slide-over drawer without losing the selected run.
- Required content: run states, workflow progress, observations, RAG citations and precedents, maintenance plan, schedule context, report preview, activity/review controls.
- Constraints: keep all current API behavior; remove sample-image browsing; support multiple simultaneous progress pollers; keep results isolated by selected run; preserve keyboard and responsive operation.

## Chosen Direction

Corridor Command Map. A persistent run ledger anchors the left edge. The selected inspection owns a horizontal workflow route and a tabbed technical workspace. New inspection opens in a drawer. Status is communicated through route position, text, and restrained signal color.

Approved comp: `.impeccable/mocks/corridor-a.png`.

Memorable moment: while a run is active, the workflow route advances from intake through report and the selected ledger row updates in place without displacing completed inspections.

## Implementation Inventory

| Ingredient | Commitment | Medium |
| --- | --- | --- |
| Run ledger | 280px dark rail, search/filter controls, compact rows, selected and live states | Semantic HTML/CSS |
| Primary action | Full-width New inspection command in rail; opens right-side drawer | HTML button + JS drawer state |
| Case header | Asset name, location, case ID, severity, repair decision, export | Semantic HTML/CSS |
| Workflow route | Seven labeled stages connected by a thin line; completed/current/future states | HTML list + CSS |
| Result navigation | Overview, Observations, RAG Sources, Maintenance Plan, Schedule, Report, Activity | Accessible tab buttons + JS |
| Overview | Asymmetric summary with severity decision, current progress, observation and retrieval previews | Semantic sections and data tables |
| Detail views | One visible result section at a time; no nested cards | HTML sections + JS tab state |
| New inspection | Asset, evidence upload, model configuration, submit action | Native form controls in modal drawer |
| Review actions | Notes and approve/revise/reject controls live in Activity | Existing PATCH API wiring |
| Formal report | Calm white document surface with export command | Existing semantic report renderer |

Component grammar: 4-6px corners, thin technical rules, near-zero decorative shadow, dense sans typography, tabular numbers, dark route ledger with pale content surface. Motion is limited to drawer entry, selected-route state, and progress changes; reduced motion removes translation.

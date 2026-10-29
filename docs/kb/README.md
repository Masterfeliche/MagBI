# MagBI Knowledge Base

> A living reference for everyone building MagBI — engineers, AI agents, and
> researchers. Each chapter explains one layer of the system end-to-end: what it
> does, why we chose this approach over the alternatives, how it works under the
> hood, and where the design is strong or fragile. As the implementation matures,
> each chapter is updated to reflect what we actually built versus what we planned.

This knowledge base doubles as a **research paper on business intelligence
systems** — it traces the journey from "what does Power BI actually do?" to
"how do you build one from scratch, and what do you learn along the way?"

---

## How to read this

- **New to the project?** Start with [01 System Overview](01-system-overview.md),
  then jump to whatever layer you are working on.
- **AI agent working on a feature?** Read the chapter for your layer first —
  it explains the contracts, invariants, and gotchas you need to respect.
- **Researcher / student?** Read front-to-back. The chapters are ordered from
  the data source to the user's screen, following data as it flows through the
  system.

---

## Chapters

| # | Chapter | What it covers |
|---|---------|----------------|
| 01 | [System Overview](01-system-overview.md) | Why build this, architecture big picture, technology stack decisions, design principles |
| 02 | [Data Connectors](02-data-connectors.md) | Pluggable source adapters — SQL Server, PostgreSQL, MySQL, CSV/Excel, DuckDB |
| 03 | [Transform Engine](03-transform-engine.md) | Power Query-style step editor, 21 transform types, query folding to source SQL |
| 04 | [Dataset & Semantic Model](04-dataset-model.md) | Tables, columns, relationships, hierarchies, date tables, RLS, model validation |
| 05 | [DAX-lite Formula Language](05-dax-lite.md) | Lexer, Pratt parser, two evaluation contexts, CALCULATE semantics, SQL compilation |
| 06 | [Query Engine](06-query-engine.md) | 8-step pipeline, filter context, join resolution, chasm-trap prevention, caching |
| 07 | [Report Designer](07-report-designer.md) | Free-form canvas, drag-and-drop, wells system, undo/redo, report definition JSON |
| 08 | [Visuals & ECharts](08-visuals-echarts.md) | 14 visual types, ECharts integration, cross-filtering, theming, accessibility |
| 09 | [API, Auth & Embedding](09-api-auth-embed.md) | REST API, JWT auth, workspace roles, embed tokens, WebSocket events |
| 10 | [Storage & Data Refresh](10-storage-refresh.md) | DuckDB file management, import pipeline, atomic swap, incremental refresh |
| 11 | [Deployment & Operations](11-deployment-ops.md) | Docker Compose, scaling patterns, monitoring, CI/CD |

---

## Conventions

Each chapter follows this structure:

1. **What it does** — feature-level overview a product person could read
2. **Why this approach** — the decision and what alternatives we rejected
3. **How it works** — technical deep-dive with diagrams where useful
4. **Key concepts** — underlying CS/engineering ideas explained from first principles
5. **Strengths** — where this design shines
6. **Weaknesses & risks** — where it could break and what we would change
7. **For agents** — invariants and contracts that automated code must respect
8. **Further reading** — links to specs, papers, and docs for the curious

---

## Status

This knowledge base is bootstrapped at project scaffold time. As each layer is
implemented, its chapter is updated from "planned design" to "what we actually
built." Look for the status badge at the top of each chapter:

- **Planned** — design only, no implementation yet
- **In Progress** — implementation underway, chapter may lag behind code
- **Implemented** — code is live, chapter reflects reality
- **Verified** — code is live and tested end-to-end

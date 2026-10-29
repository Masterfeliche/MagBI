# MagBI Business Model

**Version:** 1.0
**Date:** 29 October 2026
**Author:** Magila Technology Co. Ltd

---

## Model: Open-Core with Per-Instance Pricing

MagBI follows the open-core model proven by Metabase, Grafana, and GitLab:
a fully functional free tier drives adoption, while enterprise features that
matter at scale generate revenue — without ever charging per user.

The per-user fee is the problem MagBI was built to eliminate. The business
model must not reintroduce it.

---

## Tier Structure

### Community Edition (Free / Open Source)

The complete BI engine, free to self-host. No artificial limits on users,
dashboards, or data volume.

| Capability | Included |
|------------|----------|
| Query engine (semantic model, DAX-lite, 8-step pipeline) | Yes |
| Report designer (drag-and-drop, 13 visual types, cross-filtering) | Yes |
| Report viewer and embed SDK | Yes |
| SQL Server, PostgreSQL, MySQL, CSV/Excel, DuckDB connectors | Yes |
| Transform engine with query folding | Yes |
| Row-level security (static roles) | Yes |
| Manual data refresh | Yes |
| Single workspace | Yes |
| Docker deployment | Yes |
| Community support (GitHub Issues) | Yes |

**Purpose:** Adoption. Every organisation with a SQL database can deploy MagBI
and get production-quality dashboards at zero cost. This builds the user base,
the community, and the reputation.

**License:** A permissive source-available license (e.g., BSL 1.1 or
Elastic License 2.0) that allows free self-hosting and modification but
prevents competitors from offering MagBI as a managed service.

---

### MagBI Pro (Paid / Per-Instance)

Enterprise features for organisations that run MagBI at scale. Priced per
deployment, not per user.

| Capability | Community | Pro |
|------------|-----------|-----|
| Unlimited users and dashboards | Yes | Yes |
| Multi-workspace with isolation | — | Yes |
| Role-based access control (admin/editor/viewer/embed) | Basic | Full RBAC with custom roles |
| Audit log (who viewed what, when) | — | Yes |
| Scheduled refresh with monitoring | — | Yes |
| Refresh failure alerting (email, webhook) | — | Yes |
| SSO / SAML / OIDC integration | — | Yes |
| Dynamic RLS from host application | — | Yes |
| Priority connectors (Snowflake, BigQuery, REST API) | — | Yes |
| Incremental refresh (date-partitioned) | — | Yes |
| Embed SDK advanced features (theme sync, nav events) | — | Yes |
| Email support with SLA | — | Yes |

**Pricing:** Flat annual fee per deployment.

| Tier | Price | Target |
|------|-------|--------|
| Small (≤ 5 datasets, ≤ 3 workspaces) | $2,000/year | Small businesses, departments |
| Standard (≤ 25 datasets, ≤ 10 workspaces) | $5,000/year | Mid-size organisations |
| Enterprise (unlimited, custom SLA) | $12,000+/year | Large organisations, OEM partners |

**Comparison:** A 100-user Power BI deployment costs $1,000+/month ($12,000/year)
for Pro licenses alone, before Azure capacity. MagBI Standard serves the same
100 users for $5,000/year — a 58% saving that grows with every additional user.

---

### MagBI Cloud (Managed SaaS — Phase 2)

For organisations that do not want to manage infrastructure. Multi-tenant,
usage-based pricing.

| Capability | Description |
|------------|-------------|
| Fully managed hosting | Magila operates the infrastructure |
| Automatic updates | Always on the latest version |
| Usage-based pricing | Per-dataset/month + per-refresh-hour |
| Tenant isolation | Each organisation's data is isolated |
| Global CDN | Dashboard viewer served from edge locations |
| 99.9% uptime SLA | Enterprise reliability |

**Pricing:** $20/dataset/month base + $0.10/refresh-hour. A typical deployment
with 10 datasets refreshing every 30 minutes costs ~$300/month.

**Timeline:** Phase 2 (after Phase 1 ships). Requires multi-tenant architecture,
tenant isolation, and operational tooling.

---

## Revenue Channels

### 1. MSD ERP — Built-In Distribution

Every MSD ERP deployment ships with MagBI Community built in. This is not a
separate sale — it is part of the ERP.

**Revenue impact:**
- Eliminates Power BI licensing costs for all ERP clients (value-add)
- Increases ERP competitiveness (embedded analytics at no extra cost)
- Creates a captive base of MagBI users who may upgrade to Pro

**Upgrade path:** ERP clients who need audit logs, SSO, or scheduled refresh
upgrade to MagBI Pro. The ERP integration already works; they are paying for
governance and automation features.

### 2. Standalone Deployments

Organisations without MSD ERP deploy MagBI for their own databases.

**Acquisition:** Open source community → documentation and tutorials → Pro
upgrade when they hit enterprise needs (SSO, audit, multi-workspace).

**Target segments:**
- SMBs with 50–500 employees who use SQL databases but cannot afford Power BI
- SaaS companies that want to embed analytics in their product
- Government and NGO organisations with budget constraints

### 3. OEM / White-Label

SaaS companies embed MagBI inside their own product under a white-label
agreement. MagBI provides the engine; the SaaS company provides the UI skin
and the data.

**Pricing:** Annual OEM license ($15,000–$50,000/year depending on scale),
includes SDK access, theme customisation, and priority support.

### 4. MagBI Cloud Subscriptions

Usage-based SaaS revenue from Phase 2. Recurring, predictable, and grows
with customer data volume.

---

## Unit Economics

### Cost Structure

| Component | Monthly Cost (typical) |
|-----------|----------------------|
| Development team (ongoing) | Internal |
| Cloud infrastructure (per Cloud tenant) | ~$50/tenant |
| Support (per Pro customer) | ~$100/customer |
| Community infrastructure (docs, CI, forums) | ~$500 fixed |

### Per-Customer Economics (Pro Standard)

| Metric | Value |
|--------|-------|
| Annual revenue | $5,000 |
| Annual support cost | ~$1,200 |
| Annual infrastructure cost | $0 (self-hosted) |
| **Gross margin** | **~76%** |

### Break-Even

At $5,000/year average revenue per Pro customer, break-even on ongoing
development costs is achievable with 20–30 paying customers — a realistic
target given the MSD ERP install base as a starting pipeline.

---

## Competitive Moat

### 1. ERP Distribution Channel

MagBI ships inside MSD ERP. Every new ERP client is a MagBI user on day one.
No competing BI tool has this embedded distribution for our market.

### 2. Integration Depth

MagBI reads the host application's user system, theme, and permissions
directly. Competitors require middleware, token exchange, and manual mapping.
The deeper the integration, the higher the switching cost.

### 3. Query Engine IP

The DAX-lite compiler, query folding engine, and chasm-trap prevention are
significant technical IP. Replicating this from scratch takes 6–12 months of
specialised engineering.

### 4. Zero Per-User Pricing

Once a competitor's model is per-user, they cannot match MagBI's flat pricing
without cannibalising their own revenue. This is a structural advantage, not
a promotional discount.

---

## Growth Strategy

```
Phase 1 (Month 1–4)     → Ship v1, deploy inside MSD ERP
Phase 2 (Month 5–8)     → Open-source Community Edition
                           First standalone deployments
                           Launch Pro tier
Phase 3 (Month 9–12)    → MagBI Cloud beta
                           First OEM partnership
                           Community growth (docs, tutorials, templates)
Phase 4 (Year 2)        → Cloud GA
                           International expansion
                           Marketplace (community connectors, visual plugins)
```

---

## Key Metrics to Track

| Metric | Why It Matters |
|--------|---------------|
| Community deployments | Adoption funnel — more installs → more Pro conversions |
| Community → Pro conversion rate | Product-market fit signal; target 3–5% |
| Pro annual retention | Revenue durability; target > 90% |
| Datasets per deployment | Usage depth; more datasets → stickier customer |
| Time to first chart | Onboarding quality; target < 15 minutes |
| Cloud MRR (Phase 2) | SaaS growth trajectory |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Open-source fork competes | BSL/Elastic license prevents managed-service competition; invest in community goodwill |
| Metabase or Superset adds embedding features | Our integration depth with host applications is structural, not feature-level |
| Slow community adoption | MSD ERP base guarantees initial user volume independent of community growth |
| Pro pricing too high for SMBs | Small tier at $2,000/year is below most organisations' approval threshold |
| Cloud multi-tenancy complexity | Defer Cloud to Phase 2; validate Pro revenue first on self-hosted |

---

## Summary

MagBI's business model is built on three principles:

1. **Never charge per user.** The entire value proposition starts here.
2. **Give away the engine, sell the governance.** Community Edition is the
   product; Pro is the enterprise wrapper.
3. **Grow through the ERP.** Every MSD ERP deployment is a MagBI deployment.
   The community and standalone channels compound on top.

The open-core model aligns incentives: the more people who use MagBI for free,
the more organisations who need Pro features at scale. Growth in the free tier
feeds revenue in the paid tier, without a per-user tax that slows adoption.

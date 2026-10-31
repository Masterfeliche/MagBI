/**
 * Landing page copy and figures. Bracketed values are placeholders the owner
 * fills in before launch; the page shows them as they are.
 */

export const COMPANY = {
  name: "[COMPANY NAME]",
  contactEmail: "[CONTACT EMAIL]",
  phone: "[PHONE]",
};

export const CUSTOMER_QUOTE = {
  text: "[CUSTOMER QUOTE]",
  by: "[NAME, ROLE], MSD ERP",
};

export const GLANCE = [
  { value: "0", label: "Per-user licences or capacity fees" },
  { value: "14", label: "Standard visuals, one consistent look" },
  { value: "Every", label: "filter value checked before a dashboard ships" },
  { value: "Read-only", label: "access to your production database" },
];

export const BUYERS = [
  {
    tag: "Software vendors",
    title: "Dashboards inside your own product",
    body: "You build an ERP, a health system or a SaaS product and want analytics in it, without paying Power BI Embedded capacity for every customer.",
    gain: "embed tokens, a separate workspace per customer, read-only access to each database.",
  },
  {
    tag: "Power BI users",
    title: "The same dashboards, without the per-seat bill",
    body: "Public bodies, supply chains, utilities and mid-size companies whose Power BI costs grow with every new user.",
    gain: "datasets, measures, workspaces and embedding you already know, priced by server, not by seat.",
  },
  {
    tag: "Starting out",
    title: "BI on your own database, without a data team",
    body: "Organisations with a working system and no reporting yet, who need clear dashboards on the data they already have.",
    gain: "a standard visual kit and a QA gate that checks every figure before anyone sees it.",
  },
];

export const ROLES = [
  { mark: "V", name: "Dashboard viewers", body: "Directors, managers and officers who read dashboards and act on them. The largest group by far.", where: "Usually inside the host app, never in the designer" },
  { mark: "B", name: "BI developers and analysts", body: "Build datasets, measures and dashboards, and run the QA checks before publishing.", where: "In the MagBI designer" },
  { mark: "A", name: "Workspace admins and IT", body: "Set up database connections, roles, row-level security and refresh schedules.", where: "In MagBI workspaces" },
  { mark: "D", name: "Host app developers", body: "Embed dashboards in their application with the SDK and short-lived tokens.", where: "In their own codebase" },
];

export const FEATURES = [
  { tag: "Connect", title: "Your database, read-only", body: "SQL Server today, with CSV and Excel uploads. Datasets are read-only queries, refreshed on a schedule." },
  { tag: "Model", title: "Star schemas and measures", body: "Relationships that filter one way, as in Power BI, and DAX-style measures in one shared dataset for many dashboards." },
  { tag: "Design", title: "A report designer and a visual kit", body: "KPI cards with status rules, flow chains, donuts, heat matrices, Pareto and status tables, all in your theme." },
  { tag: "Check", title: "A QA gate on every release", body: "Every visual is run with every filter value, figures are compared with the source, and every page is rendered at full HD." },
  { tag: "Embed", title: "Inside your application", body: "Show dashboards in your own product with short-lived tokens. Your users never leave your app." },
  { tag: "Govern", title: "Workspaces, roles and row-level security", body: "Separate workspaces per team or customer, role checks on every action, rows limited per role." },
];

export const CUSTOMER_FIGURES = [
  { label: "Dashboards live", value: "3" },
  { label: "ERP modules planned", value: "8" },
  { label: "Checks per release", value: "759" },
  { label: "Slowest query", value: "0.29 s" },
];

export const POWER_BI_MAP = [
  { pbi: "Semantic model", magbi: "Dataset: tables, relationships and measures, shared by many dashboards" },
  { pbi: "DAX measures", magbi: "DAX-style measures, compiled to fast columnar queries" },
  { pbi: "Power BI Desktop", magbi: "The MagBI designer, in the browser" },
  { pbi: "Power BI Embedded", magbi: "Embed tokens, with no capacity to buy" },
  { pbi: "Workspaces and roles", magbi: "Workspaces with viewer, editor and admin roles" },
  { pbi: "Scheduled refresh", magbi: "Scheduled refresh from your database" },
];

export const SECURITY = [
  { title: "Read-only queries", body: "Anything that is not a single SELECT is refused before it reaches your database." },
  { title: "Roles per workspace", body: "Viewers read, editors build, admins manage connections and members." },
  { title: "Embed tokens that only read", body: "A dashboard embedded in your app can read its own report and data, nothing else." },
  { title: "Encrypted credentials", body: "Connection passwords are stored encrypted and never shown again." },
];

export const PLANS = [
  {
    name: "Starter",
    fits: "One organisation on one database.",
    prefix: "from",
    price: "[$300]",
    unit: "per month",
    featured: false,
    cta: "Talk to us",
    items: ["Unlimited viewers", "1 workspace, up to 10 dashboards", "Daily refresh", "Standard visual kit and QA gate"],
  },
  {
    name: "Business",
    fits: "Larger organisations with several departments.",
    prefix: "from",
    price: "[$1,000]",
    unit: "per month",
    featured: true,
    cta: "Book a demo",
    items: ["Unlimited viewers and dashboards", "Several workspaces", "Hourly refresh", "Row-level security and embedding"],
  },
  {
    name: "Vendor",
    fits: "Software vendors showing dashboards inside their product.",
    prefix: "[$X] base +",
    price: "[$100]",
    unit: "per customer workspace / month",
    featured: false,
    cta: "Talk to us",
    items: ["A separate workspace per customer", "Embed SDK and short-lived tokens", "White-label: your brand, not ours", "Priority support"],
  },
];

export const YEARLY_DISCOUNT = "[15%]";
export const BUILD_PACKAGE_PRICE = "[$X]";
export const SELF_HOSTED_PRICE = "[$X]";

/** Batches expiring by month in the MSD ERP Stock & Expiry dashboard, Oct 2026 to Sep 2027. */
export const EXPIRY_MONTHS = [0, 79, 118, 81, 28, 46, 0, 0, 0, 0, 0, 0];

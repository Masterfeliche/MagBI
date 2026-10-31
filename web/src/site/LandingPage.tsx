/** MagBI's public landing page: what it is, who it is for, what it costs. */

import { Link } from "react-router-dom";

import { hasSession } from "../shared/session";
import {
  BUILD_PACKAGE_PRICE,
  BUYERS,
  COMPANY,
  CUSTOMER_FIGURES,
  CUSTOMER_QUOTE,
  EXPIRY_MONTHS,
  FEATURES,
  GLANCE,
  PLANS,
  POWER_BI_MAP,
  ROLES,
  SECURITY,
  SELF_HOSTED_PRICE,
  YEARLY_DISCOUNT,
} from "./content";
import { Logo } from "./Logo";
import "./site.css";

const NAV = [
  { href: "#who", label: "Who it's for" },
  { href: "#platform", label: "Platform" },
  { href: "#customers", label: "Customers" },
  { href: "#powerbi", label: "From Power BI" },
  { href: "#pricing", label: "Pricing" },
];

export function LandingPage() {
  const signedIn = hasSession();
  return (
    <div className="site">
      <header className="site-top">
        <div className="site-wrap site-nav">
          <a href="#top" className="site-brand" aria-label="MagBI home">
            <Logo />
            <span>MagBI</span>
          </a>
          <nav aria-label="Main" className="site-links">
            {NAV.map((item) => (
              <a key={item.href} href={item.href}>{item.label}</a>
            ))}
            {signedIn ? (
              <Link to="/workspaces" className="site-signin">Open MagBI</Link>
            ) : (
              <Link to="/login" className="site-signin">Sign in</Link>
            )}
            <a href="#demo" className="site-btn site-btn-accent">Book a demo</a>
          </nav>
        </div>
      </header>

      <section id="top" className="site-hero">
        <div className="site-wrap site-hero-grid">
          <div className="site-hero-copy">
            <div className="site-eyebrow site-eyebrow-warm">Business intelligence platform</div>
            <h1>Dashboards your users trust, inside the product they already use.</h1>
            <p>
              MagBI connects to your database, models it with DAX-style measures, checks every figure, and embeds the
              dashboards in your application. No per-user licences, no capacity fees.
            </p>
            <div className="site-actions">
              <a href="#demo" className="site-btn site-btn-accent site-btn-lg">Book a demo</a>
              <a href="#customers" className="site-btn site-btn-ghost site-btn-lg">See it in MSD ERP</a>
            </div>
          </div>
          <HeroPreview />
        </div>
      </section>

      <section aria-label="MagBI at a glance" className="site-glance-band">
        <div className="site-wrap site-glance">
          {GLANCE.map((item) => (
            <div key={item.label}>
              <div className="site-glance-value">{item.value}</div>
              <div className="site-glance-label">{item.label}</div>
            </div>
          ))}
        </div>
      </section>

      <section id="who" className="site-section">
        <div className="site-wrap">
          <SectionHead eyebrow="Who it's for" title="Built for teams that need dashboards without the licence bill." />
          <div className="site-cards site-cards-3">
            {BUYERS.map((buyer) => (
              <article key={buyer.tag} className="site-card">
                <span className="site-chip">{buyer.tag}</span>
                <h3>{buyer.title}</h3>
                <p>{buyer.body}</p>
                <p className="site-card-foot"><b>What you get:</b> {buyer.gain}</p>
              </article>
            ))}
          </div>
          <h3 className="site-subhead">Who uses MagBI day to day</h3>
          <div className="site-cards site-cards-4">
            {ROLES.map((role) => (
              <article key={role.name} className="site-card site-card-soft">
                <div className="site-role">
                  <span aria-hidden="true">{role.mark}</span>
                  <b>{role.name}</b>
                </div>
                <p>{role.body}</p>
                <span className="site-where">{role.where}</span>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="platform" className="site-section">
        <div className="site-wrap">
          <SectionHead eyebrow="Platform" title="Everything between your database and a dashboard someone can act on." />
          <div className="site-cards site-cards-3">
            {FEATURES.map((feature) => (
              <article key={feature.tag} className="site-card">
                <span className="site-mono">{feature.tag}</span>
                <h3>{feature.title}</h3>
                <p>{feature.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="customers" className="site-section">
        <div className="site-wrap site-story">
          <div className="site-story-copy">
            <div className="site-eyebrow">Customer story · MSD ERP</div>
            <h2>MSD ERP moved its warehouse dashboards off Power BI Embedded.</h2>
            <p>
              MSD ERP runs the stores, procurement, finance and HR of the Medical Stores Department. Its Warehouse
              dashboards now come from MagBI: built on read-only queries against the ERP database, checked against it
              figure by figure, and shown inside the ERP. The remaining modules follow one at a time.
            </p>
            <blockquote>
              “{CUSTOMER_QUOTE.text}”
              <footer>{CUSTOMER_QUOTE.by}</footer>
            </blockquote>
          </div>
          <dl className="site-story-figures">
            {CUSTOMER_FIGURES.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section id="powerbi" className="site-section">
        <div className="site-wrap">
          <SectionHead eyebrow="Coming from Power BI" title="The ideas you know, without the per-seat bill." />
          <div className="site-table-box">
            <table className="site-table">
              <thead>
                <tr>
                  <th scope="col">In Power BI</th>
                  <th scope="col">In MagBI</th>
                </tr>
              </thead>
              <tbody>
                {POWER_BI_MAP.map((row) => (
                  <tr key={row.pbi}>
                    <td>{row.pbi}</td>
                    <td>{row.magbi}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="security" className="site-section">
        <div className="site-wrap site-security">
          <div>
            <div className="site-eyebrow">Security</div>
            <h2>Your data stays yours, and stays read-only.</h2>
          </div>
          <ul>
            {SECURITY.map((item) => (
              <li key={item.title}><b>{item.title}</b>{item.body}</li>
            ))}
          </ul>
        </div>
      </section>

      <section id="pricing" className="site-section">
        <div className="site-wrap">
          <div className="site-head-row">
            <SectionHead eyebrow="Pricing" title="Priced per deployment. Every viewer included." />
            <p className="site-aside">
              Add a hundred viewers or ten thousand: the price stays the same. Pay yearly and save {YEARLY_DISCOUNT}.
            </p>
          </div>
          <div className="site-cards site-cards-3">
            {PLANS.map((plan) => (
              <article key={plan.name} className={plan.featured ? "site-card site-plan site-plan-featured" : "site-card site-plan"}>
                <div className="site-plan-head">
                  <h3>{plan.name}</h3>
                  {plan.featured && <span className="site-chip site-chip-warm">Most chosen</span>}
                </div>
                <p>{plan.fits}</p>
                <div className="site-price">
                  <span>{plan.prefix}</span>
                  <strong>{plan.price}</strong>
                  <span>{plan.unit}</span>
                </div>
                <ul className="site-ticks">
                  {plan.items.map((item) => (
                    <li key={item}><span aria-hidden="true">▲</span>{item}</li>
                  ))}
                </ul>
                <a href="#demo" className={plan.featured ? "site-btn site-btn-navy" : "site-btn site-btn-outline"}>{plan.cta}</a>
              </article>
            ))}
          </div>
          <div className="site-cards site-cards-2">
            <div className="site-card site-card-soft">
              <b>Dashboard build packages</b>
              <p>We build a module of 6 to 8 dashboards on your data, checked figure by figure before handover. Fixed price from {BUILD_PACKAGE_PRICE} per module.</p>
            </div>
            <div className="site-card site-card-soft">
              <b>Self-hosted</b>
              <p>Run MagBI on your own servers when data cannot leave your premises. Annual licence and support from {SELF_HOSTED_PRICE} per year.</p>
            </div>
          </div>
        </div>
      </section>

      <section id="demo" className="site-section site-section-last">
        <div className="site-wrap site-demo">
          <div>
            <h2>See your own data in MagBI.</h2>
            <p>We connect read-only to a copy of your database and build one of your dashboards with you.</p>
            <p className="site-demo-contact">Write to {COMPANY.contactEmail} or call {COMPANY.phone}.</p>
          </div>
          <div className="site-actions">
            <Link to="/login" className="site-btn site-btn-ghost site-btn-lg">Sign in</Link>
          </div>
        </div>
      </section>

      <footer className="site-footer">
        <div className="site-wrap site-footer-row">
          <span><b>MagBI</b> · by {COMPANY.name}</span>
          <span>{COMPANY.contactEmail} · {COMPANY.phone}</span>
        </div>
      </footer>
    </div>
  );
}

function SectionHead({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div>
      <div className="site-eyebrow">{eyebrow}</div>
      <h2 className="site-h2">{title}</h2>
    </div>
  );
}

function HeroPreview() {
  const max = Math.max(...EXPIRY_MONTHS);
  return (
    <figure className="site-preview" aria-label="A dashboard built with MagBI: Stock and Expiry in MSD ERP">
      <div className="site-preview-board">
        <div className="site-preview-head">
          <div>
            <div className="site-preview-crumb">Warehouse / <b>Stock and expiry</b></div>
            <div className="site-preview-title">Stock &amp; Expiry</div>
          </div>
          <div className="site-preview-asat">Data as at <b>31 Oct 2026, 02:06</b></div>
        </div>
        <div className="site-preview-kpis">
          <PreviewKpi caption="Batches on hand" value="1,461" status="● Information" tone="info" />
          <PreviewKpi caption="Expiring in 90 days" value="274" status="◆ Watch · 19%" tone="watch" />
          <PreviewKpi caption="Expired on the shelf" value="0" status="▲ None held" tone="good" />
        </div>
        <div className="site-preview-panel">
          <div className="site-preview-strip"><b>When stock expires</b><span>amber = next 90 days</span></div>
          <div className="site-preview-bars" role="img" aria-label="Batches expiring by month: 79 in November, 118 in December, 81 in January, then 28 and 46">
            {EXPIRY_MONTHS.map((value, index) => (
              <div key={index} className="site-preview-bar">
                <span>{value || ""}</span>
                <i
                  className={value === 0 ? "zero" : index >= 1 && index <= 3 ? "soon" : ""}
                  style={{ height: Math.max(2, Math.round((value / max) * 96)) }}
                />
              </div>
            ))}
          </div>
          <div className="site-preview-axis"><span>Oct 26</span><span>Jan 27</span><span>Apr 27</span><span>Jul 27</span></div>
        </div>
      </div>
      <figcaption>Built with MagBI, shown inside MSD ERP, live on its data.</figcaption>
    </figure>
  );
}

function PreviewKpi({ caption, value, status, tone }: { caption: string; value: string; status: string; tone: "info" | "watch" | "good" }) {
  return (
    <div className={`site-preview-kpi ${tone}`}>
      <div>{caption}</div>
      <strong>{value}</strong>
      <span>{status}</span>
    </div>
  );
}

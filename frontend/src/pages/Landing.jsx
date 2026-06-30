import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BarChart3,
  BellRing,
  CheckCircle2,
  Clock3,
  Cpu,
  DatabaseZap,
  FileCheck2,
  FileSearch,
  Github,
  Globe2,
  Layers3,
  Linkedin,
  LockKeyhole,
  MapPinned,
  Radar,
  SearchCheck,
  ShieldCheck,
  Sparkles,
  Twitter,
  Zap,
  Workflow,
} from "lucide-react";
import { api } from "../lib/api.js";
import { formatApiDateTime } from "../lib/time.js";

const pipeline = [
  { label: "Capture", detail: "Static HTML first pass", icon: Globe2 },
  { label: "Render", detail: "Playwright for JS portals", icon: Cpu },
  { label: "Normalize", detail: "Clean PostgreSQL records", icon: DatabaseZap },
  { label: "Notify", detail: "Matched tender email", icon: BellRing },
];

const capabilities = [
  { title: "Real-time tender intake", detail: "The dashboard refreshes live while the hourly scraper and manual runs write clean records into PostgreSQL.", icon: DatabaseZap },
  { title: "Keyword intelligence", detail: "Defense, surveillance, camera, EOSS, NVD, PTZ, protection, and counter-UAV terms are tagged at ingestion.", icon: ShieldCheck },
  { title: "Reliable opening and closing dates", detail: "NIC-style three-date rows are parsed into published, closing, and opening dates with direct tender links.", icon: FileCheck2 },
  { title: "Operations-ready alerts", detail: "Matched tenders can trigger Gmail SMTP alerts and stay visible in the live dashboard workflow.", icon: Workflow },
];

const keywordShowcase = [
  "Thermal Weapon Sight",
  "Night Vision Device",
  "PTZ Camera",
  "EOSS",
  "LOROS",
  "Laser Range Finder",
  "LRF Integrated Sight",
  "Thermal Imager",
  "NVG",
  "Border Surveillance",
  "Holographic Sight",
  "Battlefield Surveillance Radar + EO",
  "PTZ with EO Payload",
];

const footerSocials = [
  { label: "LinkedIn", href: "https://www.linkedin.com/", icon: Linkedin },
  { label: "GitHub", href: "https://github.com/", icon: Github },
  { label: "X", href: "https://x.com/", icon: Twitter },
];

const portalGroups = [
  { label: "National", value: "GeM, CPPP, GePNIC, IREPS, Defence, Coal India" },
  { label: "North", value: "UP, Haryana, Punjab" },
  { label: "West", value: "Maharashtra, Gujarat, Rajasthan" },
  { label: "East", value: "West Bengal, Odisha, Bihar, Jharkhand, Assam" },
  { label: "South", value: "Karnataka, Tamil Nadu, Telangana, Andhra, Kerala" },
  { label: "Central", value: "Madhya Pradesh" },
];

const proposalSignals = ["23 proposal portals", "60+ defense keywords", "Hourly automation", "PostgreSQL audit trail"];

const footerCoverage = ["23 proposal portals", "60+ defense keywords", "Hourly scraper health", "Email alerts"];

function formatDateTime(value) {
  return formatApiDateTime(value, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function statusTone(status = "") {
  if (["success", "ok", "empty", "cached"].includes(status)) return "success";
  if (["retrying", "failed", "temporarily_blocked"].includes(status)) return "warning";
  return "neutral";
}

function statusLabel(status = "") {
  const labels = {
    success: "live",
    empty: "checked",
    cached: "cached",
    retrying: "auto retry",
    temporarily_blocked: "auto retry",
    failed: "auto retry",
  };
  return labels[status] || status || "pending";
}

export default function Landing({ onAuth }) {
  const [health, setHealth] = useState(null);
  const [portalHealth, setPortalHealth] = useState([]);
  const [healthError, setHealthError] = useState("");

  useEffect(() => {
    let active = true;

    const loadLiveData = () => {
      Promise.allSettled([api("/health"), api("/health/portals")]).then(([healthResult, portalsResult]) => {
        if (!active) return;
        if (healthResult.status === "fulfilled") {
          setHealth(healthResult.value);
          setHealthError("");
        } else {
          setHealthError("Backend waiting");
        }
        if (portalsResult.status === "fulfilled") {
          setPortalHealth(portalsResult.value || []);
        }
      });
    };

    loadLiveData();
    const timer = window.setInterval(loadLiveData, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const scraper = health?.scraper || {};
  const methods = health?.scrape_methods || {};
  const scrapeLabel = scraper.running ? "Scraper running now" : health?.auto_scrape_enabled ? "Auto scraper active" : healthError || "Live scraper ready";
  const latestRows = useMemo(
    () =>
      [...portalHealth]
        .sort((a, b) => new Date(b.scraped_at || 0) - new Date(a.scraped_at || 0))
        .slice(0, 4),
    [portalHealth]
  );
  const successPortals = portalHealth.filter((portal) => ["success", "empty", "cached"].includes(portal.status)).length;
  const warningPortals = portalHealth.filter((portal) => ["retrying", "failed", "temporarily_blocked"].includes(portal.status)).length;
  const methodCards = [
    { label: "Static HTML", value: "Enabled", icon: Globe2, active: true },
    { label: "Browser render", value: methods.dynamic_browser ? "Enabled" : "Standby", icon: Cpu, active: Boolean(methods.dynamic_browser) },
    { label: "Local direct", value: methods.api_proxy ? "Proxy optional" : "Active", icon: Radar, active: !methods.api_proxy },
  ];

  return (
    <main className="landingPage">
      <section className="landingHero">
        <nav className="landingNav" aria-label="Landing navigation">
          <div className="landingBrand">
            <DatabaseZap size={24} />
            <span>Apna Tender</span>
          </div>
          <div className="landingNavLinks">
            <a href="#pipeline">Pipeline</a>
            <a href="#coverage">Coverage</a>
            <a href="#capabilities">Platform</a>
          </div>
          <div className="landingNavActions">
            <button className="btn-outline" type="button" onClick={() => onAuth("signin")}>Sign in</button>
            <button className="btn-primary" type="button" onClick={() => onAuth("signup")}>Create account</button>
          </div>
        </nav>

        <div className="landingHeroInner">
          <div className="landingHeroCopy">
            <span className="landingHeroPill"><Zap size={15} /> AI tender intelligence, running locally</span>
            <h1>
              Introducing{" "}
              <span>Apna Tender AI</span>
            </h1>
            <p>
              A real-time procurement command center that scrapes every configured portal,
              understands tender content, and turns government opportunities into searchable intelligence.
            </p>
            <div className="landingActions">
              <button className="btn-primary" type="button" onClick={() => onAuth("signin")}>
                Open platform
                <ArrowRight size={18} />
              </button>
              <button className="btn-outline" type="button" onClick={() => onAuth("signup")}>Create account</button>
            </div>
            <div className="heroTrust">
              <span><CheckCircle2 size={16} /> {health?.tender_count || "Live"} active tenders</span>
              <span><Clock3 size={16} /> {scraper.interval_minutes || health?.auto_scrape_interval_minutes || 60} min cycle</span>
              <span><LockKeyhole size={16} /> Secure workspace</span>
            </div>
          </div>
        </div>

        <div className="heroLiveDock" aria-label="Live scraper summary">
          <div className="heroDockStatus">
            <div className="liveDotWrapper">
              <span className={`liveDot ${scraper.running ? "running" : ""}`} />
              <strong>{scrapeLabel}</strong>
            </div>
            <span>Last sync {formatDateTime(health?.latest_scrape)}</span>
          </div>
          <div className="heroDockMetric">
            <span>Records</span>
            <strong>{health?.tender_count || "Live"}</strong>
          </div>
          <div className="heroDockMetric">
            <span>Portals</span>
            <strong>{health?.scraper?.portal_count || 23}</strong>
          </div>
          <div className="heroDockMetric">
            <span>Cycle</span>
            <strong>{scraper.interval_minutes || health?.auto_scrape_interval_minutes || 60} min</strong>
          </div>
        </div>
      </section>

      <section className="landingStatsBand" aria-label="Platform live indicators">
        <div className="landingStats">
          <div className="landingStat clean-card">
            <DatabaseZap size={24} />
            <strong>{health?.tender_count || "Live"}</strong>
            <span>Active tenders</span>
          </div>
          <div className="landingStat clean-card">
            <Globe2 size={24} />
            <strong>{health?.scraper?.portal_count || 23}</strong>
            <span>Portal network</span>
          </div>
          <div className="landingStat clean-card">
            <SearchCheck size={24} />
            <strong>{successPortals || "Live"}</strong>
            <span>Healthy portal checks</span>
          </div>
          <div className="landingStat statusStat clean-card">
            <Clock3 size={24} />
            <strong>{scraper.running ? "Running" : warningPortals}</strong>
            <span>{scraper.running ? "Scrape in progress" : "Portal warnings"}</span>
          </div>
        </div>
      </section>

      <section className="landingSection commandSurfaceSection" aria-label="Live tender workspace preview">
        <div className="commandSurfaceCopy">
          <span className="landingEyebrow">Live command surface</span>
          <h2>Production data, shown with design-system clarity.</h2>
          <p>
            The landing page reads from the same backend as the dashboard: scraper health,
            tender volume, local network mode, browser scraping mode, and recent portal results.
          </p>
          <div className="methodGrid">
            {methodCards.map(({ label, value, icon: Icon, active }) => (
              <div className={`methodPill ${active ? "active" : ""}`} key={label}>
                <Icon size={20} />
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        </div>

        <aside className="commandSurfacePreview" aria-label="Live platform preview">
          <div className="previewTop">
            <span className={`liveDot ${scraper.running ? "running" : ""}`} />
            <strong>{scrapeLabel}</strong>
            <span>{formatDateTime(health?.latest_scrape)}</span>
          </div>
          <div className="previewHeader">
            <div>
              <span>Live tender lake</span>
              <strong>{health?.tender_count || "590"} records</strong>
            </div>
            <BarChart3 size={32} />
          </div>
          <div className="previewSearch">
            <FileSearch size={18} />
            <span>thermal camera border surveillance</span>
          </div>
          <div className="previewRows">
            {(latestRows.length ? latestRows : [
              { portal: "CPPP", status: "success", tenders_found: 12 },
              { portal: "Haryana eTenders", status: "success", tenders_found: 8 },
              { portal: "GeM", status: "empty", tenders_found: 0 },
            ]).map((row) => (
              <div className="commandRow" key={`${row.portal}-${row.scraped_at || row.status}`}>
                <span>{row.portal}</span>
                <strong>{row.tenders_found || 0} new</strong>
                <em className={statusTone(row.status)}>{statusLabel(row.status)}</em>
              </div>
            ))}
          </div>
        </aside>
      </section>

      <section className="landingInsightBand">
        <div className="landingSectionHead" style={{ textAlign: "center", margin: "0 auto", maxWidth: "800px" }}>
          <span className="landingEyebrow">Real-time operations layer</span>
          <h2>Live procurement signals, cleaned into a usable bid pipeline.</h2>
        </div>
        <div className="outcomeGrid">
          {[
            { title: "Fast qualification", detail: "Matched tenders are tagged the moment they are inserted or refreshed.", icon: Sparkles },
            { title: "Correct tender dates", detail: "Opening and closing dates are captured for government tender tables.", icon: FileCheck2 },
            { title: "Direct source links", detail: "Tender rows keep portal links that open the original notice.", icon: Layers3 },
          ].map(({ title, detail, icon: Icon }) => (
            <article className="outcomeCard clean-card" key={title}>
              <Icon size={24} />
              <strong>{title}</strong>
              <span>{detail}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="landingSection landingWorkflow" id="pipeline">
        <div className="landingSectionHead" style={{ textAlign: "center", margin: "0 auto", maxWidth: "800px" }}>
          <span className="landingEyebrow">Dual scraper pipeline</span>
          <h2>Built to fetch both simple HTML portals and JavaScript-rendered listings.</h2>
        </div>
        <div className="workflowRail">
          {pipeline.map(({ label, detail, icon: Icon }) => (
            <article className="workflowItem clean-card" key={label}>
              <Icon size={24} />
              <strong>{label}</strong>
              <span>{detail}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="landingSection coverageSection" id="coverage">
        <div className="coverageCopy">
          <span className="landingEyebrow">Portal coverage</span>
          <h2>National and state tenders collected into one searchable view.</h2>
          <p style={{ marginTop: "16px", color: "var(--lp-text-secondary)", fontSize: "1.1rem" }}>Each run records portal status, new tender count, errors, and last scraped time so the team can see exactly what is fresh.</p>
        </div>
        <div className="coveragePanel clean-card">
          <div className="coveragePanelHead">
            <MapPinned size={26} />
            <strong>{health?.scraper?.portal_count || 23} portal network</strong>
          </div>
          <div className="portalGroupGrid">
            {portalGroups.map(({ label, value }) => (
              <div className="portalGroup" key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="landingSection keywordShowcaseSection" aria-label="Keyword library coverage">
        <div className="landingSectionHead">
          <span className="landingEyebrow">50+ keyword library</span>
          <h2>Proposal keywords are matched against every tender title and description.</h2>
        </div>
        <div className="keywordTicker">
          {keywordShowcase.map((keyword) => <span key={keyword}>{keyword}</span>)}
        </div>
        <div className="proposalSignalGrid" aria-label="Proposal compliance signals">
          {proposalSignals.map((signal) => (
            <span key={signal}><CheckCircle2 size={18} /> {signal}</span>
          ))}
        </div>
      </section>

      <section className="landingSection">
        <div className="landingSectionHead" style={{ textAlign: "center", margin: "0 auto", maxWidth: "800px" }}>
          <span className="landingEyebrow">Premium tender workspace</span>
          <h2>Everything needed after the scrape is already connected.</h2>
        </div>
        <div className="capabilityGrid">
          {capabilities.map(({ title, detail, icon: Icon }) => (
            <article className="capabilityItem clean-card" key={title}>
              <Icon size={26} />
              <h3>{title}</h3>
              <p>{detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="landingClosing">
        <div>
          <span className="landingEyebrow">Ready workspace</span>
          <h2>Search, filter, export, alert, and monitor live scraper health from one responsive dashboard.</h2>
        </div>
        <button className="btn-primary darkCta" type="button" onClick={() => onAuth("signin")}>
          Enter Apna Tender
          <ArrowRight size={20} />
        </button>
      </section>

      <footer className="landingFooter">
        <div className="footerInner">
          <div className="footerBrand">
            <div className="footerLogo">
              <DatabaseZap size={24} />
              <div>
                <strong>Apna Tender</strong>
              </div>
            </div>
            <p>
              A polished on-premise tender platform with real scraper health,
              direct portal records, keyword matching, exports, and alerts.
            </p>
            <div className="footerStatus">
              <span className={`liveDot ${scraper.running ? "running" : ""}`} />
              <span>{scrapeLabel}</span>
            </div>
          </div>

          <div className="footerGroup">
            <strong>Coverage</strong>
            {footerCoverage.map((item) => <span key={item}>{item}</span>)}
          </div>

          <div className="footerGroup">
            <strong>Social</strong>
            <div className="footerSocials">
              {footerSocials.map(({ label, href, icon: Icon }) => (
                <a key={label} href={href} target="_blank" rel="noreferrer" aria-label={label}>
                  <Icon size={18} />
                  <span>{label}</span>
                </a>
              ))}
            </div>
          </div>

          <div className="footerActions">
            <strong>Quick links</strong>
            <button className="footerButton primaryFooter" type="button" onClick={() => onAuth("signin")}>Sign in</button>
            <button className="footerButton" type="button" onClick={() => onAuth("signup")}>Create account</button>
          </div>
        </div>
        <div className="footerBottom">
          <span>&copy; {new Date().getFullYear()} Apna Tender</span>
          <span>Live scraper &bull; PostgreSQL backed &bull; Alert ready</span>
        </div>
      </footer>
    </main>
  );
}

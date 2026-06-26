import { ArchiveRestore, CheckCircle2, Database, Download, HardDrive, Mail, Network, PlayCircle, RotateCcw, Save, Server, ShieldCheck, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { apiUrl, getToken } from "../lib/api.js";
import { formatApiDateTime } from "../lib/time.js";

const components = [
  { title: "23 Government Portals", detail: "6 national + 17 state police/eProcurement portals", icon: Network },
  { title: "Scraping Engine", detail: "BeautifulSoup + Playwright, FastAPI scheduler locally, Celery + Redis in Docker", icon: Workflow },
  { title: "Data Pipeline", detail: "Clean, validate, deduplicate, store tender-like records", icon: CheckCircle2 },
  { title: "PostgreSQL On-Prem", detail: "Tenders, keywords, alert subscriptions, scrape logs", icon: Database },
  { title: "Keyword Engine", detail: "50+ defense/surveillance terms with category tagging", icon: ShieldCheck },
  { title: "FastAPI Backend", detail: "JWT auth, REST APIs, search, filters, exports, alert actions", icon: Server },
  { title: "React Dashboard", detail: "Responsive HTML/CSS/JavaScript UI for search, filters, exports, alerts", icon: Workflow },
  { title: "Email Alerts", detail: "SendGrid instant alerts and daily digest for matching tenders", icon: Mail },
];

const fallbackPortals = [
  ["GeM", "National"],
  ["CPPP", "National"],
  ["GePNIC", "National"],
  ["IREPS", "National"],
  ["Defence eProcurement", "National"],
  ["Coal India Tenders", "National"],
  ["MahaTenders", "Maharashtra"],
  ["nProcure", "Gujarat"],
  ["Karnataka eProcurement", "Karnataka"],
  ["Tamil Nadu Tenders", "Tamil Nadu"],
  ["Telangana Tenders", "Telangana"],
  ["Andhra Pradesh eProcurement", "Andhra Pradesh"],
  ["UP eTender", "Uttar Pradesh"],
  ["Rajasthan eProcurement", "Rajasthan"],
  ["MP Tenders", "Madhya Pradesh"],
  ["Haryana eTenders", "Haryana"],
  ["Punjab eProcurement", "Punjab"],
  ["Kerala eTenders", "Kerala"],
  ["West Bengal Tenders", "West Bengal"],
  ["Odisha Tenders", "Odisha"],
  ["Bihar eProcurement", "Bihar"],
  ["Jharkhand Tenders", "Jharkhand"],
  ["Assam Tenders", "Assam"],
].map(([name, state]) => ({ name, state, kind: state === "National" ? "National" : "State" }));

function latestLogsByPortal(logs = []) {
  return logs.reduce((acc, log) => {
    if (!acc[log.portal]) acc[log.portal] = log;
    return acc;
  }, {});
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

function formatBytes(value = 0) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(unitIndex ? 1 : 0)} ${units[unitIndex]}`;
}

function endpointLabel(url = {}) {
  if (!url?.host) return "Not configured";
  const port = url.port ? `:${url.port}` : "";
  const database = url.database ? `/${url.database}` : "";
  return `${url.host}${port}${database}`;
}

function healthBadgeClass(status = "") {
  const normalized = String(status).toLowerCase();
  if (["ok", "ready", "active", "enabled", "protected"].includes(normalized)) return "success";
  if (["disabled", "not_checked", "optional_offline"].includes(normalized)) return "empty";
  return "retrying";
}

function readyText(value) {
  return value ? "Configured" : "Needs setup";
}

async function downloadBackup(backup, notify) {
  const response = await fetch(apiUrl(`/backups/${backup.id}/download`), {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!response.ok) {
    notify?.("Backup download failed", "error");
    return;
  }
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = backup.file_name;
  link.click();
  URL.revokeObjectURL(href);
}

export default function System({
  health,
  connections,
  scrapeLogs = [],
  stats,
  keywords = [],
  portals = [],
  backups = [],
  onRunPortal,
  portalRunPending,
  onCreateBackup,
  backupPending,
  onRestoreBackup,
  restorePending,
  notify,
}) {
  const [liveConnections, setLiveConnections] = useState(connections || null);
  const [streamLogs, setStreamLogs] = useState([]);
  const connectionData = liveConnections || connections;
  const portalCatalog = portals.length ? portals : fallbackPortals;
  const logMap = latestLogsByPortal(scrapeLogs);
  const latestBackup = backups?.[0] || health?.backup?.latest;
  const matchedBackups = (backups || []).filter((backup) => backup.backup_type === "matched").length;
  const fullBackups = (backups || []).filter((backup) => backup.backup_type === "all").length;

  useEffect(() => {
    if (connections) setLiveConnections(connections);
  }, [connections]);

  useEffect(() => {
    let active = true;

    async function loadConnections() {
      const token = getToken();
      if (!token) return;
      try {
        const response = await fetch(apiUrl("/health/connections"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) return;
        const data = await response.json();
        if (active) setLiveConnections(data);
      } catch {
        // Keep the last known connection state visible.
      }
    }

    loadConnections();
    const timer = window.setInterval(loadConnections, 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const token = getToken();
    if (!token) return undefined;
    const source = new EventSource(apiUrl(`/scrape/stream?token=${encodeURIComponent(token)}`));
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setStreamLogs((current) => [data, ...current].slice(0, 80));
      } catch {
        // Ignore malformed event lines.
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, []);

  const connectionCards = [
    {
      title: "PostgreSQL",
      value: connectionData?.database?.status || "checking",
      detail: endpointLabel(connectionData?.database?.url),
      meta: `${connectionData?.database?.active_tenders ?? stats?.total ?? 0} active tenders`,
      icon: Database,
    },
    {
      title: "Redis",
      value: connectionData?.redis?.status || "checking",
      detail: endpointLabel(connectionData?.redis?.url),
      meta: "Celery broker and cache layer",
      icon: Server,
    },
    {
      title: "ScraperAPI Proxy",
      value: connectionData?.proxy?.status || "checking",
      detail: connectionData?.proxy?.enabled ? "Proxy scraping enabled" : "Direct scraping mode",
      meta: readyText(connectionData?.proxy?.scraper_api_key_configured),
      icon: Network,
    },
    {
      title: "Playwright Browser",
      value: connectionData?.scraper?.use_playwright ? "enabled" : "disabled",
      detail: `${health?.scrape_methods?.dynamic_portals || 0} JavaScript portals`,
      meta: `${connectionData?.scraper?.portal_timeout_seconds || 60}s portal timeout`,
      icon: Workflow,
    },
    {
      title: "SendGrid Email",
      value: connectionData?.email?.status || "checking",
      detail: connectionData?.email?.from_email || "No sender",
      meta: `${connectionData?.email?.recipient_count || 0} alert recipients`,
      icon: Mail,
    },
    {
      title: "JWT Auth",
      value: connectionData?.auth?.status || "checking",
      detail: `${connectionData?.auth?.access_token_expire_minutes || 480} min sessions`,
      meta: connectionData?.auth?.secret_needs_rotation || connectionData?.auth?.admin_password_needs_rotation ? "Rotate before deployment" : "Secrets ready",
      icon: ShieldCheck,
    },
    {
      title: "Auto Scheduler",
      value: connectionData?.scraper?.auto_scrape_enabled ? "enabled" : "disabled",
      detail: `Every ${connectionData?.scraper?.interval_minutes || health?.auto_scrape_interval_minutes || 60} minutes`,
      meta: connectionData?.scraper?.runtime?.last_status || health?.scraper?.last_status || "waiting",
      icon: Workflow,
    },
    {
      title: "Backup Vault",
      value: connectionData?.backup?.last_error ? "attention" : connectionData?.backup?.enabled ? "protected" : "disabled",
      detail: connectionData?.backup?.directory || "backups",
      meta: `${connectionData?.backup?.retention_count || 30} retained snapshots`,
      icon: HardDrive,
    },
  ];
  const keywordCategories = Object.entries(
    (keywords || []).reduce((acc, item) => {
      const category = item.category || "General";
      acc[category] = (acc[category] || 0) + 1;
      return acc;
    }, {})
  ).sort((a, b) => b[1] - a[1]);

  return (
    <div className="pageGrid">
      <section className="panel">
        <div className="panelHead">
          <div>
            <h2>Proposal Technology Alignment</h2>
            <span className="muted">Architecture follows the uploaded proposal: portals to Celery, PostgreSQL, FastAPI, React, and alerts.</span>
          </div>
          <span className="statusBadge success">Industry Ready</span>
        </div>
        <div className="systemGrid">
          {components.map(({ title, detail, icon: Icon }) => (
            <div className="systemItem" key={title}>
              <Icon size={20} />
              <strong>{title}</strong>
              <span>{detail}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel connectionPanel">
        <div className="panelHead">
          <div>
            <h2>Live Connection Center</h2>
            <span className="muted">Safe production status for database, scraper, mail, auth, scheduler, and backups.</span>
          </div>
          <span className={`statusBadge ${healthBadgeClass(connectionData?.status)}`}>{connectionData?.status || "checking"}</span>
        </div>
        <div className="connectionGrid">
          {connectionCards.map(({ title, value, detail, meta, icon: Icon }) => (
            <article className="connectionCard" key={title}>
              <div className="connectionCardTop">
                <Icon size={19} />
                <span className={`statusBadge ${healthBadgeClass(value)}`}>{value}</span>
              </div>
              <strong>{title}</strong>
              <span>{detail}</span>
              <small>{meta}</small>
            </article>
          ))}
        </div>
        {connectionData?.warnings?.length > 0 && (
          <div className="connectionWarnings">
            {connectionData.warnings.map((warning) => <span key={warning}>{warning}</span>)}
          </div>
        )}
      </section>

      <section className="panel backupVaultPanel">
        <div className="panelHead">
          <div>
            <h2>Tender Backup Vault</h2>
            <span className="muted">Matched tenders are snapshotted after scrapes, with manual full-system backup and restore for recovery.</span>
          </div>
          <span className={`statusBadge ${health?.backup?.last_error ? "retrying" : "success"}`}>
            {health?.backup?.last_error ? "Backup warning" : "Protected"}
          </span>
        </div>

        <div className="backupSummaryGrid">
          <div className="backupSummaryCard">
            <HardDrive size={19} />
            <span>Backup mode</span>
            <strong>{health?.backup?.enabled ? "Automatic" : "Manual only"}</strong>
            <small>{health?.backup?.retention_count || 30} retained per type</small>
          </div>
          <div className="backupSummaryCard">
            <ShieldCheck size={19} />
            <span>Latest backup</span>
            <strong>{latestBackup ? formatApiDateTime(latestBackup.created_at, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Waiting"}</strong>
            <small>{latestBackup ? `${latestBackup.tender_count} records protected` : "Create a backup to initialize the vault"}</small>
          </div>
          <div className="backupSummaryCard">
            <ArchiveRestore size={19} />
            <span>Recovery sets</span>
            <strong>{matchedBackups + fullBackups}</strong>
            <small>{matchedBackups} matched / {fullBackups} full</small>
          </div>
        </div>

        {health?.backup?.last_error && <p className="backupWarning">{health.backup.last_error}</p>}

        <div className="backupActions">
          <button className="primarySmall" type="button" onClick={() => onCreateBackup?.("matched")} disabled={backupPending}>
            <Save size={16} />
            Back up matched tenders
          </button>
          <button className="secondary" type="button" onClick={() => onCreateBackup?.("all")} disabled={backupPending}>
            <Database size={16} />
            Back up all tenders
          </button>
        </div>

        <div className="backupList">
          {(backups || []).length === 0 && <span className="muted">No backup snapshots yet. The next live scrape will create one automatically.</span>}
          {(backups || []).slice(0, 8).map((backup) => (
            <article className="backupRow" key={backup.id}>
              <div>
                <strong>{backup.file_name}</strong>
                <span>{backup.reason} - {formatApiDateTime(backup.created_at)} - {formatBytes(backup.size_bytes)}</span>
              </div>
              <dl>
                <div><dt>Type</dt><dd>{backup.backup_type}</dd></div>
                <div><dt>Records</dt><dd>{backup.tender_count}</dd></div>
                <div><dt>Matched</dt><dd>{backup.matched_count}</dd></div>
              </dl>
              <div className="backupRowActions">
                <button className="iconTextButton" type="button" onClick={() => downloadBackup(backup, notify)} title="Download JSON backup">
                  <Download size={16} />
                  Download
                </button>
                <button className="iconTextButton" type="button" onClick={() => onRestoreBackup?.(backup.id)} disabled={restorePending} title="Restore missing or inactive tenders from this backup">
                  <RotateCcw size={16} />
                  Restore
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="split">
        <div className="panel">
          <div className="panelHead">
            <h2>Runtime Status</h2>
          </div>
          <dl className="statusList">
            <div><dt>Backend</dt><dd>{health?.status || "checking"}</dd></div>
            <div><dt>Auto scrape</dt><dd>{health?.auto_scrape_enabled ? "enabled" : "disabled"}</dd></div>
            <div><dt>Interval</dt><dd>{health?.auto_scrape_interval_minutes || 60} minutes</dd></div>
            <div><dt>Portal catalog</dt><dd>{health?.scraper?.portal_count || portalCatalog.length} portals</dd></div>
            <div><dt>Storage</dt><dd>{endpointLabel(connectionData?.database?.url)} via PostgreSQL</dd></div>
            <div><dt>Proxy</dt><dd>{connectionData?.proxy?.enabled ? "ScraperAPI enabled" : "Direct portal requests"}</dd></div>
            <div><dt>Email</dt><dd>{connectionData?.email?.status || "checking"}</dd></div>
          </dl>
        </div>

        <div className="panel">
          <div className="panelHead">
            <h2>Keyword Library</h2>
            <span className="countBadge">{keywords?.length || 0} active terms</span>
          </div>
          <div className="keywordCategoryGrid">
            {keywordCategories.length === 0 && <span className="muted">Keyword library is loading.</span>}
            {keywordCategories.map(([category, count]) => (
              <div className="keywordCategoryItem" key={category}>
                <strong>{category}</strong>
                <span>{count} keywords</span>
                <em>{stats?.by_category?.[category] || 0} matched tenders</em>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panelHead">
          <div>
            <h2>Live Scraper Console</h2>
            <span className="muted">Realtime messages from automatic and manual scraper runs.</span>
          </div>
          <span className="statusBadge success">SSE live</span>
        </div>
        <div className="liveConsole">
          {streamLogs.length === 0 && <span>Waiting for scraper events. Run a portal or wait for the next scheduled cycle.</span>}
          {streamLogs.map((line, index) => (
            <code key={`${line.at}-${index}`}>
              <time>{line.at ? formatApiDateTime(line.at, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--"}</time>
              {line.message}
            </code>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panelHead">
          <div>
            <h2>Portal Coverage Matrix</h2>
            <span className="muted">All proposal portals with fetched count, matched count, latest scrape state, and manual portal run.</span>
          </div>
        </div>
        <div className="portalMatrix">
          {portalCatalog.map((portal) => {
            const latest = logMap[portal.name];
            const fetched = stats?.by_portal?.[portal.name] || 0;
            const matched = stats?.matched_by_portal?.[portal.name] || 0;
            return (
              <article className="portalMatrixItem" key={portal.name}>
                <div>
                  <strong>{portal.name}</strong>
                  <span>{portal.state || "National"} - {portal.kind || "State"}</span>
                </div>
                <dl>
                  <div><dt>Fetched</dt><dd>{fetched}</dd></div>
                  <div><dt>Matched</dt><dd>{matched}</dd></div>
                </dl>
                <span className={`statusBadge ${latest?.status || "empty"}`}>{statusLabel(latest?.status)}</span>
                <button className="iconTextButton" type="button" onClick={() => onRunPortal?.(portal.name)} disabled={portalRunPending} title={`Run ${portal.name} scrape`}>
                  <PlayCircle size={16} />
                  Run
                </button>
              </article>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <div className="panelHead">
          <h2>Latest Scrape</h2>
        </div>
        <div className="logList compact">
          {(scrapeLogs || []).slice(0, 5).map((log) => (
            <div className="logRow" key={log.id}>
              <strong>{log.portal}</strong>
              <span className={`statusBadge ${log.status}`}>{statusLabel(log.status)}</span>
              <span>{log.tenders_found} new</span>
              <time>{formatApiDateTime(log.scraped_at)}</time>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

import { Activity, AlertTriangle, Bell, CheckCircle2, Clock3, Database, Eye } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import CategoryChips from "../components/CategoryChips.jsx";
import { formatApiDateTime, parseApiDate } from "../lib/time.js";

function formatScrapeError(message = "") {
  return message
    .replace(/https?:\/\/\S+/g, "portal URL")
    .replace(/For more information check:.*/i, "")
    .replace(/Client error '404 Not Found'/i, "Portal listing returned 404")
    .replace(/failed after retries:/i, "could not be reached:")
    .replace(/TimeoutError/i, "Portal timeout")
    .replace(/\[Errno 11001\] getaddrinfo failed/i, "DNS temporarily unavailable")
    .slice(0, 180)
    .trim();
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

function formatRelative(seconds) {
  if (seconds === null || seconds === undefined) return "Waiting";
  if (seconds < 30) return "just now";
  if (seconds < 90) return "1 min ago";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return minutes ? `${hours}h ${minutes}m ago` : `${hours}h ago`;
}

function formatCountdown(seconds) {
  if (seconds === null || seconds === undefined) return "Calculating";
  if (seconds <= 0) return "due now";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} min`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.ceil((seconds % 3600) / 60);
  return minutes >= 60 ? `${hours + 1}h` : `${hours}h ${minutes}m`;
}

function matchScore(tender) {
  return Number(tender?.raw_data?.match_score || 0);
}

function maxCount(entries) {
  return Math.max(1, ...entries.map(([, count]) => Number(count) || 0));
}

function barPercent(count, max) {
  if (!count) return "0%";
  return `${Math.max(4, Math.round((Number(count) / max) * 100))}%`;
}

export default function Dashboard({ stats, scrapeLogs = [], health, liveSync, liveEvents = [], onSelectTender }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const categories = Object.entries(stats?.by_category || {}).sort((a, b) => b[1] - a[1]);
  const portals = Object.entries(stats?.by_portal || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const matchedKeywords = Object.entries(stats?.by_keyword || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const matchedPortals = Object.entries(stats?.matched_by_portal || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const categoryMax = maxCount(categories);
  const portalMax = maxCount(portals);
  const keywordMax = maxCount(matchedKeywords);
  const matchedPortalMax = maxCount(matchedPortals);
  const logs = scrapeLogs || [];
  const latestLog = logs[0];
  const scraper = health?.scraper || {};
  const healthyRuns = logs.filter((log) => ["success", "empty", "cached"].includes(log.status)).length;
  const attentionRuns = logs.filter((log) => ["retrying", "failed", "temporarily_blocked"].includes(log.status)).length;
  const latestTime = latestLog?.scraped_at ? formatApiDateTime(latestLog.scraped_at, { hour: "2-digit", minute: "2-digit" }) : "Waiting";
  const serverTime = health?.server_time ? parseApiDate(health.server_time).getTime() : now;
  const clientDeltaSeconds = Math.max(0, Math.floor((now - serverTime) / 1000));
  const lastScrapeAge = health?.latest_scrape_age_seconds !== null && health?.latest_scrape_age_seconds !== undefined
    ? health.latest_scrape_age_seconds + clientDeltaSeconds
    : null;
  const nextScrapeSeconds = health?.next_scrape_in_seconds !== null && health?.next_scrape_in_seconds !== undefined
    ? Math.max(0, health.next_scrape_in_seconds - clientDeltaSeconds)
    : null;
  const exactScrapeTime = health?.latest_scrape ? formatApiDateTime(health.latest_scrape, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "Waiting";
  const matchedTenders = useMemo(() => [...(stats?.recent_matched || [])].sort((a, b) => matchScore(b) - matchScore(a)), [stats]);
  const matchRate = stats?.total ? Math.round(((stats?.matched || 0) / stats.total) * 100) : 0;
  const matchRateLabel = stats?.matched && stats?.total && matchRate === 0 ? "<1% qualified" : `${matchRate}% qualified`;

  return (
    <div className="pageGrid">
      <section className="dashboardHero">
        <div>
          <span className="dashboardEyebrow">Live operations</span>
          <h2>Procurement intelligence command center</h2>
          <p>Monitor scraper activity, keyword matches, portal coverage, and recently qualified opportunities from one working dashboard.</p>
        </div>
        <div className="heroStatusGrid">
          <div className="heroStatusItem">
            <CheckCircle2 size={18} />
            <strong>{healthyRuns}</strong>
            <span>healthy portal checks</span>
          </div>
          <div className="heroStatusItem warning">
            <AlertTriangle size={18} />
            <strong>{attentionRuns}</strong>
            <span>need attention</span>
          </div>
          <div className="heroStatusItem">
            <Clock3 size={18} />
            <strong>{scraper.running ? "Running" : formatRelative(lastScrapeAge)}</strong>
            <span>{scraper.running ? "scrape in progress" : `last scrape ${exactScrapeTime}`}</span>
          </div>
          <div className="heroStatusItem liveFresh">
            <Clock3 size={18} />
            <strong>{scraper.running ? "Live" : formatCountdown(nextScrapeSeconds)}</strong>
            <span>{scraper.running ? "checking portals now" : `next ${scraper.interval_minutes || health?.auto_scrape_interval_minutes || 120} min run`}</span>
          </div>
        </div>
      </section>

      <section className="metricBand">
        <div className="metric">
          <Database size={20} />
          <span>Total active tenders</span>
          <strong>{stats?.total || 0}</strong>
        </div>
        <div className="metric">
          <CheckCircle2 size={20} />
          <span>Matched tenders</span>
          <strong>{stats?.matched || 0}</strong>
          <small>{matchRateLabel}</small>
        </div>
        <div className="metric">
          <Database size={20} />
          <span>Unmatched stored</span>
          <strong>{stats?.unmatched || 0}</strong>
        </div>
        <div className="metric">
          <Activity size={20} />
          <span>Unclassified</span>
          <strong>{stats?.unclassified || 0}</strong>
        </div>
        <div className="metric">
          <Bell size={20} />
          <span>New today</span>
          <strong>{stats?.new_today || 0}</strong>
        </div>
        <div className="metric">
          <Eye size={20} />
          <span>Documents</span>
          <strong>{stats?.processed_documents || 0}</strong>
          <small>{stats?.queued_documents || 0} queued / {stats?.failed_documents || 0} failed</small>
        </div>
      </section>

      <section className="panel realtimePanel">
        <div className="panelHead">
          <div>
            <h2>Realtime Scraper Stream</h2>
            <span className="muted">{liveSync?.message || "Waiting for live scraper events"}</span>
          </div>
          <span className={`statusBadge ${health?.scraper?.running ? "success" : "cached"}`}>
            {health?.scraper?.running ? "running now" : "standing by"}
          </span>
        </div>
        <div className="liveConsole dashboardConsole">
          {liveEvents.length === 0 && <span>Live portal messages will appear here as soon as a scrape starts.</span>}
          {liveEvents.slice(0, 8).map((event, index) => (
            <code key={`${event.at}-${index}`}>
              <time>{event.at ? formatApiDateTime(event.at, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--"}</time>
              {event.message}
            </code>
          ))}
        </div>
      </section>

      <section className="split">
        <div className="panel">
          <div className="panelHead">
            <div>
              <h2>Category Coverage</h2>
              <span className="muted">Scaled against the highest category count</span>
            </div>
          </div>
          <div className="barList">
            {categories.length === 0 && <span className="muted">No category matches yet. Matching starts as soon as proposal keywords appear in tender text.</span>}
            {categories.map(([category, count]) => (
              <div className="barRow" key={category}>
                <span>{category}</span>
                <div
                  role="progressbar"
                  aria-label={`${category}: ${count} tenders`}
                  aria-valuenow={count}
                  aria-valuemin="0"
                  aria-valuemax={categoryMax}
                  title={`${category}: ${count} tenders`}
                  style={{ "--value": barPercent(count, categoryMax) }}
                />
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panelHead">
            <div>
              <h2>Portal Coverage</h2>
              <span className="muted">Fetched tenders by source portal</span>
            </div>
          </div>
          <div className="barList">
            {portals.length === 0 && <span className="muted">No portal tender data has been stored yet.</span>}
            {portals.map(([portal, count]) => (
              <div className="barRow portal" key={portal}>
                <span>{portal}</span>
                <div
                  role="progressbar"
                  aria-label={`${portal}: ${count} tenders`}
                  aria-valuenow={count}
                  aria-valuemin="0"
                  aria-valuemax={portalMax}
                  title={`${portal}: ${count} tenders`}
                  style={{ "--value": barPercent(count, portalMax) }}
                />
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="split">
        <div className="panel">
          <div className="panelHead">
            <div>
              <h2>Matched Keywords</h2>
              <span className="muted">Keywords that produced real qualified tenders</span>
            </div>
          </div>
          <div className="barList">
            {matchedKeywords.length === 0 && <span className="muted">No matched keywords in the current live tender set.</span>}
            {matchedKeywords.map(([keyword, count]) => (
              <div className="barRow keyword" key={keyword}>
                <span>{keyword}</span>
                <div
                  role="progressbar"
                  aria-label={`${keyword}: ${count} matched tenders`}
                  aria-valuenow={count}
                  aria-valuemin="0"
                  aria-valuemax={keywordMax}
                  title={`${keyword}: ${count} matched tenders`}
                  style={{ "--value": barPercent(count, keywordMax) }}
                />
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panelHead">
            <div>
              <h2>Matched Portals</h2>
              <span className="muted">Portals currently producing qualified opportunities</span>
            </div>
          </div>
          <div className="barList">
            {matchedPortals.length === 0 && <span className="muted">No portal has a qualified tender yet.</span>}
            {matchedPortals.map(([portal, count]) => (
              <div className="barRow portal" key={portal}>
                <span>{portal}</span>
                <div
                  role="progressbar"
                  aria-label={`${portal}: ${count} matched tenders`}
                  aria-valuenow={count}
                  aria-valuemin="0"
                  aria-valuemax={matchedPortalMax}
                  title={`${portal}: ${count} matched tenders`}
                  style={{ "--value": barPercent(count, matchedPortalMax) }}
                />
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panelHead">
          <h2>Live Scrape Status</h2>
          <span className="muted">Auto-refreshes every 15 seconds</span>
        </div>
        <div className="logList">
          {logs.length === 0 && <span className="muted">No scrape runs yet. Click Run live scrape.</span>}
          {logs.map((log) => (
            <div className={`logRow ${log.status}`} key={log.id}>
              <strong><span className={`statusDot ${log.status}`} />{log.portal}</strong>
              <span className={`statusBadge ${log.status}`}>{statusLabel(log.status)}</span>
              <span>{log.tenders_found} new</span>
              <time>{formatApiDateTime(log.scraped_at)}</time>
              {log.error_message && <small title={log.error_message}>{formatScrapeError(log.error_message)}</small>}
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panelHead">
          <div>
            <h2>Matched Opportunities</h2>
            <span className="muted">Ranked by keyword confidence and refreshed every 15 seconds</span>
          </div>
        </div>
        <div className="matchList">
          {matchedTenders.length === 0 && <span className="muted">No keyword-qualified tenders yet. The scraper is still storing all live tenders and will surface matches as soon as proposal keywords appear.</span>}
          {matchedTenders.map((tender) => (
            <button key={tender.id} type="button" onClick={() => onSelectTender(tender.id)}>
              <div className="matchCardTop">
                <strong>{tender.title}</strong>
                <span className="matchScore">{matchScore(tender) || 1}/100</span>
              </div>
              <span>{tender.portal} - {tender.state || "National"}</span>
              <CategoryChips categories={tender.categories} />
              <em>{(tender.raw_data?.match_reasons || tender.matched_keywords || []).slice(0, 2).join(" | ") || "Matched by proposal keyword"}</em>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

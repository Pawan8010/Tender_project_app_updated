import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Clock3, DatabaseZap, RefreshCw, ShieldCheck } from "lucide-react";
import ExportButtons from "../components/ExportButtons.jsx";
import FilterPanel from "../components/FilterPanel.jsx";
import SmartSearch from "../components/SmartSearch.jsx";
import TenderTable from "../components/TenderTable.jsx";
import { formatApiDateTime } from "../lib/time.js";

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

export default function Tenders({ filters, setFilters, stats, categories, data, health, scrapeLogs = [], liveSync, liveEvents = [], isFetching, error, selectedId, onSelect, notify }) {
  const pages = Math.max(1, Math.ceil((data?.total || 0) / (data?.limit || 20)));
  const scraper = health?.scraper || {};
  const healthyPortals = (scrapeLogs || []).filter((log) => ["success", "empty", "cached"].includes(log.status)).length;
  const warningPortals = (scrapeLogs || []).filter((log) => ["retrying", "failed", "temporarily_blocked"].includes(log.status)).length;
  const visibleCount = data?.results?.length || 0;
  const totalCount = data?.total || 0;
  const matchedCount = stats?.matched || 0;
  const lastScrapeLabel = health?.latest_scrape_age_seconds !== null && health?.latest_scrape_age_seconds !== undefined
    ? formatRelative(health.latest_scrape_age_seconds)
    : "Waiting";
  const nextRunLabel = scraper.running ? "running now" : formatCountdown(health?.next_scrape_in_seconds);
  const latestScrapeTime = health?.latest_scrape
    ? formatApiDateTime(health.latest_scrape, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "Waiting";

  function setPage(delta) {
    setFilters((current) => ({ ...current, page: Math.min(pages, Math.max(1, current.page + delta)) }));
  }

  return (
    <div className="pageGrid">
      <div className="panel">
        <div className="panelHead tenderHead">
          <div>
            <h2>Live Tender Feed</h2>
            <p>Fresh tenders from proposal portals, normalized into procurement-style rows with IDs, references, closing dates, and direct source actions.</p>
          </div>
          <ExportButtons filters={filters} notify={notify} />
        </div>

        <section className="tenderOpsStrip" aria-label="Live tender operations status">
          <div className="tenderOpsCard live">
            <DatabaseZap size={18} />
            <span>Total records</span>
            <strong>{stats?.total || health?.tender_count || 0}</strong>
            <small>{visibleCount} visible on this page</small>
          </div>
          <div className="tenderOpsCard">
            <ShieldCheck size={18} />
            <span>Matched tenders</span>
            <strong>{matchedCount}</strong>
            <small>{filters.matched_only ? "matched filter active" : "proposal keyword engine"}</small>
          </div>
          <div className="tenderOpsCard">
            <Clock3 size={18} />
            <span>Freshness</span>
            <strong>{lastScrapeLabel}</strong>
            <small>{latestScrapeTime}</small>
          </div>
          <div className={`tenderOpsCard ${scraper.running ? "running" : ""}`}>
            <RefreshCw size={18} />
            <span>Next scrape</span>
            <strong>{nextRunLabel}</strong>
            <small>{scraper.interval_minutes || health?.auto_scrape_interval_minutes || 60} min automation</small>
          </div>
          <div className={`tenderOpsCard ${warningPortals ? "warning" : "healthy"}`}>
            {warningPortals ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
            <span>Portal health</span>
            <strong>{healthyPortals}/{health?.scraper?.portal_count || 23}</strong>
            <small>{warningPortals ? `${warningPortals} retrying/monitored` : "all latest checks stable"}</small>
          </div>
        </section>

        {(isFetching || error || scraper.running) && (
          <div className={`queryNotice ${error ? "error" : scraper.running ? "running" : ""}`} role="status">
            {error ? (
              <>
                <AlertTriangle size={16} />
                <span>{error.message || "Could not refresh live tenders. Existing stored rows are still visible."}</span>
              </>
            ) : scraper.running ? (
              <>
                <RefreshCw size={16} />
                <span>Scraper is checking portals now. New or refreshed tenders will appear automatically.</span>
              </>
            ) : (
              <>
                <RefreshCw size={16} />
                <span>Refreshing live tender rows from the backend.</span>
              </>
            )}
          </div>
        )}

        <div className="feedLiveStrip" role="status">
          <div>
            <span className={`statusDot ${scraper.running ? "success" : "cached"}`} />
            <strong>{scraper.running ? "Scraping all portals now" : "Realtime feed active"}</strong>
            <small>{liveSync?.message || "The tender table refreshes automatically from the live backend."}</small>
          </div>
          <div className="feedLiveEvents">
            {liveEvents.slice(0, 3).map((event, index) => (
              <span key={`${event.at}-${index}`}>{event.message}</span>
            ))}
            {liveEvents.length === 0 && <span>Waiting for the next portal update.</span>}
          </div>
        </div>

        <SmartSearch
          notify={notify}
          onSearchPhrase={(phrase) => {
            setFilters((current) => ({ ...current, search: phrase, category: "", page: 1 }));
            notify?.(`Searching live tenders for: ${phrase}`);
          }}
          onPick={(item) => {
            setFilters((current) => ({ ...current, search: item.term, category: item.category || current.category, page: 1 }));
            notify?.(`Smart search applied: ${item.term}`);
          }}
        />
        <FilterPanel filters={filters} setFilters={setFilters} stats={stats} categories={categories} />
        <TenderTable
          tenders={data?.results || []}
          selectedId={selectedId}
          onSelect={onSelect}
          search={filters.search}
          page={data?.page || filters.page || 1}
          limit={data?.limit || 20}
        />
        <div className="pagination">
          <span>
            Page {data?.page || 1} of {pages} - {totalCount} tenders
          </span>
          <div className="actions">
            <button className="iconButton" type="button" title="Previous page" onClick={() => setPage(-1)} disabled={filters.page <= 1}>
              <ChevronLeft size={18} />
            </button>
            <button className="iconButton" type="button" title="Next page" onClick={() => setPage(1)} disabled={filters.page >= pages}>
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

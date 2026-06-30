import { Bell, DatabaseZap, LayoutDashboard, ListFilter, LogOut, Radio, SearchCode, Server, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiUrl, clearToken, getRefreshToken, getToken } from "./lib/api.js";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import SessionTimer from "./components/SessionTimer.jsx";
import { ToastProvider, useToast } from "./components/Toast.jsx";
import Alerts from "./pages/Alerts.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Keywords from "./pages/Keywords.jsx";
import Landing from "./pages/Landing.jsx";
import Login from "./pages/Login.jsx";
import System from "./pages/System.jsx";
import Sessions from "./pages/Sessions.jsx";
import Tenders from "./pages/Tenders.jsx";
import CategoryChips from "./components/CategoryChips.jsx";
import useLang from "./hooks/useLang.js";
import { t } from "./lib/i18n.js";

const tabs = [
  { id: "dashboard", labelKey: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "tenders", labelKey: "tenders", label: "Tenders", icon: ListFilter },
  { id: "alerts", labelKey: "alerts", label: "Alerts", icon: Bell },
  { id: "keywords", labelKey: "keywords", label: "Keywords", icon: SearchCode },
  { id: "system", labelKey: "system", label: "System", icon: Server },
  { id: "sessions", labelKey: "sessions", label: "Sessions", icon: ShieldCheck },
];

const initialFilters = {
  search: "",
  category: "",
  state: "",
  portal: "",
  date_from: "",
  date_to: "",
  opening_from: "",
  opening_to: "",
  closing_from: "",
  closing_to: "",
  closing_in_days: "",
  matched_only: false,
  page: 1,
};

function openingDate(tender) {
  return tender?.opening_date || tender?.raw_data?.opening_date || "N/A";
}

function tenderLink(tender) {
  return tender?.open_url || tender?.tender_url;
}

function AppContent() {
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState(null);
  const [tab, setTab] = useState("dashboard");
  const [filters, setFilters] = useState(initialFilters);
  const [selectedId, setSelectedId] = useState(null);
  const [liveSync, setLiveSync] = useState({ status: "idle", message: "Waiting for live scraper events" });
  const [liveEvents, setLiveEvents] = useState([]);
  const [tokenVersion, setTokenVersion] = useState(0);
  useLang();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  useEffect(() => {
    if (getToken()) {
      api("/auth/me").then(setUser).catch(clearToken);
    }
  }, []);

  useEffect(() => {
    const bump = () => setTokenVersion((value) => value + 1);
    const clearUser = () => {
      setUser(null);
      setAuthMode("signin");
      bump();
    };
    window.addEventListener("auth-token-updated", bump);
    window.addEventListener("auth-token-cleared", clearUser);
    return () => {
      window.removeEventListener("auth-token-updated", bump);
      window.removeEventListener("auth-token-cleared", clearUser);
    };
  }, []);

  const enabled = Boolean(user);
  const statsQuery = useQuery({ queryKey: ["stats"], queryFn: () => api("/tenders/stats"), enabled, refetchInterval: 5000 });
  const keywordsQuery = useQuery({ queryKey: ["keywords"], queryFn: () => api("/keywords/"), enabled });
  const alertsQuery = useQuery({ queryKey: ["alerts"], queryFn: () => api("/alerts/"), enabled });
  const scrapeLogsQuery = useQuery({ queryKey: ["scrapeLogs"], queryFn: () => api("/scrape/logs?limit=23"), enabled, refetchInterval: 5000 });
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: () => api("/health"), enabled, refetchInterval: 5000 });
  const portalHealthQuery = useQuery({ queryKey: ["portalHealth"], queryFn: () => api("/health/portals"), enabled, refetchInterval: 15000 });
  const aiDashboardQuery = useQuery({ queryKey: ["aiDashboard"], queryFn: () => api("/dashboard/ai"), enabled, refetchInterval: 15000 });
  const connectionsQuery = useQuery({ queryKey: ["connections"], queryFn: () => api("/health/connections"), enabled, refetchInterval: 15000 });
  const portalsQuery = useQuery({ queryKey: ["portals"], queryFn: () => api("/scrape/portals"), enabled });
  const backupsQuery = useQuery({ queryKey: ["backups"], queryFn: () => api("/backups/"), enabled, refetchInterval: 30000 });
  const sessionsQuery = useQuery({ queryKey: ["sessions"], queryFn: () => api("/auth/sessions"), enabled, refetchInterval: 15000 });
  const adminSessionsQuery = useQuery({ queryKey: ["adminSessions"], queryFn: () => api("/auth/admin/sessions"), enabled: enabled && user?.role === "admin", refetchInterval: 15000 });
  const scraperRunning = Boolean(healthQuery.data?.scraper?.running);
  const tenderQuery = useQuery({
    queryKey: ["tenders", filters],
    queryFn: () => api(`/tenders/?${new URLSearchParams(Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== ""))).toString()}`),
    enabled,
    refetchInterval: 5000,
  });
  const detailQuery = useQuery({
    queryKey: ["tender", selectedId],
    queryFn: () => api(`/tenders/${selectedId}`),
    enabled: enabled && Boolean(selectedId),
  });

  useEffect(() => {
    if (!enabled) {
      setLiveSync({ status: "idle", message: "Sign in to connect live scraper events" });
      return undefined;
    }

    const token = getToken();
    if (!token) return undefined;

    let refreshTimer = null;
    const invalidateLiveData = () => {
      window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["stats"] });
        queryClient.invalidateQueries({ queryKey: ["tenders"] });
        queryClient.invalidateQueries({ queryKey: ["scrapeLogs"] });
        queryClient.invalidateQueries({ queryKey: ["health"] });
        queryClient.invalidateQueries({ queryKey: ["portalHealth"] });
        queryClient.invalidateQueries({ queryKey: ["aiDashboard"] });
        queryClient.invalidateQueries({ queryKey: ["connections"] });
        queryClient.invalidateQueries({ queryKey: ["backups"] });
      }, 250);
    };

    const source = new EventSource(apiUrl(`/scrape/stream?token=${encodeURIComponent(token)}`));
    setLiveSync({ status: "connecting", message: "Connecting to live scraper" });

    source.onopen = () => {
      setLiveSync({ status: "connected", message: "Live scraper connected" });
    };
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const message = data.message || "Live scraper update received";
        setLiveSync({ status: message.toLowerCase().includes("failed") ? "warning" : "connected", message });
        setLiveEvents((current) => [data, ...current].slice(0, 24));
        invalidateLiveData();
        if (message.toLowerCase().includes("scrape cycle finished")) {
          notify(message);
        }
      } catch {
        setLiveSync({ status: "connected", message: "Live scraper update received" });
        invalidateLiveData();
      }
    };
    source.onerror = () => {
      setLiveSync({ status: "warning", message: "Live stream reconnecting" });
    };

    return () => {
      window.clearTimeout(refreshTimer);
      source.close();
    };
  }, [enabled, notify, queryClient, tokenVersion]);

  const scrapeMutation = useMutation({
    mutationFn: () => api("/scrape/start", { method: "POST" }),
    onSuccess: (data) => {
      notify(
        data.status === "already_running"
          ? "Scraper is already running"
          : data.message || "Live scraper started"
      );
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["tenders"] });
      queryClient.invalidateQueries({ queryKey: ["scrapeLogs"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
      queryClient.invalidateQueries({ queryKey: ["portalHealth"] });
      queryClient.invalidateQueries({ queryKey: ["aiDashboard"] });
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (error) => notify(error.message || "Scrape failed", "error"),
  });

  const cleanupMutation = useMutation({
    mutationFn: () => api("/scrape/demo-data", { method: "DELETE" }),
    onSuccess: (data) => {
      notify(`Removed ${data.deleted} demo tenders`);
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["tenders"] });
    },
    onError: (error) => notify(error.message || "Cleanup failed", "error"),
  });

  const portalScrapeMutation = useMutation({
    mutationFn: (portalName) => api(`/tenders/trigger/${encodeURIComponent(portalName)}`, { method: "POST" }),
    onSuccess: (data) => {
      notify(`${data.portal}: ${data.tenders_found} new, ${data.updated_tenders || 0} refreshed`);
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["tenders"] });
      queryClient.invalidateQueries({ queryKey: ["scrapeLogs"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
      queryClient.invalidateQueries({ queryKey: ["portalHealth"] });
      queryClient.invalidateQueries({ queryKey: ["aiDashboard"] });
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (error) => notify(error.message || "Portal scrape failed", "error"),
  });

  const backupMutation = useMutation({
    mutationFn: ({ backupType, reason }) => api(`/backups/create?${new URLSearchParams({ backup_type: backupType, reason }).toString()}`, { method: "POST" }),
    onSuccess: (data) => {
      notify(`${data.backup_type === "all" ? "Full tender" : "Matched tender"} backup created: ${data.tender_count} records`);
      queryClient.invalidateQueries({ queryKey: ["backups"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
      queryClient.invalidateQueries({ queryKey: ["portalHealth"] });
      queryClient.invalidateQueries({ queryKey: ["aiDashboard"] });
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (error) => notify(error.message || "Backup failed", "error"),
  });

  const restoreBackupMutation = useMutation({
    mutationFn: (backupId) => api(`/backups/${backupId}/restore`, { method: "POST" }),
    onSuccess: (data) => {
      notify(`Backup restore complete: ${data.restored} restored, ${data.updated} updated, ${data.skipped} already safe`);
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["tenders"] });
      queryClient.invalidateQueries({ queryKey: ["backups"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
      queryClient.invalidateQueries({ queryKey: ["portalHealth"] });
      queryClient.invalidateQueries({ queryKey: ["aiDashboard"] });
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (error) => notify(error.message || "Restore failed", "error"),
  });

  const documentProcessMutation = useMutation({
    mutationFn: () => api("/scrape/documents/process?limit=50", { method: "POST" }),
    onSuccess: (data) => {
      notify(`Document processing complete: ${data.processed || 0} processed, ${data.failed || 0} failed`);
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["tenders"] });
      queryClient.invalidateQueries({ queryKey: ["health"] });
      queryClient.invalidateQueries({ queryKey: ["portalHealth"] });
      queryClient.invalidateQueries({ queryKey: ["aiDashboard"] });
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (error) => notify(error.message || "Document processing failed", "error"),
  });

  const categories = useMemo(() => {
    const fromStats = Object.keys(statsQuery.data?.by_category || {});
    const fromKeywords = [...new Set((keywordsQuery.data || []).map((keyword) => keyword.category).filter(Boolean))];
    return [...new Set([...fromStats, ...fromKeywords])].sort();
  }, [statsQuery.data, keywordsQuery.data]);

  async function logout() {
    try {
      await api("/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: getRefreshToken() }),
      });
    } catch {
      // Local logout should still complete if the server session already expired.
    }
    clearToken();
    setUser(null);
    setAuthMode(null);
  }

  async function logoutAll() {
    try {
      await api("/auth/logout-all", { method: "POST" });
      notify("Logged out from all devices");
    } catch (error) {
      notify(error.message || "Logout all failed", "error");
    } finally {
      clearToken();
      setUser(null);
      setAuthMode(null);
    }
  }

  function selectTender(id) {
    setSelectedId(id);
    setTab("tenders");
  }

  if (!user && !authMode) return <Landing onAuth={setAuthMode} />;
  if (!user) return <Login initialMode={authMode} onBack={() => setAuthMode(null)} onLogin={setUser} />;

  return (
    <div className="appShell platformShell">
      <aside className="sidebar">
        <div className="appTitle">
          <DatabaseZap size={28} />
          <div>
            <strong>Apna Tender</strong>
            <span>Procurement command</span>
          </div>
        </div>
        <nav>
          {tabs.map(({ id, label, icon: Icon }) => (
            <button key={id} type="button" className={tab === id ? "active" : ""} onClick={() => setTab(id)} title={label}>
              <Icon size={18} />
              {t(tabs.find((item) => item.id === id)?.labelKey) || label}
            </button>
          ))}
        </nav>
        <button className="logout" type="button" onClick={logout} title="Sign out">
          <LogOut size={18} />
          {t("sign_out")}
        </button>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <h1>{t(tabs.find((item) => item.id === tab)?.labelKey) || tabs.find((item) => item.id === tab)?.label}</h1>
            <span>{user.email} - {user.role}</span>
          </div>
          <div className="actions">
            <span className={`liveSyncPill ${liveSync.status}`} title={liveSync.message}>
              <Radio size={15} />
              {liveSync.status === "connected" ? "Live" : liveSync.status === "connecting" ? "Connecting" : "Sync"}
            </span>
            <SessionTimer onExpired={() => setUser(null)} />
            <button className="secondary" type="button" onClick={() => cleanupMutation.mutate()} disabled={cleanupMutation.isPending} title="Remove seeded/sample tenders">
              <Trash2 size={17} />
              Clean sample data
            </button>
            <button className="primarySmall" type="button" onClick={() => scrapeMutation.mutate()} disabled={scrapeMutation.isPending || scraperRunning}>
              <DatabaseZap size={17} />
              {scrapeMutation.isPending || scraperRunning ? t("scraping") : t("run_scrape")}
            </button>
          </div>
        </header>

        {tab === "dashboard" && (
          <Dashboard
            stats={statsQuery.data}
            scrapeLogs={scrapeLogsQuery.data}
            health={healthQuery.data}
            portalHealth={portalHealthQuery.data}
            aiDashboard={aiDashboardQuery.data}
            liveSync={liveSync}
            liveEvents={liveEvents}
            onSelectTender={selectTender}
          />
        )}
        {tab === "tenders" && (
          <Tenders
            filters={filters}
            setFilters={setFilters}
            stats={statsQuery.data}
            categories={categories}
            data={tenderQuery.data}
            health={healthQuery.data}
            portalHealth={portalHealthQuery.data}
            connections={connectionsQuery.data}
            scrapeLogs={scrapeLogsQuery.data}
            liveSync={liveSync}
            liveEvents={liveEvents}
            isFetching={tenderQuery.isFetching}
            error={tenderQuery.error}
            selectedId={selectedId}
            onSelect={setSelectedId}
            notify={notify}
          />
        )}
        {tab === "alerts" && <Alerts alerts={alertsQuery.data} categories={categories} stats={statsQuery.data} notify={notify} user={user} />}
        {tab === "keywords" && <Keywords keywords={keywordsQuery.data} notify={notify} />}
        {tab === "sessions" && (
          <Sessions
            sessions={sessionsQuery.data || []}
            adminSessions={adminSessionsQuery.data || []}
            user={user}
            onRefresh={() => {
              queryClient.invalidateQueries({ queryKey: ["sessions"] });
              queryClient.invalidateQueries({ queryKey: ["adminSessions"] });
            }}
            onLogoutAll={logoutAll}
            notify={notify}
          />
        )}
        {tab === "system" && (
          <System
            health={healthQuery.data}
            connections={connectionsQuery.data}
            scrapeLogs={scrapeLogsQuery.data}
            stats={statsQuery.data}
            keywords={keywordsQuery.data}
            portals={portalsQuery.data}
            backups={backupsQuery.data}
            onRunPortal={(portalName) => portalScrapeMutation.mutate(portalName)}
            portalRunPending={portalScrapeMutation.isPending}
            onCreateBackup={(backupType) => backupMutation.mutate({ backupType, reason: backupType === "all" ? "manual-full" : "manual-matched" })}
            backupPending={backupMutation.isPending}
            onRestoreBackup={(backupId) => restoreBackupMutation.mutate(backupId)}
            restorePending={restoreBackupMutation.isPending}
            onProcessDocuments={() => documentProcessMutation.mutate()}
            documentProcessPending={documentProcessMutation.isPending}
            notify={notify}
          />
        )}
      </main>

      <aside className={`detailRail ${selectedId ? "open" : ""}`} aria-hidden={!selectedId}>
        {selectedId && (
          <button className="closeDetail" type="button" onClick={() => setSelectedId(null)}>
            Close
          </button>
        )}
        {selectedId && detailQuery.data && (
          <>
            <span className="eyebrow">{detailQuery.data.portal} - {detailQuery.data.state || "National"}</span>
            <h2>{detailQuery.data.title}</h2>
            <CategoryChips categories={detailQuery.data.categories} />
            {detailQuery.data.raw_data?.ai && (
              <div className="detailAiBox">
                <strong>AI tender intelligence</strong>
                <span>
                  {detailQuery.data.raw_data.ai.category || detailQuery.data.ai_category || "General"}
                  {detailQuery.data.raw_data.ai.confidence ? ` - ${Math.round(Number(detailQuery.data.raw_data.ai.confidence) * 100)}% confidence` : ""}
                </span>
                {detailQuery.data.raw_data.ai.summary && <p>{detailQuery.data.raw_data.ai.summary}</p>}
                {detailQuery.data.raw_data.ai.tags?.length > 0 && (
                  <div className="aiTagRow">
                    {detailQuery.data.raw_data.ai.tags.slice(0, 8).map((tag) => <em key={tag}>{tag}</em>)}
                  </div>
                )}
                {detailQuery.data.raw_data.ai.entities && (
                  <small>
                    {Object.entries(detailQuery.data.raw_data.ai.entities)
                      .filter(([, values]) => Array.isArray(values) && values.length > 0)
                      .slice(0, 3)
                      .map(([name, values]) => `${name.replaceAll("_", " ")}: ${values.slice(0, 3).join(", ")}`)
                      .join(" | ")}
                  </small>
                )}
              </div>
            )}
            <dl>
              <div><dt>Opening Date</dt><dd>{openingDate(detailQuery.data)}</dd></div>
              <div><dt>Published</dt><dd>{detailQuery.data.published_date || "N/A"}</dd></div>
              <div><dt>Closing Date</dt><dd>{detailQuery.data.closing_date || "N/A"}</dd></div>
              <div><dt>Estimated value</dt><dd>{detailQuery.data.estimated_value ? `INR ${detailQuery.data.estimated_value.toLocaleString("en-IN")}` : "N/A"}</dd></div>
              <div><dt>Keywords</dt><dd>{detailQuery.data.matched_keywords.join(", ") || "N/A"}</dd></div>
              <div><dt>Match score</dt><dd>{detailQuery.data.raw_data?.match_score ? `${detailQuery.data.raw_data.match_score}/100` : "N/A"}</dd></div>
              <div><dt>Summary</dt><dd>{detailQuery.data.raw_data?.ai?.summary || detailQuery.data.raw_data?.plain_summary || "N/A"}</dd></div>
            </dl>
            {detailQuery.data.raw_data?.match_reasons?.length > 0 && (
              <div className="matchReasonBox">
                <strong>Why it matched</strong>
                {detailQuery.data.raw_data.match_reasons.slice(0, 5).map((reason) => <span key={reason}>{reason}</span>)}
              </div>
            )}
            <p>{detailQuery.data.description}</p>
            {tenderLink(detailQuery.data) && (
              <a className="primaryLink" href={tenderLink(detailQuery.data)} target="_blank" rel="noreferrer">
                Open tender portal
              </a>
            )}
          </>
        )}
      </aside>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <ErrorBoundary>
        <AppContent />
      </ErrorBoundary>
    </ToastProvider>
  );
}

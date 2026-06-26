import { Laptop, LogOut, MonitorCheck, RotateCw, ShieldAlert, Smartphone, Trash2 } from "lucide-react";
import { api } from "../lib/api.js";
import { formatApiDateTime } from "../lib/time.js";

function isMobile(session) {
  return /android|ios|iphone|ipad/i.test(`${session.operating_system || ""} ${session.device_name || ""}`);
}

function status(session) {
  if (session.revoked) return "revoked";
  if (!session.is_active) return "expired";
  return "active";
}

export default function Sessions({ sessions = [], adminSessions = [], user, onRefresh, onLogoutAll, notify }) {
  async function revoke(session) {
    await api(`/auth/session/${encodeURIComponent(session.session_id)}`, { method: "DELETE" });
    notify?.(session.current ? "Current session revoked" : "Session revoked");
    onRefresh?.();
    if (session.current) onLogoutAll?.();
  }

  async function revokeOthers() {
    const others = sessions.filter((session) => !session.current && session.is_active && !session.revoked);
    await Promise.all(others.map((session) => api(`/auth/session/${encodeURIComponent(session.session_id)}`, { method: "DELETE" })));
    notify?.(`Revoked ${others.length} other sessions`);
    onRefresh?.();
  }

  const activeCount = sessions.filter((session) => session.is_active && !session.revoked).length;
  const revokedCount = sessions.filter((session) => session.revoked).length;
  const expiredCount = sessions.filter((session) => !session.is_active && !session.revoked).length;

  return (
    <div className="pageGrid">
      <section className="panel sessionHero">
        <div>
          <span className="dashboardEyebrow">Enterprise sessions</span>
          <h2>Device and session control</h2>
          <p>Review where your account is active, rotate access silently, and revoke sessions independently.</p>
        </div>
        <div className="sessionActions">
          <button className="secondary" type="button" onClick={onRefresh}>
            <RotateCw size={16} />
            Refresh
          </button>
          <button className="secondary" type="button" onClick={revokeOthers} disabled={activeCount <= 1}>
            <ShieldAlert size={16} />
            Log out other devices
          </button>
          <button className="primarySmall" type="button" onClick={onLogoutAll}>
            <LogOut size={16} />
            Log out all
          </button>
        </div>
      </section>

      <section className="metricBand">
        <div className="metric"><MonitorCheck size={20} /><span>Active sessions</span><strong>{activeCount}</strong></div>
        <div className="metric"><ShieldAlert size={20} /><span>Revoked</span><strong>{revokedCount}</strong></div>
        <div className="metric"><Trash2 size={20} /><span>Expired</span><strong>{expiredCount}</strong></div>
      </section>

      <section className="panel">
        <div className="panelHead">
          <div>
            <h2>Your Sessions</h2>
            <span className="muted">Each browser or device has its own refresh token and session id.</span>
          </div>
        </div>
        <div className="sessionList">
          {sessions.length === 0 && <span className="muted">No sessions loaded yet.</span>}
          {sessions.map((session) => {
            const Icon = isMobile(session) ? Smartphone : Laptop;
            return (
              <article className="sessionRow" key={session.session_id}>
                <Icon size={22} />
                <div>
                  <strong>{session.device_name || "Unknown device"} {session.current && <em>Current</em>}</strong>
                  <span>{session.ip_address || "No IP"} - {session.city || "Unknown city"} {session.country || ""}</span>
                  <small>Login {formatApiDateTime(session.login_time)} | Last activity {formatApiDateTime(session.last_activity_at)}</small>
                  <small>Expires {formatApiDateTime(session.session_expires_at)} | Refresh until {formatApiDateTime(session.refresh_expires_at)}</small>
                </div>
                <span className={`statusBadge ${status(session)}`}>{status(session)}</span>
                <button className="iconTextButton" type="button" onClick={() => revoke(session)} disabled={!session.is_active || session.revoked}>
                  <Trash2 size={16} />
                  Revoke
                </button>
              </article>
            );
          })}
        </div>
      </section>

      {user?.role === "admin" && (
        <section className="panel">
          <div className="panelHead">
            <div>
              <h2>Admin Session Monitor</h2>
              <span className="muted">Latest active, expired, and revoked sessions across users.</span>
            </div>
          </div>
          <div className="sessionList compactSessions">
            {adminSessions.length === 0 && <span className="muted">No admin session rows loaded.</span>}
            {adminSessions.slice(0, 100).map((session) => (
              <article className="sessionRow" key={`admin-${session.session_id}`}>
                <MonitorCheck size={20} />
                <div>
                  <strong>User #{session.user_id} - {session.device_name || "Unknown device"}</strong>
                  <span>{session.ip_address || "No IP"} - {session.browser || "Browser"} - {session.operating_system || "OS"}</span>
                  <small>Last activity {formatApiDateTime(session.last_activity_at)} | {session.last_api_request || "No API path"}</small>
                </div>
                <span className={`statusBadge ${status(session)}`}>{status(session)}</span>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

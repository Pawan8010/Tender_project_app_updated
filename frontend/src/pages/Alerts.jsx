import { BellPlus, MailCheck, Send, Trash2, Settings } from "lucide-react";
import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import CategoryChips from "../components/CategoryChips.jsx";

export default function Alerts({ alerts, categories, stats, notify, user }) {
  const queryClient = useQueryClient();
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [selectedPortals, setSelectedPortals] = useState([]);
  const portals = Object.keys(stats?.by_portal || {});

  const [smtpConfig, setSmtpConfig] = useState({
    gmail_user: "",
    gmail_app_password: "",
    smtp_host: "smtp.gmail.com",
    smtp_port: 465,
    alert_from_email: "",
    alert_to_emails: "",
  });
  const [loadingConfig, setLoadingConfig] = useState(false);
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (isAdmin) {
      setLoadingConfig(true);
      api("/alerts/email-config")
        .then((data) => {
          setSmtpConfig({
            gmail_user: data.gmail_user || "",
            gmail_app_password: data.gmail_app_password || "",
            smtp_host: data.smtp_host || "smtp.gmail.com",
            smtp_port: data.smtp_port || 465,
            alert_from_email: data.alert_from_email || "",
            alert_to_emails: data.alert_to_emails || "",
          });
        })
        .catch((err) => {
          console.error("Failed to fetch email config", err);
        })
        .finally(() => {
          setLoadingConfig(false);
        });
    }
  }, [isAdmin]);

  const createMutation = useMutation({
    mutationFn: () => api("/alerts/", { method: "POST", body: JSON.stringify({ categories: selectedCategories, portals: selectedPortals, email_enabled: true }) }),
    onSuccess: () => {
      setSelectedCategories([]);
      setSelectedPortals([]);
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      notify?.("Alert subscription saved");
    },
    onError: (error) => notify?.(error.message || "Could not save alert", "error"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => api(`/alerts/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      notify?.("Alert subscription deleted");
    },
    onError: (error) => notify?.(error.message || "Could not delete alert", "error"),
  });

  const testMutation = useMutation({
    mutationFn: () => api("/alerts/test", { method: "POST" }),
    onSuccess: (data) => notify?.(data?.message || "Test email action completed"),
    onError: (error) => notify?.(error.message || "Test email failed", "error"),
  });

  const pendingMutation = useMutation({
    mutationFn: () => api("/alerts/send-pending", { method: "POST" }),
    onSuccess: (data) => notify?.(data?.message || "Pending matched alerts processed"),
    onError: (error) => notify?.(error.message || "Could not send matched alerts", "error"),
  });

  const saveConfigMutation = useMutation({
    mutationFn: (config) => api("/alerts/email-config", { method: "POST", body: JSON.stringify(config) }),
    onSuccess: () => notify?.("Email configuration saved successfully"),
    onError: (error) => notify?.(error.message || "Failed to save configuration", "error"),
  });

  const digestMutation = useMutation({
    mutationFn: () => api("/alerts/digest", { method: "POST" }),
    onSuccess: (data) => notify?.(data?.message || "Daily digest sent successfully"),
    onError: (error) => notify?.(error.message || "Failed to send digest", "error"),
  });

  function toggle(value, list, setter) {
    setter(list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
  }

  return (
    <div className="pageGrid">
      <section className="panel">
        <div className="panelHead">
          <h2>Email Alert Subscriptions</h2>
          <div className="actions">
            <button className="secondary" type="button" onClick={() => testMutation.mutate()} disabled={testMutation.isPending}>
              <MailCheck size={17} />
              Test Email
            </button>
            <button className="secondary" type="button" onClick={() => pendingMutation.mutate()} disabled={pendingMutation.isPending}>
              <Send size={17} />
              {pendingMutation.isPending ? "Sending..." : "Send Matched"}
            </button>
            <button className="primarySmall" type="button" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
              <BellPlus size={17} />
              {createMutation.isPending ? "Adding..." : "Add"}
            </button>
          </div>
        </div>
        {testMutation.data?.message && <p className="muted">{testMutation.data.message}</p>}
        {pendingMutation.data?.message && <p className="muted">{pendingMutation.data.message}</p>}
        <div className="selectorGrid">
          <div>
            <h3>Categories</h3>
            <div className="checkGrid">
              {categories.map((category) => (
                <label key={category}>
                  <input type="checkbox" checked={selectedCategories.includes(category)} onChange={() => toggle(category, selectedCategories, setSelectedCategories)} />
                  {category}
                </label>
              ))}
            </div>
          </div>
          <div>
            <h3>Portals</h3>
            <div className="checkGrid">
              {portals.map((portal) => (
                <label key={portal}>
                  <input type="checkbox" checked={selectedPortals.includes(portal)} onChange={() => toggle(portal, selectedPortals, setSelectedPortals)} />
                  {portal}
                </label>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panelHead">
          <h2>Active Rules</h2>
        </div>
        <div className="ruleList">
          {(alerts || []).map((alert) => (
            <div className="rule" key={alert.id}>
              <div>
                <CategoryChips categories={alert.categories} />
                <span>{alert.portals.length ? alert.portals.join(", ") : "All portals"}</span>
              </div>
              <button className="iconButton danger" type="button" title="Delete alert" onClick={() => deleteMutation.mutate(alert.id)}>
                <Trash2 size={17} />
              </button>
            </div>
          ))}
        </div>
      </section>

      {isAdmin && (
        <section className="panel" style={{ gridColumn: "1 / -1", marginTop: "16px" }}>
          <div className="panelHead">
            <h2 style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <Settings size={20} />
              Email Server Configuration
            </h2>
            <div className="actions">
              <button 
                className="secondary" 
                type="button" 
                onClick={() => digestMutation.mutate()} 
                disabled={digestMutation.isPending}
              >
                <Send size={17} />
                {digestMutation.isPending ? "Sending..." : "Send Daily Digest"}
              </button>
              <button 
                className="primarySmall" 
                type="button" 
                onClick={() => saveConfigMutation.mutate(smtpConfig)} 
                disabled={saveConfigMutation.isPending}
              >
                <Settings size={17} />
                {saveConfigMutation.isPending ? "Saving..." : "Save Settings"}
              </button>
            </div>
          </div>
          {loadingConfig ? (
            <p className="muted" style={{ padding: "16px 0" }}>Loading configurations...</p>
          ) : (
            <div className="formGrid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "20px", marginTop: "20px" }}>
              <div className="formGroup" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--lp-text-secondary)" }}>
                  Gmail User (SMTP Username)
                </label>
                <input
                  type="email"
                  value={smtpConfig.gmail_user}
                  onChange={(e) => setSmtpConfig({ ...smtpConfig, gmail_user: e.target.value })}
                  placeholder="e.g. bhandaresandesh26@gmail.com"
                  style={{ padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--lp-border-color)", background: "white", outline: "none", fontSize: "0.95rem" }}
                />
              </div>
              
              <div className="formGroup" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--lp-text-secondary)" }}>
                  Gmail App Password
                </label>
                <input
                  type="password"
                  value={smtpConfig.gmail_app_password}
                  onChange={(e) => setSmtpConfig({ ...smtpConfig, gmail_app_password: e.target.value })}
                  placeholder="•••• •••• •••• ••••"
                  style={{ padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--lp-border-color)", background: "white", outline: "none", fontSize: "0.95rem" }}
                />
              </div>

              <div className="formGroup" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--lp-text-secondary)" }}>
                  SMTP Host
                </label>
                <input
                  type="text"
                  value={smtpConfig.smtp_host}
                  onChange={(e) => setSmtpConfig({ ...smtpConfig, smtp_host: e.target.value })}
                  placeholder="smtp.gmail.com"
                  style={{ padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--lp-border-color)", background: "white", outline: "none", fontSize: "0.95rem" }}
                />
              </div>

              <div className="formGroup" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--lp-text-secondary)" }}>
                  SMTP Port
                </label>
                <input
                  type="number"
                  value={smtpConfig.smtp_port}
                  onChange={(e) => setSmtpConfig({ ...smtpConfig, smtp_port: parseInt(e.target.value) || 465 })}
                  placeholder="465"
                  style={{ padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--lp-border-color)", background: "white", outline: "none", fontSize: "0.95rem" }}
                />
              </div>

              <div className="formGroup" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--lp-text-secondary)" }}>
                  Sender Email (From)
                </label>
                <input
                  type="email"
                  value={smtpConfig.alert_from_email}
                  onChange={(e) => setSmtpConfig({ ...smtpConfig, alert_from_email: e.target.value })}
                  placeholder="e.g. bhandaresandesh26@gmail.com"
                  style={{ padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--lp-border-color)", background: "white", outline: "none", fontSize: "0.95rem" }}
                />
              </div>

              <div className="formGroup" style={{ display: "flex", flexDirection: "column", gap: "6px", gridColumn: "1 / -1" }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--lp-text-secondary)" }}>
                  Recipient Emails (Default To, comma-separated)
                </label>
                <input
                  type="text"
                  value={smtpConfig.alert_to_emails}
                  onChange={(e) => setSmtpConfig({ ...smtpConfig, alert_to_emails: e.target.value })}
                  placeholder="e.g. user1@gmail.com, user2@gmail.com"
                  style={{ padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--lp-border-color)", background: "white", outline: "none", fontSize: "0.95rem" }}
                />
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

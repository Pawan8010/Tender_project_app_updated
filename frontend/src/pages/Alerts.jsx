import { BellPlus, MailCheck, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import CategoryChips from "../components/CategoryChips.jsx";

export default function Alerts({ alerts, categories, stats, notify }) {
  const queryClient = useQueryClient();
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [selectedPortals, setSelectedPortals] = useState([]);
  const portals = Object.keys(stats?.by_portal || {});

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
    </div>
  );
}

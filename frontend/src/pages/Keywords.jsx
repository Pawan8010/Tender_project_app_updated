import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.js";

const categoryOptions = ["Thermal", "NVD", "PTZ", "EOSS", "LRF", "Camera", "Border", "General", "Communication", "Protection", "Counter-UAV", "Sight"];

export default function Keywords({ keywords, notify }) {
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState("Thermal");

  const createMutation = useMutation({
    mutationFn: () => api("/keywords/", { method: "POST", body: JSON.stringify({ keyword, category, is_active: true }) }),
    onSuccess: () => {
      setKeyword("");
      queryClient.invalidateQueries({ queryKey: ["keywords"] });
      notify?.("Keyword added");
    },
    onError: (error) => notify?.(error.message || "Could not add keyword", "error"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }) => api(`/keywords/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keywords"] });
      notify?.("Keyword updated");
    },
    onError: (error) => notify?.(error.message || "Could not update keyword", "error"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => api(`/keywords/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["keywords"] });
      notify?.("Keyword deleted");
    },
    onError: (error) => notify?.(error.message || "Could not delete keyword", "error"),
  });

  function addKeyword(event) {
    event.preventDefault();
    if (!keyword.trim()) return;
    createMutation.mutate();
  }

  return (
    <div className="pageGrid">
      <section className="panel">
        <div className="panelHead">
          <h2>Add New Keyword</h2>
        </div>
        <form className="keywordForm" onSubmit={addKeyword}>
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="Keyword text" />
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            {categoryOptions.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
          <button className="primarySmall" type="submit" disabled={createMutation.isPending}>
            <Plus size={17} />
            {createMutation.isPending ? "Adding..." : "Add"}
          </button>
        </form>
      </section>

      <section className="panel">
        <div className="panelHead">
          <h2>Keyword Library</h2>
          <span className="countBadge">{(keywords || []).length}</span>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Keyword Text</th>
                <th>Category</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {(keywords || []).map((item) => (
                <tr key={item.id}>
                  <td data-label="Keyword"><strong>{item.keyword}</strong></td>
                  <td data-label="Category">{item.category || "General"}</td>
                  <td data-label="Status">
                    <label className="inlineToggle">
                      <input
                        type="checkbox"
                        checked={item.is_active}
                        onChange={(event) => updateMutation.mutate({ id: item.id, payload: { is_active: event.target.checked } })}
                      />
                      {item.is_active ? "Active" : "Inactive"}
                    </label>
                  </td>
                  <td data-label="Action">
                    <button className="iconButton danger" type="button" title="Delete keyword" onClick={() => deleteMutation.mutate(item.id)}>
                      <Trash2 size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

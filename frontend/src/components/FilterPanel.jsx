import { CalendarClock, Filter, RotateCcw, Search } from "lucide-react";

const emptyFilters = {
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

const filterLabels = {
  search: "Search",
  category: "Category",
  state: "State",
  portal: "Portal",
  date_from: "Published from",
  date_to: "Published to",
  opening_from: "Opening from",
  opening_to: "Opening to",
  closing_from: "Closing from",
  closing_to: "Closing to",
  closing_in_days: "Closing window",
  matched_only: "Matched only",
};

export default function FilterPanel({ filters, setFilters, stats, categories }) {
  const portals = Object.keys(stats?.by_portal || {});
  const states = Object.keys(stats?.by_state || {});
  const activeFilters = Object.entries(filters).filter(([key, value]) => {
    if (key === "page") return false;
    if (typeof value === "boolean") return value;
    return Boolean(value);
  });

  function update(key, value) {
    setFilters((current) => ({ ...current, [key]: value, page: 1 }));
  }

  function resetFilters() {
    setFilters(emptyFilters);
  }

  return (
    <section className="filterBand" aria-label="Tender filters">
      <div className="filterHeader">
        <div>
          <span className="filterEyebrow"><Filter size={14} /> Tender filters</span>
          <strong>Search and qualify live tenders</strong>
        </div>
        <div className="filterSummary">
          <span>{activeFilters.length ? `${activeFilters.length} active` : "No filters"}</span>
          <button className="iconTextButton" type="button" title="Reset filters" onClick={resetFilters} disabled={!activeFilters.length}>
            <RotateCcw size={16} />
            Reset
          </button>
        </div>
      </div>

      {activeFilters.length > 0 && (
        <div className="activeFilterChips" aria-label="Active filters">
          {activeFilters.map(([key, value]) => (
            <button type="button" key={key} onClick={() => update(key, typeof value === "boolean" ? false : "")}>
              {filterLabels[key] || key}: {typeof value === "boolean" ? "Yes" : value}
            </button>
          ))}
        </div>
      )}

      <div className="filterGrid">
        <label className="searchBox">
          <Search size={18} />
          <input
            value={filters.search}
            onChange={(event) => update("search", event.target.value)}
            placeholder="Search title, keyword, equipment, portal"
          />
        </label>
        <label className="selectField">
          <span>Category</span>
          <select value={filters.category} onChange={(event) => update("category", event.target.value)}>
            <option value="">All categories</option>
            {categories.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
        </label>
        <label className="selectField">
          <span>Portal</span>
          <select value={filters.portal} onChange={(event) => update("portal", event.target.value)}>
            <option value="">All portals</option>
            {portals.map((portal) => (
              <option key={portal} value={portal}>
                {portal}
              </option>
            ))}
          </select>
        </label>
        <label className="selectField">
          <span>State</span>
          <select value={filters.state} onChange={(event) => update("state", event.target.value)}>
            <option value="">All states</option>
            {states.map((state) => (
              <option key={state} value={state}>
                {state}
              </option>
            ))}
          </select>
        </label>
        <label className="dateField">
          <span>Published from</span>
          <input type="date" value={filters.date_from} onChange={(event) => update("date_from", event.target.value)} />
        </label>
        <label className="dateField">
          <span>Published to</span>
          <input type="date" value={filters.date_to} onChange={(event) => update("date_to", event.target.value)} />
        </label>
        <label className="dateField">
          <span>Opening from</span>
          <input type="date" value={filters.opening_from} onChange={(event) => update("opening_from", event.target.value)} />
        </label>
        <label className="dateField">
          <span>Opening to</span>
          <input type="date" value={filters.opening_to} onChange={(event) => update("opening_to", event.target.value)} />
        </label>
        <label className="dateField">
          <span>Closing from</span>
          <input type="date" value={filters.closing_from} onChange={(event) => update("closing_from", event.target.value)} />
        </label>
        <label className="dateField">
          <span>Closing to</span>
          <input type="date" value={filters.closing_to} onChange={(event) => update("closing_to", event.target.value)} />
        </label>
        <label className="selectField">
          <span>Quick closing</span>
          <select value={filters.closing_in_days} onChange={(event) => update("closing_in_days", event.target.value)}>
            <option value="">Any closing date</option>
            <option value="7">Closing in 7 days</option>
            <option value="30">Closing in 30 days</option>
          </select>
        </label>
        <label className="toggleBox">
          <input type="checkbox" checked={filters.matched_only} onChange={(event) => update("matched_only", event.target.checked)} />
          <span>
            <strong>Matched only</strong>
            <em>Show keyword-qualified tenders</em>
          </span>
        </label>
      </div>
      <div className="dateFilterHint">
        <CalendarClock size={15} />
        <span>Opening and closing filters use the dates captured from the original portal rows.</span>
      </div>
    </section>
  );
}

import { Brain, Search } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api.js";

export default function SmartSearch({ onPick, onSearchPhrase, notify }) {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("both");
  const [results, setResults] = useState([]);
  const [liveResults, setLiveResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [scraping, setScraping] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (q.trim().length < 2) return;
    setLoading(true);
    try {
      const data = await api(`/ml/search?${new URLSearchParams({ q, mode, limit: "12" }).toString()}`);
      setResults(data.results || []);
      onSearchPhrase?.(q.trim());
    } catch (error) {
      notify?.(error.message || "Smart search failed", "error");
    } finally {
      setLoading(false);
    }
  }

  async function scrapeNow() {
    if (q.trim().length < 2) return;
    setScraping(true);
    setLiveResults([]);
    try {
      notify?.("Starting live scraper and searching current tenders...");
      const started = await api("/scrape/start", { method: "POST" });
      const data = await api(`/tenders/?${new URLSearchParams({ search: q.trim(), limit: "8", page: "1" }).toString()}`);
      setLiveResults(data.results || []);
      onSearchPhrase?.(q.trim());
      notify?.(`${started.message || "Live scraper started"} Showing ${data.total || 0} current matching rows while fresh portal updates arrive.`);
    } catch (error) {
      notify?.(error.message || "Live scrape search failed", "error");
    } finally {
      setScraping(false);
    }
  }

  return (
    <section className="smartSearch">
      <form onSubmit={submit}>
        <Brain size={18} />
        <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Smart search: thermal optic, drone jammer, night equipment..." />
        <select value={mode} onChange={(event) => setMode(event.target.value)}>
          <option value="both">Both</option>
          <option value="semantic">Semantic</option>
          <option value="fuzzy">Fuzzy</option>
        </select>
        <button className="primarySmall" type="submit" disabled={loading}>
          <Search size={16} />
          {loading ? "Searching..." : "Search tenders"}
        </button>
      </form>
      {q.trim().length > 1 && (
        <div className="smartSearchActions">
          <button className="smartPhraseButton" type="button" onClick={() => onSearchPhrase?.(q.trim())}>
            Search stored tenders for "{q.trim()}"
          </button>
          <button className="smartPhraseButton live" type="button" onClick={scrapeNow} disabled={scraping}>
            {scraping ? "Starting live scrape..." : "Start live scrape + search"}
          </button>
        </div>
      )}
      {liveResults.length > 0 && (
        <div className="liveSearchResults">
          <strong>Fresh scrape matches</strong>
          {liveResults.map((item) => (
            <button key={item.id} type="button" onClick={() => onSearchPhrase?.(q.trim())}>
              <span>{item.title}</span>
              <small>{item.portal} - closes {item.closing_date || "N/A"}</small>
            </button>
          ))}
        </div>
      )}
      {results.length > 0 && (
        <div className="smartResults">
          {results.map((item) => (
            <button key={`${item.term}-${item.method}`} type="button" onClick={() => onPick?.(item)}>
              <strong>{item.term}</strong>
              <span>{item.category}</span>
              <em>{Math.round(item.score * 100)}%</em>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

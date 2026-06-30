import { Brain, Clock, ExternalLink, Search, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import GoogleCseSearch from "./GoogleCseSearch.jsx";

export default function SmartSearch({ onPick, onSearchPhrase, onSelectTender, notify }) {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("both");
  const [results, setResults] = useState([]);
  const [aiResults, setAiResults] = useState([]);
  const [liveResults, setLiveResults] = useState([]);
  const [googleResults, setGoogleResults] = useState(null);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [scraping, setScraping] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [importingLink, setImportingLink] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [suggesting, setSuggesting] = useState(false);
  const [searchFocused, setSearchFocused] = useState(false);
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("tender_recent_searches") || "[]");
    } catch {
      return [];
    }
  });

  function visibleGoogleBlock(google) {
    if (!google) return null;
    if (google.provider === "local_index_primary" && !(google.results?.length || google.stored)) return null;
    return google;
  }

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setSuggestions([]);
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      setSuggesting(true);
      try {
        const data = await api(`/ml/suggest?${new URLSearchParams({ q: term, limit: "8" }).toString()}`);
        setSuggestions(data.suggestions || []);
      } catch {
        setSuggestions([]);
      } finally {
        setSuggesting(false);
      }
    }, 220);
    return () => window.clearTimeout(timer);
  }, [q]);

  function rememberSearch(term) {
    const clean = term.trim();
    if (clean.length < 2) return;
    const next = [clean, ...recentSearches.filter((item) => item.toLowerCase() !== clean.toLowerCase())].slice(0, 6);
    setRecentSearches(next);
    localStorage.setItem("tender_recent_searches", JSON.stringify(next));
  }

  function chooseSuggestion(text) {
    setQ(text);
    setSearchFocused(false);
    onSearchPhrase?.(text);
  }

  function highlightedText(text, terms = []) {
    const source = String(text || "");
    const cleanTerms = [...new Set(terms.filter(Boolean).map((term) => String(term).trim()).filter((term) => term.length > 1))].slice(0, 10);
    if (!cleanTerms.length || !source) return source;
    const pattern = new RegExp(`(${cleanTerms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "ig");
    return source.split(pattern).map((part, index) =>
      cleanTerms.some((term) => term.toLowerCase() === part.toLowerCase()) ? <mark key={`${part}-${index}`}>{part}</mark> : part
    );
  }

  async function submit(event) {
    event.preventDefault();
    if (q.trim().length < 2) return;
    setLoading(true);
    setSearched(true);
    setGoogleResults(null);
    try {
      rememberSearch(q.trim());
      const data = await api(`/ml/unified?${new URLSearchParams({ q: q.trim(), mode, tender_limit: "12", web_limit: "8", store_web: "false", include_google: "true" }).toString()}`);
      setGoogleResults(visibleGoogleBlock(data.google));
      setAiResults(data.ai_tenders?.results || []);
      setResults(data.related_terms?.results || []);
      onSearchPhrase?.(q.trim());
      notify?.(`Fast AI search completed for "${q.trim()}"; Google related results are connected.`);
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
    setSearched(true);
    try {
      notify?.("Starting the full 23-portal scraper in the background. Search will use the current index immediately.");
      const data = await api("/scrape/start", { method: "POST" });
      const unifiedData = await api(`/ml/unified?${new URLSearchParams({ q: q.trim(), mode, tender_limit: "12", web_limit: "8", store_web: "false", include_google: "true" }).toString()}`);
      setLiveResults([]);
      setGoogleResults(visibleGoogleBlock(unifiedData.google));
      setAiResults(unifiedData.ai_tenders?.results || []);
      setResults(unifiedData.related_terms?.results || []);
      onSearchPhrase?.(q.trim());
      notify?.(`${data.message || "Full scraper started."} Current index returned ${unifiedData.ai_tenders?.results?.length || 0} AI matches.`);
    } catch (error) {
      notify?.(error.message || "Live scrape search failed", "error");
    } finally {
      setScraping(false);
    }
  }

  async function discoverFromGoogle() {
    setDiscovering(true);
    setSearched(true);
    try {
      notify?.("Running Google portal discovery across configured tender portals...");
      const data = await api("/scrape/google-discovery/run?limit_per_portal=1&store=true", { method: "POST" });
      setLiveResults(
        (data.results || []).map((item) => ({
          id: item.id,
          title: item.title,
          portal: item.portal,
          closing_date: null,
        }))
      );
      if (q.trim().length > 1) {
        const unifiedData = await api(`/ml/unified?${new URLSearchParams({ q: q.trim(), mode, tender_limit: "12", web_limit: "10", store_web: "true", include_google: "true" }).toString()}`);
        setGoogleResults(visibleGoogleBlock(unifiedData.google));
        setAiResults(unifiedData.ai_tenders?.results || []);
        setResults(unifiedData.related_terms?.results || []);
        onSearchPhrase?.(q.trim());
      }
      notify?.(`Google discovery complete: ${data.discovered || 0} URLs found, ${data.new || 0} new, ${data.updated || 0} updated.`);
    } catch (error) {
      notify?.(error.message || "Google discovery failed", "error");
    } finally {
      setDiscovering(false);
    }
  }

  async function importWebResult(item) {
    if (!item?.link) return;
    setImportingLink(item.link);
    try {
      const saved = await api("/ml/web/import", {
        method: "POST",
        body: JSON.stringify({
          query: q.trim(),
          title: item.title,
          link: item.link,
          snippet: item.snippet || "",
          display_link: item.display_link || "",
        }),
      });
      notify?.(`Web result saved to tender system (${saved.status}).`);
      setGoogleResults((current) => {
        if (!current?.results) return current;
        return {
          ...current,
          stored: (current.stored || 0) + 1,
          results: current.results.map((result) =>
            result.link === item.link
              ? { ...result, tracked: true, stored_id: saved.id, store_status: saved.status }
              : result
          ),
        };
      });
      onSearchPhrase?.(q.trim());
    } catch (error) {
      notify?.(error.message || "Could not save web result", "error");
    } finally {
      setImportingLink("");
    }
  }

  return (
    <section className="smartSearch">
      <form onSubmit={submit}>
        <Brain size={18} />
        <div className="googleLikeSearchBox">
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => window.setTimeout(() => setSearchFocused(false), 160)}
            placeholder="Search tenders like Google: AI tenders in Maharashtra, road work under 5 crore..."
          />
          {searchFocused && (suggestions.length > 0 || recentSearches.length > 0 || suggesting) && (
            <div className="searchSuggestPanel">
              {suggesting && <div className="suggestLoading">Finding tender suggestions...</div>}
              {suggestions.map((item) => (
                <button key={`${item.text}-${item.type}`} type="button" onClick={() => chooseSuggestion(item.text)}>
                  <Search size={14} />
                  <span>{highlightedText(item.text, [q])}</span>
                  <em>{item.type === "ai_expansion" ? "AI expansion" : "Tender index"}</em>
                </button>
              ))}
              {recentSearches.length > 0 && (
                <div className="recentSearchGroup">
                  <strong>Recent searches</strong>
                  {recentSearches.map((item) => (
                    <button key={item} type="button" onClick={() => chooseSuggestion(item)}>
                      <Clock size={14} />
                      <span>{item}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        <select value={mode} onChange={(event) => setMode(event.target.value)}>
          <option value="both">AI + fuzzy</option>
          <option value="semantic">AI terms</option>
          <option value="fuzzy">Fuzzy terms</option>
        </select>
        <button className="primarySmall" type="submit" disabled={loading}>
          <Search size={16} />
          {loading ? "Searching..." : "Fast AI search"}
        </button>
      </form>
      {q.trim().length > 1 && (
        <div className="smartSearchActions">
          <button className="smartPhraseButton" type="button" onClick={() => onSearchPhrase?.(q.trim())}>
            Search stored tenders for "{q.trim()}"
          </button>
          <button className="smartPhraseButton live" type="button" onClick={scrapeNow} disabled={scraping}>
            {scraping ? "Starting scraper..." : "Start full scraper"}
          </button>
          <button className="smartPhraseButton" type="button" onClick={discoverFromGoogle} disabled={discovering}>
            {discovering ? "Discovering..." : "Google portal discovery"}
          </button>
          <span className="smartSearchHint">Fast search ranks local tenders first, then shows related Google tender results for discovery/import.</span>
        </div>
      )}
      <GoogleCseSearch query={q.trim()} />
      {googleResults && (
        <div className="liveSearchResults googleSearchResults">
          <strong>Google related tender results</strong>
          {googleResults.message && <p className="googleStoreStatus">{googleResults.message}</p>}
          {googleResults.stored > 0 && <p className="googleStoreStatus">Saved {googleResults.stored} Google results into this tender system for AI search.</p>}
          {googleResults.results?.length > 0 ? (
            googleResults.results.map((item) => (
              <div className="webResultRow" key={item.link}>
                <a href={item.link} target="_blank" rel="noreferrer">
                  <span>{item.title}</span>
                  <small>{item.display_link || item.link}</small>
                  {item.snippet && <em>{item.snippet}</em>}
                </a>
                <div className="webResultActions">
                  <button className="miniActionButton" type="button" onClick={() => importWebResult(item)} disabled={importingLink === item.link || item.tracked}>
                    {importingLink === item.link ? "Saving..." : item.tracked ? `Saved #${item.stored_id}` : "Track in system"}
                  </button>
                </div>
              </div>
            ))
          ) : (
            <a href={googleResults.search_url} target="_blank" rel="noreferrer">
              <span>Open live web results for "{q.trim()}"</span>
              <small>{googleResults.configured ? googleResults.message || "No Google API results returned" : "Google API keys are not configured locally"}</small>
              <em>Local tender index remains primary. Google is used for related public tender discovery.</em>
            </a>
          )}
          <a className="googleOpenLink" href={googleResults.search_url} target="_blank" rel="noreferrer">
            <ExternalLink size={14} />
            Open full web search
          </a>
        </div>
      )}
      {aiResults.length > 0 && (
        <div className="liveSearchResults aiSearchResults">
          <strong>AI semantic tender matches</strong>
          {aiResults.map((item) => (
            <button key={item.id} type="button" onClick={() => onSelectTender?.(item.id)}>
              <span>{highlightedText(item.title, item.matched_terms || [])}</span>
              <small>
                {item.portal} - {item.state || "National"} - {item.department || item.organization || "Public tender"} - {item.ai_category || "General"}
              </small>
              <div className="aiResultMeta">
                <b>
                  <Sparkles size={13} />
                  {item.confidence ?? Math.round((item.score || 0) * 100)}% confidence
                </b>
                {item.tender_status && <i>{item.tender_status}</i>}
                {item.estimated_value ? <i>INR {Number(item.estimated_value).toLocaleString("en-IN")}</i> : null}
                {item.closing_date && <i>Closes {item.closing_date}</i>}
              </div>
              {item.snippet && <em>{highlightedText(item.snippet, item.matched_terms || [])}</em>}
              {item.ai_summary && <p>{highlightedText(item.ai_summary, item.matched_terms || [])}</p>}
              {item.ai_tags?.length > 0 && (
                <div className="aiSearchTags">
                  {item.ai_tags.slice(0, 6).map((tag) => (
                    <span key={tag}>{highlightedText(tag, item.matched_terms || [])}</span>
                  ))}
                </div>
              )}
            </button>
          ))}
        </div>
      )}
      {loading && (
        <div className="searchSkeletons">
          <span />
          <span />
          <span />
        </div>
      )}
      {liveResults.length > 0 && (
        <div className="liveSearchResults">
          <strong>Fresh scrape matches</strong>
          {liveResults.map((item) => (
            <button key={item.id} type="button" onClick={() => onSelectTender?.(item.id)}>
              <span>{item.title}</span>
              <small>{item.portal} - closes {item.closing_date || "N/A"}</small>
            </button>
          ))}
        </div>
      )}
      {results.length > 0 && (
        <div className="smartResults">
          <strong className="smartResultsTitle">Related AI terms</strong>
          {results.map((item) => (
            <button key={`${item.term}-${item.method}`} type="button" onClick={() => onPick?.(item)}>
              <strong>{item.term}</strong>
              <span>{item.category}</span>
              <em>{Math.round(item.score * 100)}%</em>
            </button>
          ))}
        </div>
      )}
      {searched && !loading && !scraping && !googleResults && aiResults.length === 0 && liveResults.length === 0 && (
        <div className="smartEmpty">No semantic matches found yet. Run full live scrape to refresh all portals, then AI search again.</div>
      )}
    </section>
  );
}

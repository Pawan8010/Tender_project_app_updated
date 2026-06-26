import { ExternalLink, Eye, GitCompare } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api.js";

function daysLeft(closingDate) {
  if (!closingDate) return "N/A";
  const diff = Math.ceil((new Date(closingDate) - new Date()) / 86400000);
  if (diff < 0) return "Closed";
  if (diff === 0) return "Today";
  return `${diff} days`;
}

function daysLeftClass(closingDate) {
  if (!closingDate) return "neutral";
  const diff = Math.ceil((new Date(closingDate) - new Date()) / 86400000);
  if (diff < 7) return "danger";
  if (diff <= 14) return "warning";
  return "success";
}

function openingDate(tender) {
  return tender.opening_date || tender.raw_data?.opening_date || "N/A";
}

function tenderLink(tender) {
  return tender.open_url || tender.tender_url;
}

function bracketValues(text = "") {
  return [...String(text).matchAll(/\[([^\]]+)\]/g)].map((match) => match[1].trim()).filter(Boolean);
}

function tenderNumber(tender) {
  const raw = tender.raw_data || {};
  const brackets = bracketValues(tender.description);
  return tender.bid_number || raw.bid_number || raw.tender_display_id || (brackets.length >= 3 ? brackets[2] : "") || raw.tender_number || `TW-${String(tender.id).padStart(5, "0")}`;
}

function referenceNumber(tender) {
  const raw = tender.raw_data || {};
  const brackets = bracketValues(tender.description);
  return tender.reference_number || raw.nit_id || raw.procurement_id || (brackets.length >= 2 ? brackets[1] : "") || raw.tender_number || raw.bid_number || tender.tender_id || "N/A";
}

function departmentName(tender) {
  const raw = tender.raw_data || {};
  const hasBracketDepartment = /\]\s*[^\]]+$/.test(String(tender.description || ""));
  const afterBrackets = hasBracketDepartment ? String(tender.description || "").replace(/^.*\]\s*/, "").replace(/\|\|/g, " | ").trim() : "";
  return tender.department || tender.buyer || tender.organization || raw.department || raw.buyer || afterBrackets || tender.state || tender.portal || "N/A";
}

function timeLeft(closingDate) {
  if (!closingDate) return "N/A";
  const closing = new Date(`${closingDate}T23:59:59`);
  const diff = closing.getTime() - Date.now();
  if (Number.isNaN(diff)) return "N/A";
  if (diff <= 0) return "Closed";
  const totalMinutes = Math.floor(diff / 60000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  return `${String(days).padStart(2, "0")}:${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function descriptionMeta(tender) {
  const keywords = tender.matched_keywords?.length ? tender.matched_keywords.slice(0, 3).join(", ") : "No matched keyword";
  return `${tender.portal}${tender.state ? ` - ${tender.state}` : ""} | ${keywords}`;
}

function plainSummary(tender) {
  return tender.raw_data?.plain_summary || "";
}

function matchScore(tender) {
  const score = Number(tender.raw_data?.match_score || 0);
  return Number.isFinite(score) && score > 0 ? score : null;
}

function highlightText(text, query) {
  if (!query?.trim()) return text;
  const escaped = query.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = String(text).split(new RegExp(`(${escaped})`, "ig"));
  return parts.map((part, index) => (
    part.toLowerCase() === query.trim().toLowerCase() ? <mark key={`${part}-${index}`}>{part}</mark> : part
  ));
}

export default function TenderTable({ tenders, selectedId, onSelect, search = "", page = 1, limit = 20 }) {
  const [similar, setSimilar] = useState(null);

  async function loadSimilar(event, tender) {
    event.stopPropagation();
    const data = await api(`/ml/similar/${tender.id}`);
    setSimilar(data);
  }

  return (
    <>
      <div className="tableWrap procurementTableWrap">
        <table className="procurementTable">
        <thead>
          <tr>
            <th>SL No.</th>
            <th>Tender/RFQ ID</th>
            <th>Tender Description</th>
            <th>Reference No.</th>
            <th>Department</th>
            <th>Opening Date</th>
            <th>Closing Date</th>
            <th>Time left (DD:HH:MM)</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {tenders.length === 0 && (
            <tr>
              <td colSpan="9" className="emptyCell">
                No live tenders fetched yet. Run live scrape or wait for the hourly proposal-aligned scraper.
              </td>
            </tr>
          )}
          {tenders.map((tender, index) => (
            <tr key={tender.id} className={selectedId === tender.id ? "selected" : ""} onClick={() => onSelect(tender.id)}>
              <td data-label="SL No." className="slCell">{(page - 1) * limit + index + 1}</td>
              <td data-label="Tender/RFQ ID" className="idCell">
                <strong>{highlightText(tenderNumber(tender), search)}</strong>
                {" "}
                <span className="portalMini">{tender.portal}</span>
              </td>
              <td data-label="Tender Description" className="descriptionCell">
                <strong>{highlightText(tender.title, search)}</strong>
                <span>{descriptionMeta(tender)}</span>
                {plainSummary(tender) && <small className="plainSummary">{plainSummary(tender)}</small>}
              </td>
              <td data-label="Reference No.">{referenceNumber(tender)}</td>
              <td data-label="Department">{departmentName(tender)}</td>
              <td data-label="Opening Date">{openingDate(tender)}</td>
              <td data-label="Closing Date">{tender.closing_date || "N/A"}</td>
              <td data-label="Time left">
                <span className={`daysBadge ${daysLeftClass(tender.closing_date)}`} title={daysLeft(tender.closing_date)}>
                  {timeLeft(tender.closing_date)}
                </span>
                {matchScore(tender) !== null && <small className="matchScore">Match {matchScore(tender)}</small>}
              </td>
              <td data-label="Action">
                <div className="tableActions">
                  <button className="iconButton small" type="button" title="View tender details" onClick={(event) => { event.stopPropagation(); onSelect(tender.id); }}>
                    <Eye size={15} />
                  </button>
                  <button className="iconButton small" type="button" title="Find similar tenders" onClick={(event) => loadSimilar(event, tender)}>
                    <GitCompare size={15} />
                  </button>
                  {tenderLink(tender) ? (
                    <a className="iconButton small" title="Open tender portal" href={tenderLink(tender)} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>
                      <ExternalLink size={15} />
                    </a>
                  ) : (
                    <span className="muted">N/A</span>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
        </table>
      </div>
      {similar && (
        <div className="modalShade" role="dialog" aria-modal="true">
          <div className="similarModal">
            <div className="panelHead">
              <div>
                <h2>Similar Tenders</h2>
                <span className="muted">{similar.target_title}</span>
              </div>
              <button className="closeDetail" type="button" onClick={() => setSimilar(null)}>Close</button>
            </div>
            <div className="similarList">
              {(similar.similar || []).length === 0 && <span className="muted">No similar tenders found yet.</span>}
              {(similar.similar || []).map((item) => (
                <button key={item.tender_id} type="button" onClick={() => { onSelect(item.tender_id); setSimilar(null); }}>
                  <strong>{item.title}</strong>
                  <span>{item.portal} - {Math.round(item.score * 100)}% similar</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

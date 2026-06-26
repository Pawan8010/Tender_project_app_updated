import { FileDown, Sheet } from "lucide-react";
import { useState } from "react";
import { exportUrl, getToken } from "../lib/api.js";

function filenameFromResponse(response, fallback) {
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/i);
  return match?.[1] || fallback;
}

export default function ExportButtons({ filters, notify }) {
  const [downloading, setDownloading] = useState(null);
  const [status, setStatus] = useState("");

  async function download(format) {
    const token = getToken();
    const url = exportUrl(format, filters);
    const fallbackName = format === "excel" ? "tenders.xlsx" : "tenders.csv";
    setDownloading(format);
    setStatus(`Preparing ${format === "excel" ? "Excel" : "CSV"} export...`);

    try {
      const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) {
        let detail = response.statusText || "Export failed";
        try {
          const body = await response.json();
          detail = body.detail || detail;
        } catch {
          // Keep the HTTP status text when the response is not JSON.
        }
        throw new Error(detail);
      }

      const blob = await response.blob();
      if (!blob.size) throw new Error("Export returned an empty file");

      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = filenameFromResponse(response, fallbackName);
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(href), 1500);

      const label = format === "excel" ? "Excel" : "CSV";
      setStatus(`${label} export ready`);
      notify?.(`${label} export downloaded`);
    } catch (error) {
      const message = error.message || "Export failed";
      setStatus(message);
      notify?.(message, "error");
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="exportBlock">
      <div className="actions exportActions" aria-label="Export live tender feed">
        <button type="button" className="secondary" onClick={() => download("csv")} disabled={Boolean(downloading)}>
          <FileDown size={17} />
          {downloading === "csv" ? "Preparing..." : "CSV"}
        </button>
        <button type="button" className="secondary" onClick={() => download("excel")} disabled={Boolean(downloading)}>
          <Sheet size={17} />
          {downloading === "excel" ? "Preparing..." : "Excel"}
        </button>
      </div>
      {status && <span className="exportStatus">{status}</span>}
    </div>
  );
}

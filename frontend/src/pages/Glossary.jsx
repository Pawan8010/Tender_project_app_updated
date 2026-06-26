import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { GLOSSARY } from "../lib/glossary.js";

export default function Glossary() {
  const [search, setSearch] = useState("");
  const rows = useMemo(
    () => Object.entries(GLOSSARY).filter(([term, text]) => `${term} ${text}`.toLowerCase().includes(search.toLowerCase())),
    [search]
  );
  return (
    <div className="pageGrid">
      <section className="panel">
        <div className="panelHead">
          <div>
            <h2>Help / Glossary</h2>
            <span className="muted">Plain English meaning for tender and technology terms.</span>
          </div>
        </div>
        <label className="searchBox">
          <Search size={18} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search glossary" />
        </label>
        <div className="glossaryGrid">
          {rows.map(([term, explanation]) => (
            <article key={term} className="glossaryCard">
              <strong>{term}</strong>
              <span>{explanation}</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

import { ExternalLink } from "lucide-react";

export default function GoogleCseSearch({ query }) {
  const term = query?.trim() || "government tender";
  const googleUrl = `https://www.google.com/search?q=${encodeURIComponent(`${term} tender procurement India`)}`;

  return (
    <div className="googleCsePanel googleFallbackPanel">
      <strong>
        <ExternalLink size={14} />
        Google related tender results
      </strong>
      <small>
        The platform shows API-powered Google related results below when Google allows the configured key.
        If the API is blocked, open the same tender query directly on Google.
      </small>
      <a className="googleOpenLink" href={googleUrl} target="_blank" rel="noreferrer">
        <ExternalLink size={14} />
        Open Google results for "{term}"
      </a>
    </div>
  );
}

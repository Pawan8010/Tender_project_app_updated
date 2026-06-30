import { TERM_HELP } from "../lib/termHelp.js";

export default function Tooltip({ term, children }) {
  const explanation = TERM_HELP[term];
  if (!explanation) return <>{children || term}</>;
  return (
    <span className="tooltipTerm">
      {children || term}
      <span className="tooltipBubble">
        <strong>{term}</strong>
        {explanation}
      </span>
    </span>
  );
}

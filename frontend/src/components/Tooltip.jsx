import { GLOSSARY } from "../lib/glossary.js";

export default function Tooltip({ term, children }) {
  const explanation = GLOSSARY[term];
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

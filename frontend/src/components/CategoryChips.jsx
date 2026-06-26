const colors = {
  Thermal: "chip thermal",
  NVD: "chip nvd",
  PTZ: "chip ptz",
  EOSS: "chip eoss",
  Camera: "chip camera",
  Sight: "chip sight",
  Communication: "chip comm",
  Protection: "chip protect",
  Security: "chip security",
  Tactical: "chip tactical",
  "Counter-UAV": "chip counter",
};

export default function CategoryChips({ categories = [] }) {
  if (!categories.length) return <span className="muted">Uncategorized</span>;
  return (
    <div className="chipRow">
      {categories.map((category) => (
        <span key={category} className={colors[category] || "chip"}>
          <Tooltip term={category}>{category}</Tooltip>
        </span>
      ))}
    </div>
  );
}
import Tooltip from "./Tooltip.jsx";

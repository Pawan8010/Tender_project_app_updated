import { Languages } from "lucide-react";
import { getLang, setLang, t } from "../lib/i18n.js";
import useLang from "../hooks/useLang.js";

export default function LanguageSwitcher() {
  const lang = useLang();
  return (
    <label className="languageSwitcher" title={t("language")}>
      <Languages size={16} />
      <select value={lang || getLang()} onChange={(event) => setLang(event.target.value)}>
        <option value="en">EN</option>
        <option value="hi">हिं</option>
        <option value="mr">मर</option>
      </select>
    </label>
  );
}

import { useEffect, useState } from "react";
import { getLang } from "../lib/i18n.js";

export default function useLang() {
  const [lang, setLanguage] = useState(getLang());
  useEffect(() => {
    const handler = (event) => setLanguage(event.detail);
    window.addEventListener("tw-lang-change", handler);
    return () => window.removeEventListener("tw-lang-change", handler);
  }, []);
  return lang;
}

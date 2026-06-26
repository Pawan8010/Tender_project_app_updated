export const TRANSLATIONS = {
  en: { dashboard: "Dashboard", tenders: "Tenders", alerts: "Alerts", keywords: "Keywords", system: "System", glossary: "Glossary", sign_out: "Sign out", run_scrape: "Run live scrape", scraping: "Scraping...", language: "Language" },
  hi: { dashboard: "डैशबोर्ड", tenders: "निविदाएं", alerts: "अलर्ट", keywords: "कीवर्ड", system: "सिस्टम", glossary: "शब्दकोश", sign_out: "लॉग आउट", run_scrape: "अभी स्क्रैप करें", scraping: "स्क्रैप हो रहा है...", language: "भाषा" },
  mr: { dashboard: "डॅशबोर्ड", tenders: "निविदा", alerts: "सूचना", keywords: "कीवर्ड", system: "प्रणाली", glossary: "शब्दकोश", sign_out: "बाहेर पडा", run_scrape: "आत्ता स्क्रॅप करा", scraping: "स्क्रॅप होत आहे...", language: "भाषा" },
};

let current = localStorage.getItem("tw_lang") || "en";

export function getLang() {
  return current;
}

export function setLang(lang) {
  current = TRANSLATIONS[lang] ? lang : "en";
  localStorage.setItem("tw_lang", current);
  window.dispatchEvent(new CustomEvent("tw-lang-change", { detail: current }));
}

export function t(key) {
  return TRANSLATIONS[current]?.[key] || TRANSLATIONS.en[key] || key;
}

import re
from dataclasses import dataclass

from app.config import CATEGORY_MAP, KEYWORDS


@dataclass(frozen=True)
class MatchRule:
    term: str
    category: str
    keyword: str
    weight: int = 8


KEYWORD_ALIASES = [
    MatchRule("cctv", "Camera", "Security Equipment", 7),
    MatchRule("cctv camera", "Camera", "Security Equipment", 10),
    MatchRule("ip camera", "Camera", "Optical Camera", 9),
    MatchRule("cameras", "Camera", "Optical Camera", 6),
    MatchRule("surveillance camera", "Camera", "Surveillance Equipment", 10),
    MatchRule("surveillance system", "EOSS", "Surveillance Equipment", 8),
    MatchRule("video surveillance", "Camera", "Surveillance Equipment", 9),
    MatchRule("security camera", "Camera", "Security Equipment", 9),
    MatchRule("body camera", "Camera", "Body Worn Camera", 8),
    MatchRule("dome camera", "Camera", "Optical Camera", 7),
    MatchRule("bullet camera", "Camera", "Optical Camera", 7),
    MatchRule("network camera", "Camera", "Optical Camera", 7),
    MatchRule("thermal scope", "Thermal", "Thermal Weapon Sight", 10),
    MatchRule("thermal imaging camera", "Thermal", "Thermal Imaging Camera", 12),
    MatchRule("long range thermal camera", "Thermal", "Long Range Thermal Imaging Camera", 12),
    MatchRule("long range thermal imaging camera", "Thermal", "Long Range Thermal Imaging Camera", 14),
    MatchRule("long range thermal imager", "Thermal", "Long Range Thermal Imaging Camera", 12),
    MatchRule("ir camera", "Thermal", "IR Camera", 10),
    MatchRule("night vision binocular", "NVD", "Night Vision Device", 10),
    MatchRule("night vision monocular", "NVD", "Night Vision Device", 10),
    MatchRule("image intensifier tube", "NVD", "Image Intensifier", 10),
    MatchRule("electro-optic", "EOSS", "Electro Optical Surveillance System", 9),
    MatchRule("electro optical", "EOSS", "Electro Optical Surveillance System", 10),
    MatchRule("eo/ir", "EOSS", "Electro Optical Surveillance System", 10),
    MatchRule("eo ir", "EOSS", "Electro Optical Surveillance System", 9),
    MatchRule("laser rangefinder", "EOSS", "Laser Range Finder", 10),
    MatchRule("laser range finder integrated sight", "EOSS", "Laser Range Finder Integrated Sight", 11),
    MatchRule("lrf integrated sight", "EOSS", "LRF Integrated Sight", 11),
    MatchRule("range finder", "EOSS", "Laser Range Finder", 8),
    MatchRule("surveillance radar", "EOSS", "Battlefield Surveillance Radar", 10),
    MatchRule("battlefield surveillance radar eo", "EOSS", "Battlefield Surveillance Radar EO", 11),
    MatchRule("ptz with eo payload", "PTZ", "PTZ with EO Payload", 11),
    MatchRule("border monitoring", "EOSS", "Border Surveillance System", 7),
    MatchRule("perimeter surveillance", "Security", "Perimeter Security", 9),
    MatchRule("perimeter protection", "Security", "Perimeter Security", 8),
    MatchRule("intrusion alarm", "Security", "Intrusion Detection", 8),
    MatchRule("intrusion detection system", "Security", "Intrusion Detection", 10),
    MatchRule("access control", "Security", "Security Equipment", 6),
    MatchRule("uhf radio", "Communication", "Handheld Radio", 8),
    MatchRule("vhf radio", "Communication", "Handheld Radio", 8),
    MatchRule("wireless set", "Communication", "Handheld Radio", 7),
    MatchRule("walky talky", "Communication", "Walkie Talkie", 8),
    MatchRule("walkie-talkie", "Communication", "Walkie Talkie", 9),
    MatchRule("drone jammer", "Counter-UAV", "Counter UAV", 10),
    MatchRule("uav detection", "Counter-UAV", "Drone Detection", 10),
    MatchRule("anti drone", "Counter-UAV", "Anti-Drone", 10),
    MatchRule("anti-drone", "Counter-UAV", "Anti-Drone", 10),
    MatchRule("counter drone", "Counter-UAV", "Counter UAV", 9),
    MatchRule("ballistic vest", "Protection", "Body Armor", 10),
    MatchRule("bulletproof jacket", "Protection", "Bulletproof", 10),
    MatchRule("bullet proof jacket", "Protection", "Bullet Proof", 10),
    MatchRule("riot gear", "Protection", "Riot Control", 8),
    MatchRule("combat helmet", "Protection", "Ballistic Helmet", 8),
    MatchRule("tactical kit", "Tactical", "Tactical Equipment", 8),
]

REGIONAL_TERM_ALIASES = {
    "थर्मल कैमरा": "thermal camera",
    "थर्मल कॅमेरा": "thermal camera",
    "थर्मल इमेजिंग कैमरा": "thermal imaging camera",
    "थर्मल इमेजिंग कॅमेरा": "thermal imaging camera",
    "लंबी दूरी थर्मल कैमरा": "long range thermal camera",
    "लांब पल्ल्याचा थर्मल कॅमेरा": "long range thermal camera",
    "सीसीटीवी": "cctv",
    "सीसीटीव्ही": "cctv",
    "सीसीटीवी कैमरा": "cctv camera",
    "सीसीटीव्ही कॅमेरा": "cctv camera",
    "निगरानी कैमरा": "surveillance camera",
    "निगरानी कॅमेरा": "surveillance camera",
    "सर्विलांस कैमरा": "surveillance camera",
    "सर्व्हेलन्स कॅमेरा": "surveillance camera",
    "रात्रि दृष्टि": "night vision",
    "नाइट विजन": "night vision",
    "नाईट व्हिजन": "night vision",
    "ड्रोन जैमर": "drone jammer",
    "ड्रोन जॅमर": "drone jammer",
    "एंटी ड्रोन": "anti drone",
    "अँटी ड्रोन": "anti drone",
    "वॉकी टॉकी": "walkie-talkie",
    "वाकी टाकी": "walkie-talkie",
    "बुलेट प्रूफ": "bullet proof",
    "बुलेटप्रूफ": "bulletproof",
}


NEGATIVE_PHRASES = (
    "security deposit",
    "security money",
    "earnest money",
    "scope of work",
)


def _expand_regional_terms(text: str) -> str:
    expanded = text or ""
    for regional, english in REGIONAL_TERM_ALIASES.items():
        if regional in expanded:
            expanded = f"{expanded} {english}"
    return expanded


def _normalize(text: str) -> str:
    expanded = _expand_regional_terms(text)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+/.-]+", " ", expanded.lower())).strip()


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize(phrase)
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])", normalized_text))


def analyze_tender_match(text: str) -> dict:
    normalized = _normalize(text)
    matched = []
    categories = set()
    aliases = []
    reasons = []
    score = 0

    for keyword in KEYWORDS:
        if _contains_phrase(normalized, keyword):
            matched.append(keyword)
            category = category_for_keyword(keyword)
            if category:
                categories.add(category)
            score += 12
            reasons.append(f"proposal keyword: {keyword}")

    for rule in KEYWORD_ALIASES:
        if _contains_phrase(normalized, rule.term):
            if rule.keyword not in matched:
                matched.append(rule.keyword)
            categories.add(rule.category)
            aliases.append(rule.term)
            score += rule.weight
            reasons.append(f"alias: {rule.term} -> {rule.keyword}")

    if any(_contains_phrase(normalized, phrase) for phrase in NEGATIVE_PHRASES):
        score = max(0, score - 4)

    return {
        "matched_keywords": list(dict.fromkeys(matched)),
        "categories": sorted(categories),
        "match_aliases": list(dict.fromkeys(aliases)),
        "match_reasons": list(dict.fromkeys(reasons))[:8],
        "match_score": min(score, 100),
    }


def match_keywords(text: str) -> tuple[list[str], list[str]]:
    result = analyze_tender_match(text)
    return result["matched_keywords"], result["categories"]


def category_for_keyword(keyword: str) -> str | None:
    lowered = keyword.lower()
    for category, terms in CATEGORY_MAP.items():
        if any(term.lower() in lowered or lowered in term.lower() for term in terms):
            return category
    return None


def _match_keywords_from_library(db, text: str) -> tuple[list[str], list[str], dict]:
    try:
        from app.services.ml_engine import ml_analyze_tender
        match_meta = ml_analyze_tender(text)
    except Exception:
        match_meta = analyze_tender_match(text)

    matched = list(match_meta.get("matched_keywords") or [])
    categories = set(match_meta.get("categories") or [])
    text_lower = (text or "").lower()

    from app.models import Keyword
    active_keywords = db.query(Keyword).filter(Keyword.is_active == True).all()
    for row in active_keywords:
        kw = (row.keyword or "").strip()
        if not kw:
            continue
        if kw.lower() in text_lower and kw not in matched:
            matched.append(kw)
            cat = row.category or category_for_keyword(kw)
            if cat:
                categories.add(cat)

    match_meta["matched_keywords"] = matched
    match_meta["categories"] = sorted(categories)
    return matched, match_meta["categories"], match_meta

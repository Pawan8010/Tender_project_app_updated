from __future__ import annotations

import math
import re
import importlib.util
from collections import Counter
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from app.config import settings


AI_SYNONYMS = {
    "ai": ["artificial intelligence", "machine learning", "deep learning", "computer vision", "nlp", "generative ai", "llm", "automation"],
    "ml": ["machine learning", "artificial intelligence", "predictive analytics", "model training"],
    "cloud": ["cloud", "saas", "iaas", "paas", "data center", "virtualization", "aws", "azure"],
    "drone": ["drone", "uav", "counter uav", "anti-drone", "aerial surveillance"],
    "cyber": ["cyber security", "security operations", "siem", "soc", "firewall", "endpoint security"],
    "road": ["road", "highway", "bridge", "pavement", "civil works"],
    "railway": ["railway", "rail", "track", "signalling", "station"],
}

CATEGORY_RULES = {
    "Construction": ["construction", "building", "civil", "road", "bridge", "pavement", "renovation"],
    "IT": ["software", "cloud", "server", "data center", "application", "erp", "ai", "machine learning", "computer vision"],
    "Electrical": ["electrical", "substation", "transformer", "cable", "lighting", "power supply"],
    "Healthcare": ["hospital", "medical", "diagnostic", "healthcare", "medicine", "ambulance"],
    "Education": ["school", "college", "university", "education", "classroom", "laboratory"],
    "Agriculture": ["agriculture", "irrigation", "farm", "seed", "fertilizer"],
    "Mining": ["mine", "mining", "coal", "mineral"],
    "Transport": ["transport", "bus", "vehicle", "fleet", "railway", "metro"],
    "Infrastructure": ["infrastructure", "road", "bridge", "water supply", "sewerage"],
    "Telecommunication": ["telecom", "networking", "fiber", "broadband", "router", "switch"],
    "Energy": ["solar", "renewable", "power", "energy", "ev charging"],
    "Manufacturing": ["manufacturing", "fabrication", "machinery", "workshop"],
    "Security": ["security", "surveillance", "cctv", "thermal", "drone", "radar", "defence"],
}

TAG_RULES = {
    "Cyber Security": ["cyber", "firewall", "siem", "soc", "endpoint", "security audit"],
    "Cloud": ["cloud", "saas", "iaas", "paas", "virtualization"],
    "AI": ["artificial intelligence", " ai ", "computer vision", "llm", "generative ai"],
    "ML": ["machine learning", "deep learning", "predictive model"],
    "IoT": ["iot", "sensor", "smart meter"],
    "Drone": ["drone", "uav", "anti-drone", "counter uav"],
    "Construction": ["construction", "building"],
    "Civil": ["civil", "road", "bridge", "pavement"],
    "Electrical": ["electrical", "transformer", "substation"],
    "Mechanical": ["mechanical", "machinery", "pump", "hvac"],
    "Healthcare": ["hospital", "medical", "healthcare"],
    "Education": ["school", "college", "university"],
    "Defence": ["defence", "army", "navy", "air force", "ordnance"],
    "Railway": ["railway", "rail", "track", "signalling"],
    "Solar": ["solar", "photovoltaic"],
    "EV": ["electric vehicle", "ev charging"],
    "Software": ["software", "application", "portal"],
    "Hardware": ["hardware", "server", "desktop", "laptop"],
    "Networking": ["network", "router", "switch", "fiber"],
}

ENTITY_PATTERNS = {
    "currency_amounts": r"(?:rs\.?|inr|₹)\s*[0-9][0-9,]*(?:\.\d+)?\s*(?:crore|cr|lakh|lac|million)?",
    "emails": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phones": r"(?:\+91[-\s]?)?[6-9]\d{9}",
}


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _lower(text: str | None) -> str:
    return f" {_clean(text).lower()} "


@lru_cache(maxsize=1)
def _model():
    if not settings()["ml_engine_enabled"]:
        return None
    if importlib.util.find_spec("sentence_transformers") is None:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(settings()["ml_model_name"])
    except Exception as exc:
        print(f"AI intelligence model unavailable, using deterministic NLP fallback: {exc}")
        return None


def text_embedding(text: str, dimensions: int = 384) -> list[float]:
    model = _model()
    text = _clean(text)[:8000]
    if model:
        try:
            vector = model.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
            return [round(float(value), 6) for value in vector.tolist()]
        except Exception:
            pass

    buckets = [0.0] * dimensions
    tokens = re.findall(r"[a-zA-Z0-9+#.-]{2,}", text.lower())
    for token in tokens:
        index = hash(token) % dimensions
        buckets[index] += 1.0
    norm = math.sqrt(sum(value * value for value in buckets)) or 1.0
    return [round(value / norm, 6) for value in buckets]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    return sum(left[i] * right[i] for i in range(size))


def expand_query(query: str) -> list[str]:
    lowered = _lower(query)
    terms = [query]
    for key, values in AI_SYNONYMS.items():
        if f" {key} " in lowered or any(value in lowered for value in values):
            terms.extend(values)
    return list(dict.fromkeys(_clean(term) for term in terms if _clean(term)))


def predict_category(text: str) -> tuple[str, float]:
    lowered = _lower(text)
    scored = []
    for category, terms in CATEGORY_RULES.items():
        score = sum(1 for term in terms if term in lowered)
        if score:
            scored.append((category, score / max(1, len(terms))))
    if not scored:
        return "General", 0.25
    category, score = max(scored, key=lambda item: item[1])
    return category, min(0.98, 0.45 + score)


def generate_tags(text: str, limit: int = 10) -> list[str]:
    lowered = _lower(text)
    tags = []
    for tag, terms in TAG_RULES.items():
        if any(term in lowered for term in terms):
            tags.append(tag)
    return tags[:limit]


def extract_entities(text: str) -> dict[str, list[str]]:
    cleaned = _clean(text)
    entities: dict[str, list[str]] = {}
    for name, pattern in ENTITY_PATTERNS.items():
        entities[name] = list(dict.fromkeys(re.findall(pattern, cleaned, flags=re.IGNORECASE)))[:20]

    label_map = {
        "organizations": ["organisation", "organization", "department", "ministry", "buyer"],
        "locations": ["state", "district", "location", "place of work"],
        "eligibility": ["eligibility", "qualification", "experience", "turnover"],
        "technical_requirements": ["technical", "specification", "scope of work", "supply of"],
    }
    for key, labels in label_map.items():
        values = []
        for label in labels:
            pattern = re.compile(rf"{label}\s*[:\-]?\s*(.{{3,180}})", re.IGNORECASE)
            for match in pattern.findall(cleaned):
                value = re.split(r"\s{2,}|\.|;", _clean(match))[0]
                if value:
                    values.append(value[:180])
        entities[key] = list(dict.fromkeys(values))[:10]
    return entities


def important_dates(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|\b\d{1,2}[-/][A-Za-z]{3}[-/]\d{2,4}\b", text)))[:20]


def summarize(text: str, max_sentences: int = 3) -> str:
    cleaned = _clean(text)
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    if len(sentences) <= max_sentences:
        return cleaned[:900]
    keywords = ("scope", "supply", "work", "eligibility", "technical", "bid", "tender")
    ranked = sorted(
        sentences,
        key=lambda sentence: sum(word in sentence.lower() for word in keywords),
        reverse=True,
    )
    return " ".join(ranked[:max_sentences])[:900]


def analyze_tender_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("raw_data") or {}
    text = " ".join(
        str(part)
        for part in [
            payload.get("title"),
            payload.get("description"),
            payload.get("department"),
            payload.get("organization"),
            payload.get("location"),
            payload.get("search_text"),
            raw.get("detail_text"),
            raw.get("document_text"),
            raw.get("pdf_text"),
            raw.get("ocr_text"),
        ]
        if part
    )
    category, confidence = predict_category(text)
    tags = generate_tags(text)
    entities = extract_entities(text)
    return {
        "category": category,
        "confidence": round(confidence, 3),
        "tags": tags,
        "entities": entities,
        "summary": summarize(text),
        "important_dates": important_dates(text),
        "embedding": text_embedding(text),
    }


def parse_natural_search(query: str) -> dict[str, Any]:
    lowered = _lower(query)
    core_query = query
    filters: dict[str, Any] = {}
    state_match = re.search(r"\bin\s+([a-zA-Z ]+?)(?:\s+under|\s+closing|\s+tenders|\s+for|$)", query, re.IGNORECASE)
    if state_match:
        filters["state"] = _clean(state_match.group(1)).title()
        core_query = re.sub(rf"\bin\s+{re.escape(state_match.group(1))}\b", " ", core_query, flags=re.IGNORECASE)
    value_match = re.search(r"under\s+([0-9.]+)\s*(crore|cr|lakh|lac)", lowered)
    if value_match:
        amount = float(value_match.group(1))
        unit = value_match.group(2)
        filters["max_value"] = amount * (10_000_000 if unit in {"crore", "cr"} else 100_000)
        core_query = re.sub(r"\bunder\s+[0-9.]+\s*(crore|cr|lakh|lac)\b", " ", core_query, flags=re.IGNORECASE)
    if "closing this week" in lowered:
        filters["closing_to"] = date.today() + timedelta(days=7)
        core_query = re.sub(r"\bclosing\s+this\s+week\b", " ", core_query, flags=re.IGNORECASE)
    elif "closing today" in lowered:
        filters["closing_to"] = date.today()
        core_query = re.sub(r"\bclosing\s+today\b", " ", core_query, flags=re.IGNORECASE)
    core_query = re.sub(r"\btenders?\b", " ", core_query, flags=re.IGNORECASE)
    core_query = _clean(core_query) or query
    filters["core_query"] = core_query
    filters["expanded_terms"] = expand_query(core_query)
    return filters


def trend_summary(tenders: list[Any]) -> dict[str, Any]:
    sectors = Counter()
    technologies = Counter()
    departments = Counter()
    states = Counter()
    for tender in tenders:
        raw = tender.raw_data or {}
        ai = raw.get("ai") or {}
        sectors.update([tender.ai_category or ai.get("category") or "General"])
        technologies.update(ai.get("tags") or [])
        if tender.department:
            departments.update([tender.department])
        if tender.state:
            states.update([tender.state])
    return {
        "trending_sectors": sectors.most_common(10),
        "trending_technologies": technologies.most_common(10),
        "active_departments": departments.most_common(10),
        "active_states": states.most_common(10),
    }

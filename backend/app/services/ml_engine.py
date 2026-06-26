from __future__ import annotations

from functools import lru_cache

from app.config import KEYWORDS, settings
from app.keywords import KEYWORD_ALIASES, analyze_tender_match, category_for_keyword


def _all_terms() -> list[str]:
    return list(dict.fromkeys([*KEYWORDS, *(rule.keyword for rule in KEYWORD_ALIASES), *(rule.term for rule in KEYWORD_ALIASES)]))


@lru_cache(maxsize=1)
def _load_model():
    if not settings()["ml_engine_enabled"]:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(settings()["ml_model_name"])
    except Exception as exc:
        print(f"ML model unavailable, using fuzzy matching only: {exc}")
        return None


def fuzzy_search(query: str, top_k: int = 10) -> list[dict]:
    try:
        from rapidfuzz import fuzz, process

        matches = process.extract(query, _all_terms(), scorer=fuzz.token_set_ratio, limit=top_k, score_cutoff=45)
        return [
            {"term": term, "score": round(score / 100, 3), "category": category_for_keyword(term) or "General", "method": "fuzzy"}
            for term, score, _index in matches
        ]
    except Exception:
        lowered = query.lower()
        results = []
        for term in _all_terms():
            term_lower = term.lower()
            if lowered in term_lower or term_lower in lowered:
                results.append({"term": term, "score": 0.65, "category": category_for_keyword(term) or "General", "method": "contains"})
        return results[:top_k]


@lru_cache(maxsize=1)
def _keyword_embeddings():
    model = _load_model()
    if not model:
        return None, []
    terms = _all_terms()
    return model.encode(terms, convert_to_numpy=True, normalize_embeddings=True), terms


def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    model = _load_model()
    if not model:
        return fuzzy_search(query, top_k)
    try:
        import numpy as np

        embeddings, terms = _keyword_embeddings()
        query_embedding = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
        scores = (query_embedding @ embeddings.T)[0]
        threshold = settings()["ml_similarity_threshold"]
        results = []
        for index in np.argsort(scores)[::-1][:top_k]:
            score = float(scores[index])
            if score < threshold:
                continue
            term = terms[int(index)]
            results.append({"term": term, "score": round(score, 3), "category": category_for_keyword(term) or "General", "method": "semantic"})
        return results or fuzzy_search(query, top_k)
    except Exception as exc:
        print(f"Semantic search failed, using fuzzy: {exc}")
        return fuzzy_search(query, top_k)


def ml_analyze_tender(text: str) -> dict:
    result = analyze_tender_match(text)
    if not settings()["ml_engine_enabled"]:
        return result
    semantic = semantic_search(text[:512], 5)
    extra_keywords = [item["term"] for item in semantic if item["term"] not in result["matched_keywords"] and item["score"] >= settings()["ml_similarity_threshold"]]
    categories = set(result["categories"])
    for item in semantic:
        if item["category"]:
            categories.add(item["category"])
    return {
        **result,
        "semantic_matches": extra_keywords,
        "matched_keywords": list(dict.fromkeys([*result["matched_keywords"], *extra_keywords])),
        "categories": sorted(categories),
        "match_score": min(100, int(result["match_score"]) + len(extra_keywords) * 3),
        "ml_used": True,
    }


def find_similar_titles(target_title: str, titles: list[str], top_k: int = 5) -> list[dict]:
    model = _load_model()
    if not model:
        target_terms = {word for word in target_title.lower().split() if len(word) > 3}
        scored = []
        for index, title in enumerate(titles):
            words = {word for word in title.lower().split() if len(word) > 3}
            score = len(target_terms & words) / max(1, len(target_terms | words))
            if score:
                scored.append({"index": index, "title": title, "score": round(score, 3), "method": "token"})
        return sorted(scored, key=lambda row: row["score"], reverse=True)[:top_k]
    try:
        import numpy as np

        vectors = model.encode([target_title, *titles], convert_to_numpy=True, normalize_embeddings=True)
        scores = (vectors[0:1] @ vectors[1:].T)[0]
        return [
            {"index": int(index), "title": titles[int(index)], "score": round(float(scores[index]), 3), "method": "semantic"}
            for index in np.argsort(scores)[::-1][:top_k]
            if float(scores[index]) >= 0.45
        ]
    except Exception:
        return []

import re
from typing import Set

def normalize_arabic(text: str) -> str:
    """Normalizes Arabic text for flexible matching."""
    if not text:
        return ""
    # Remove punctuation
    text = re.sub(r"[؟?!.,;:،؛\"'()\[\]{}ـ_\-/\\]", " ", text)
    # Normalize Alefs
    text = re.sub(r"[أإآ]", "ا", text)
    # Normalize Teh Marbuta
    text = re.sub(r"ة", "ه", text)
    # Normalize Yeh
    text = re.sub(r"ى", "ي", text)
    # Remove diacritics (Tashkeel)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    # Normalize spaces
    return re.sub(r"\s+", " ", text).strip().lower()


def get_arabic_keywords(text: str) -> Set[str]:
    """Extracts keywords with and without Arabic definite article (الـ)."""
    normalized = normalize_arabic(text)
    tokens = normalized.split()
    keywords = set()
    stopwords = {"من", "في", "على", "الى", "عن", "مع", "هو", "هي", "اليوم", "هل", "كم", "شن", "شنو", "يا", "ان", "لا"}

    for t in tokens:
        if t in stopwords:
            continue
        keywords.add(t)
        # Strip 'ال'
        if t.startswith("ال") and len(t) > 3:
            keywords.add(t[2:])
        # Handle 'دكتور' / 'دكتوره'
        if t in ["دكتور", "دكتوره", "د"]:
            continue

    return keywords


def is_fuzzy_match(source_text: str, query_text: str) -> bool:
    """Checks if there is a significant semantic/keyword overlap."""
    source_keys = get_arabic_keywords(source_text)
    query_keys = get_arabic_keywords(query_text)
    overlap = source_keys.intersection(query_keys)
    return len(overlap) > 0

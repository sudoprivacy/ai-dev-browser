"""Text matching algorithms for fuzzy element finding.

Supports multiple strategies:
- exact: Perfect string match
- contains: Substring match
- fuzzy: Edit distance (Levenshtein) via rapidfuzz or fallback
- semantic: Embedding-based similarity (placeholder for future implementation)

Usage:
    from ai_dev_browser.core.text_match import best_match, match_score

    score = match_score("Upload", "Upload files")
    result = best_match("Upload", ["Upload files", "Download", "Settings"])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

# Try to import rapidfuzz for fast edit distance, fall back to stdlib
try:
    from rapidfuzz.distance import Levenshtein

    def _levenshtein(a: str, b: str) -> int:
        return Levenshtein.distance(a, b)

except ImportError:
    # Pure Python fallback (slower but no dependencies)
    def _levenshtein(a: str, b: str) -> int:
        if len(a) < len(b):
            return _levenshtein(b, a)
        if len(b) == 0:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            curr = [i + 1]
            for j, cb in enumerate(b):
                cost = 0 if ca == cb else 1
                curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
            prev = curr
        return prev[-1]


@dataclass
class MatchResult:
    """Result of a text match operation."""

    text: str
    score: float
    strategy: str  # "exact", "contains", "fuzzy", "semantic"
    index: int  # Index in the original candidates list


def _match_score(query: str, target: str, case_sensitive: bool = False) -> tuple[float, str]:
    """Score how well query matches target.

    Uses parallel scoring: all strategies run independently,
    returns the highest score.

    Args:
        query: Search text
        target: Candidate text to match against
        case_sensitive: Whether to match case-sensitively

    Returns:
        Tuple of (score 0.0-1.0, strategy_name)
    """
    if not query or not target:
        return (0.0, "none")

    q = query if case_sensitive else query.lower()
    t = target if case_sensitive else target.lower()

    # Exact match
    if q == t:
        return (1.0, "exact")

    best_score = 0.0
    best_strategy = "none"

    # Contains: high base score + coverage bonus
    # "Upload" in "Upload files" should score much higher than edit distance
    if q in t:
        coverage = len(q) / len(t)
        # Prefix match gets higher base (more likely intentional)
        base = 0.85 if t.startswith(q) else 0.75
        score = base + 0.1 * coverage
        if score > best_score:
            best_score = score
            best_strategy = "contains"

    # Reverse contains: target is substring of query
    if t in q:
        coverage = len(t) / len(q)
        score = 0.7 + 0.1 * coverage
        if score > best_score:
            best_score = score
            best_strategy = "contains"

    # Edit distance: normalized similarity
    edit_dist = _levenshtein(q, t)
    max_len = max(len(q), len(t))
    edit_score = 1.0 - edit_dist / max_len
    if edit_score > best_score:
        best_score = edit_score
        best_strategy = "fuzzy"

    return (best_score, best_strategy)


def _best_match(
    query: str,
    candidates: Sequence[str],
    threshold: float = 0.4,
    case_sensitive: bool = False,
) -> Optional[MatchResult]:
    """Find the best matching candidate for a query.

    Args:
        query: Search text
        candidates: List of candidate strings to match against
        threshold: Minimum score to consider a match (0.0-1.0)
        case_sensitive: Whether to match case-sensitively

    Returns:
        MatchResult if a match is found above threshold, None otherwise
    """
    if not query or not candidates:
        return None

    best: Optional[MatchResult] = None

    for i, candidate in enumerate(candidates):
        if not candidate:
            continue
        score, strategy = _match_score(query, candidate, case_sensitive)
        if score >= threshold and (best is None or score > best.score):
            best = MatchResult(
                text=candidate,
                score=score,
                strategy=strategy,
                index=i,
            )

    return best


def _all_matches(
    query: str,
    candidates: Sequence[str],
    threshold: float = 0.4,
    case_sensitive: bool = False,
    limit: int = 10,
) -> list[MatchResult]:
    """Find all matching candidates above threshold, sorted by score.

    Args:
        query: Search text
        candidates: List of candidate strings
        threshold: Minimum score
        case_sensitive: Whether to match case-sensitively
        limit: Maximum number of results

    Returns:
        List of MatchResult sorted by score descending
    """
    if not query or not candidates:
        return []

    results = []
    for i, candidate in enumerate(candidates):
        if not candidate:
            continue
        score, strategy = _match_score(query, candidate, case_sensitive)
        if score >= threshold:
            results.append(MatchResult(
                text=candidate,
                score=score,
                strategy=strategy,
                index=i,
            ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def _semantic_match(
    query: str,
    candidates: Sequence[str],
    threshold: float = 0.5,
    **kwargs,
) -> Optional[MatchResult]:
    """Semantic similarity matching using embeddings.

    NOT YET IMPLEMENTED. Placeholder for future integration with:
    - OpenAI Embeddings API
    - Nexus embedding service
    - Local sentence-transformers models

    Args:
        query: Search text
        candidates: List of candidate strings
        threshold: Minimum similarity score
        **kwargs: Provider-specific options (api_key, model, endpoint, etc.)

    Returns:
        MatchResult if found, None otherwise

    Raises:
        NotImplementedError: Always (until implemented)
    """
    raise NotImplementedError(
        "Semantic matching is not yet implemented. "
        "See: https://github.com/sudoprivacy/ai-dev-browser/issues/3 "
        "Planned providers: OpenAI embeddings, Nexus, sentence-transformers."
    )

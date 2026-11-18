"""Lexical retrieval-quality layer for the existing BM25 pipeline.

No embeddings, no vector database, no external service. Everything here is
deterministic text processing around ``rank_bm25.BM25Okapi``.

Why each technique exists (each was demonstrated as a defect on the legacy
tokenizer/ranker; see docs/BACKEND_RETRIEVAL_AUDIT.md):

* ``normalize_degrees`` - ``B.Tech``/``M.Tech`` both collapsed to the token
  ``tech`` (single letters are dropped) and ``btech`` never matched ``B.Tech``.
* ``unicode_tokens``    - the legacy tokenizer is ASCII-only, so every Telugu or
  Hindi query produced zero tokens and Indic page text was never indexed.
* ``stemming``          - ``fees`` did not match a page that says ``fee``.
* ``synonyms``          - ``CSE`` did not match "Computer Science and Engineering".
* ``field_weighting``   - title and URL words are scored as their own BM25 field
  instead of being glued into the body text.
* ``phrase_bonus``      - "management quota" as an adjacent phrase outranks pages
  that merely contain both words.
* ``relevance_floor``   - a chunk that only shares boilerplate words ("campus",
  "home") with the question is no longer considered evidence.
* ``diversity``         - near-duplicate chunks (for example printer-friendly
  copies of a page) do not crowd out other relevant pages.

Limits: still purely lexical. Cross-language retrieval (an English question for
a Telugu page, or the reverse) is impossible here, and Indic inflection
(suffixes attached to a word) is not stemmed. See the audit document.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SYNONYMS_FILE_ENV = "RETRIEVAL_SYNONYMS_FILE"
DEFAULT_SYNONYMS_FILE = ROOT / "data" / "retrieval_synonyms.json"

# Legacy stop words (kept identical so the two modes disagree only where intended).
STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "being", "do", "does", "did", "has", "have", "had", "what",
    "which", "who", "whom", "when", "where", "why", "how",
    "can", "could", "would", "should", "will", "shall", "may",
    "might", "must", "and", "or", "but", "if", "then", "than",
    "to", "of", "in", "on", "at", "by", "for", "from", "with",
    "about", "into", "as", "it", "its", "this", "that", "these",
    "those", "i", "we", "you", "they", "them", "their", "our",
    "your", "me", "my", "please", "tell", "give", "provide",
    "available", "official", "svce", "tirupati",
}

# Words that carry no topic by themselves. They stay in the BM25 query but do not
# count against a chunk when measuring how much of the question it covers.
QUERY_FILLER = {
    "detail", "details", "information", "info", "list", "need", "know", "want",
    "show", "get", "find", "explain", "regarding", "latest", "current", "best",
    "good", "near", "about", "kind", "type", "much", "many", "also", "tomorrow",
    "today", "now",
}

# Indic scripts matched as letters: combining vowel signs (category Mc/Mn) are not
# alphanumeric for ``str.isalnum`` so a plain ``\w`` would split every word apart.
_TOKEN_RE = re.compile(r"[0-9a-z\u00c0-\u024f\u0900-\u097f\u0c00-\u0c7f]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")

_DEGREE_RE = re.compile(r"\b([bm])[\s.\-]*(tech|sc|com|arch|pharm|des|ed)\b\.?")
_DEGREE_SHORT_RE = re.compile(r"\b([bm])\s*\.\s*(e|a)\b\.?(?=\s|$|[,;:)])")
_MULTI_DOT_RE = re.compile(r"\b(m\.b\.a|m\.c\.a|b\.b\.a|b\.c\.a|ph\.d)\b\.?")
_SIMPLE_JOINS = ((re.compile(r"\be[\s\-]mail\b"), "email"), (re.compile(r"\bwi[\s\-]fi\b"), "wifi"))
_URL_EXT = {"php", "html", "htm", "aspx", "asp", "jsp", "pdf", "docx", "doc", "www", "http", "https", "com", "in", "edu", "org", "net"}


@dataclass(frozen=True)
class QualityConfig:
    """Every technique can be switched off individually (used for ablations)."""

    normalize_degrees: bool = True
    unicode_tokens: bool = True
    stemming: bool = True
    synonyms: bool = True
    field_weighting: bool = True
    phrase_bonus: bool = True
    relevance_floor: bool = True
    diversity: bool = True
    # A query term found in a chunk's title or URL path makes the chunk count as 'about' that
    # topic even when the word is common in the body (site navigation repeats "Placements",
    # "Admissions"... on every page). Without it such questions were refused (audit F12).
    meta_match_distinctive: bool = True
    title_weight: float = 0.6
    expansion_weight: float = 0.4
    phrase_weight: float = 1.5
    coverage_weight: float = 2.0
    min_coverage: float = 0.15
    distinctive_idf_fraction: float = 0.35
    near_duplicate_jaccard: float = 0.8

    @classmethod
    def from_env(cls) -> "QualityConfig":
        cfg = cls()
        raw = os.getenv("RETRIEVAL_MIN_COVERAGE", "").strip()
        if raw:
            try:
                value = float(raw)
                if 0.0 <= value <= 1.0:
                    cfg = replace(cfg, min_coverage=value)
                else:
                    LOGGER.warning("RETRIEVAL_MIN_COVERAGE ignored: %r is outside 0..1", raw)
            except ValueError:
                LOGGER.warning("RETRIEVAL_MIN_COVERAGE ignored: %r is not a number", raw)
        return cfg

    @classmethod
    def baseline_lexical(cls) -> "QualityConfig":
        """All techniques off: BM25 over title+text with the improved plumbing."""
        return cls(False, False, False, False, False, False, False, False, False)


# --------------------------------------------------------------------------- text


def normalize_text(text: str, cfg: QualityConfig = QualityConfig()) -> str:
    text = unicodedata.normalize("NFKC", str(text)).lower()
    if cfg.normalize_degrees:
        text = _MULTI_DOT_RE.sub(lambda m: m.group(1).replace(".", ""), text)
        text = _DEGREE_RE.sub(lambda m: m.group(1) + m.group(2), text)
        text = _DEGREE_SHORT_RE.sub(lambda m: m.group(1) + m.group(2), text)
        for pattern, repl in _SIMPLE_JOINS:
            text = pattern.sub(repl, text)
    return text


def stem(token: str) -> str:
    """Very conservative English plural stripping (applied to both sides)."""
    if len(token) < 4 or not token.isascii() or not token.isalpha():
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith(("sses", "ches", "shes", "xes", "zes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str, cfg: QualityConfig = QualityConfig(), *, keep_stop: bool = False) -> list[str]:
    text = normalize_text(text, cfg)
    pattern = _TOKEN_RE if cfg.unicode_tokens else _ASCII_TOKEN_RE
    out: list[str] = []
    for word in pattern.findall(text):
        if not keep_stop and word in STOP_WORDS:
            continue
        if len(word) <= 1 and word.isascii():
            continue
        out.append(stem(word) if cfg.stemming else word)
    return out


def url_tokens(url: str, cfg: QualityConfig = QualityConfig()) -> list[str]:
    """Words from the URL path ("/placements/statistics-2023-24" -> placements statistics 2023 24)."""
    if not url:
        return []
    path = re.sub(r"^[a-z]+://[^/]*", "", str(url).lower())
    path = path.split("#", 1)[0].replace("?", "/").replace("=", "/")
    words = re.findall(r"[a-z0-9]+", path)
    return [stem(w) if cfg.stemming else w for w in words if w not in _URL_EXT and len(w) > 1]


# ------------------------------------------------------------------- terminology

# Higher-education vocabulary only (abbreviations and alternative wordings). These
# are search terms, not facts about any college. Extend via data/retrieval_synonyms.json.
DEFAULT_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("cse", "computer science", "computer science engineering"),
    ("ece", "electronics communication", "electronics communication engineering"),
    ("eee", "electrical electronics", "electrical electronics engineering"),
    ("mech", "mechanical", "mechanical engineering"),
    ("hod", "head of department"),
    ("tpo", "training placement officer"),
    ("eamcet", "eapcet"),
    ("fee", "tuition fee", "fee structure"),
    ("scholarship", "financial aid"),
    ("hostel", "accommodation", "residence"),
    ("transport", "bus"),
    ("exam", "examination"),
    ("sem", "semester"),
    ("lib", "library"),
    ("wifi", "wireless internet"),
    ("ug", "undergraduate"),
    ("pg", "postgraduate"),
    ("phd", "doctoral", "doctorate"),
    ("placement", "recruitment"),
    ("grievance", "complaint"),
    ("syllabus", "curriculum"),
    ("intake", "seat"),
)


def load_synonym_groups(path: str | Path | None = None) -> tuple[tuple[str, ...], ...]:
    """Defaults plus an optional JSON file: ``[["term", "alternative phrase", ...], ...]``.

    A missing file is normal. A malformed file is ignored with a warning (never fatal).
    """
    groups = list(DEFAULT_SYNONYM_GROUPS)
    candidate = Path(path) if path else Path(os.getenv(SYNONYMS_FILE_ENV, "") or DEFAULT_SYNONYMS_FILE)
    try:
        if candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
            if not isinstance(data, list):
                raise ValueError("top level must be a list of lists")
            for entry in data:
                if (isinstance(entry, list) and len(entry) >= 2
                        and all(isinstance(item, str) and item.strip() for item in entry)):
                    groups.append(tuple(entry))
                else:
                    LOGGER.warning("Ignoring invalid synonym entry in %s: %r", candidate, entry)
    except Exception as exc:  # unreadable or malformed: keep defaults
        LOGGER.warning("Synonym file %s ignored: %s", candidate, exc)
    return tuple(groups)


@dataclass(frozen=True)
class Expansion:
    source: tuple[str, ...]           # query tokens that triggered it
    alternatives: tuple[tuple[str, ...], ...]  # token tuples that may stand in for the source


class SynonymMap:
    def __init__(self, groups: Iterable[Sequence[str]], cfg: QualityConfig):
        self._groups: list[list[tuple[str, ...]]] = []
        plain = replace(cfg, synonyms=False)
        for group in groups:
            phrases = [tuple(tokenize(p, plain)) for p in group]
            phrases = [p for p in phrases if p]
            if len(phrases) >= 2:
                self._groups.append(phrases)

    def expand(self, query_tokens: Sequence[str]) -> list[Expansion]:
        found: list[Expansion] = []
        seen: set[tuple] = set()
        joined = tuple(query_tokens)
        for phrases in self._groups:
            for i, phrase in enumerate(phrases):
                if not _contains_run(joined, phrase):
                    continue
                alts = tuple(p for j, p in enumerate(phrases) if j != i and p != phrase)
                key = (phrase, alts)
                if alts and key not in seen:
                    seen.add(key)
                    found.append(Expansion(phrase, alts))
        return found


def _contains_run(tokens: Sequence[str], run: Sequence[str]) -> bool:
    n, m = len(tokens), len(run)
    return m > 0 and any(tuple(tokens[i:i + m]) == tuple(run) for i in range(n - m + 1))


# ------------------------------------------------------------------------ analysis


@dataclass(frozen=True)
class QueryAnalysis:
    raw: str
    tokens: tuple[str, ...]            # de-duplicated, order preserved
    bigrams: tuple[tuple[str, str], ...]
    expansions: tuple[Expansion, ...]
    expansion_tokens: tuple[str, ...]  # tokens not already in the query


@dataclass
class QualityIndex:
    """BM25 fields and per-chunk token sets, built once per loaded index."""

    cfg: QualityConfig
    synonyms: SynonymMap
    body_bm25: Any
    meta_bm25: Any
    body_tokens: list[list[str]]
    doc_sets: list[frozenset]
    meta_sets: list[frozenset]
    idf: dict[str, float]
    idf_max: float
    n_chunks: int

    # ---- construction

    @classmethod
    def build(cls, chunks: Sequence[dict], bm25_cls: Any, cfg: QualityConfig | None = None,
              synonym_groups: Iterable[Sequence[str]] | None = None) -> "QualityIndex":
        cfg = cfg or QualityConfig.from_env()
        body_tokens: list[list[str]] = []
        meta_tokens: list[list[str]] = []
        for chunk in chunks:
            title, text, url = str(chunk.get("title", "")), str(chunk.get("text", "")), str(chunk.get("url", ""))
            if cfg.field_weighting:
                body_tokens.append(tokenize(text, cfg))
                meta_tokens.append(tokenize(title, cfg) + url_tokens(url, cfg))
            else:  # legacy layout: title glued to body, no separate field
                body_tokens.append(tokenize(f"{title} {text}", cfg))
                meta_tokens.append([])
        doc_sets = [frozenset(b) | frozenset(m) for b, m in zip(body_tokens, meta_tokens)]
        n = len(chunks)
        df: dict[str, int] = {}
        for tokens in doc_sets:
            for term in tokens:
                df[term] = df.get(term, 0) + 1
        idf = {t: math.log(1.0 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        groups = synonym_groups if synonym_groups is not None else load_synonym_groups()
        # rank_bm25 cannot be built from empty documents lists; guard empty metas.
        meta_corpus = [m if m else ["\u0000"] for m in meta_tokens]
        return cls(
            cfg=cfg,
            synonyms=SynonymMap(groups, cfg) if cfg.synonyms else SynonymMap((), cfg),
            body_bm25=bm25_cls([b if b else ["\u0000"] for b in body_tokens]),
            meta_bm25=bm25_cls(meta_corpus) if cfg.field_weighting else None,
            body_tokens=body_tokens,
            doc_sets=doc_sets,
            meta_sets=[frozenset(m) for m in meta_tokens],
            idf=idf,
            idf_max=math.log(1.0 + (n + 0.5) / 0.5),
            n_chunks=n,
        )

    # ---- query side

    def analyze(self, query: str) -> QueryAnalysis:
        tokens = tuple(dict.fromkeys(tokenize(query, self.cfg)))
        ordered = tokenize(query, self.cfg)
        bigrams = tuple(dict.fromkeys(zip(ordered, ordered[1:]))) if self.cfg.phrase_bonus else ()
        expansions = tuple(self.synonyms.expand(ordered)) if self.cfg.synonyms else ()
        in_query = set(tokens)
        extra: list[str] = []
        for exp in expansions:
            for alt in exp.alternatives:
                for term in alt:
                    if term not in in_query and term not in extra:
                        extra.append(term)
        return QueryAnalysis(query, tokens, bigrams, expansions, tuple(extra))

    def base_scores(self, analysis: QueryAnalysis):
        """Per-chunk lexical relevance: body + title_weight*meta + expansion_weight*expansion."""
        import numpy as np

        scores = np.asarray(self.body_bm25.get_scores(list(analysis.tokens)), dtype=float)
        scores = np.maximum(scores, 0.0)
        if self.meta_bm25 is not None and analysis.tokens:
            meta = np.maximum(np.asarray(self.meta_bm25.get_scores(list(analysis.tokens)), dtype=float), 0.0)
            scores = scores + self.cfg.title_weight * meta
        if analysis.expansion_tokens:
            exp = np.maximum(np.asarray(self.body_bm25.get_scores(list(analysis.expansion_tokens)), dtype=float), 0.0)
            scores = scores + self.cfg.expansion_weight * exp
        return scores

    # ---- per-candidate signals

    def _term_idf(self, term: str) -> float:
        return self.idf.get(term, self.idf_max)

    def _matched(self, term: str, doc: frozenset, analysis: QueryAnalysis) -> bool:
        if term in doc:
            return True
        for exp in analysis.expansions:
            if term in exp.source and any(all(t in doc for t in alt) for alt in exp.alternatives):
                return True
        return False

    def coverage(self, index: int, analysis: QueryAnalysis) -> tuple[float, bool]:
        """(idf-weighted share of the question's topical terms found in the chunk,
        whether at least one matched term is distinctive in this corpus)."""
        doc = self.doc_sets[index]
        topical = [t for t in analysis.tokens if t not in QUERY_FILLER] or list(analysis.tokens)
        total = sum(self._term_idf(t) for t in topical)
        if total <= 0:
            return 0.0, False
        matched = [t for t in topical if self._matched(t, doc, analysis)]
        got = sum(self._term_idf(t) for t in matched)
        threshold = self.cfg.distinctive_idf_fraction * self.idf_max
        distinctive = any(self._term_idf(t) >= threshold for t in matched)
        if not distinctive and self.cfg.meta_match_distinctive and self.meta_sets:
            meta = self.meta_sets[index]
            distinctive = any(t in meta for t in matched)
        return got / total, distinctive

    def phrase_matches(self, index: int, analysis: QueryAnalysis) -> int:
        if not analysis.bigrams:
            return 0
        body = self.body_tokens[index]
        pairs = set(zip(body, body[1:]))
        return sum(1 for bg in analysis.bigrams if bg in pairs)

    def near_duplicate(self, a: int, b: int) -> bool:
        sa, sb = self.doc_sets[a], self.doc_sets[b]
        if not sa or not sb:
            return False
        return len(sa & sb) / len(sa | sb) >= self.cfg.near_duplicate_jaccard

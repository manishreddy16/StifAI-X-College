"""Pure, read-only inspection helpers (no retrieval state, no writes, no network)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

_INDIC = re.compile(r"[\u0900-\u097f\u0c00-\u0c7f]")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

DEFAULT_QUESTIONS = (
    # Generic probes about common college topics. They carry no facts: the report only shows
    # what the index returns for them. Edit or replace with --questions FILE.
    "What is the admission process?",
    "What are the hostel fees?",
    "Tell me about placements",
    "How can I contact the college?",
    "What are the library timings?",
    "Which courses does the college offer?",
    "Are scholarships available?",
    "B.Tech eligibility",
    "What is the duration of M.Tech?",
    "CSE department laboratories",
    "Transport facilities",
    "How do I apply for revaluation?",
    "Best pizza near campus",
    "What is the capital of France?",
    "హాస్టల్ ఫీజు",
    "छात्रावास शुल्क",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint_tree(root: Path) -> dict[str, tuple[int, int]]:
    """{relative path: (size, mtime_ns)} for every file and directory under ``root``.

    Used before and after the run to prove nothing was created, changed or removed.
    Access times are deliberately excluded (reading a file may update them).
    """
    result: dict[str, tuple[int, int]] = {}
    root = Path(root)
    if not root.exists():
        return result
    for current, dirs, files in os.walk(root):
        for name in dirs + files:
            full = Path(current) / name
            try:
                st = full.stat()
            except OSError:
                continue
            result[str(full.relative_to(root))] = (0 if full.is_dir() else st.st_size, 0 if full.is_dir() else st.st_mtime_ns)
    return result


def read_questions(path: str | Path) -> list[str]:
    """One question per line, or JSONL with a ``question``/``query``/``text`` field. ``#`` comments allowed."""
    questions: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                for key in ("question", "query", "text"):
                    if isinstance(obj.get(key), str) and obj[key].strip():
                        questions.append(obj[key].strip())
                        break
                continue
        questions.append(line)
    return questions


def describe_file(path: Path) -> dict[str, Any]:
    """Facts about one candidate index file (read-only)."""
    info: dict[str, Any] = {"path": str(path), "exists": False}
    try:
        st = path.stat()
    except OSError:
        return info
    info.update(
        exists=True,
        size_bytes=st.st_size,
        mtime=st.st_mtime,
        mtime_iso=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
    )
    try:
        info["sha256"] = sha256_file(path)
    except OSError as exc:
        info["sha256"] = None
        info["read_error"] = f"{type(exc).__name__}: {exc}"
        return info
    info.update(corpus_stats(path))
    return info


def corpus_stats(path: Path) -> dict[str, Any]:
    """Parse the file the same way the API loader does and report data-quality facts."""
    total = invalid = 0
    texts: list[str] = []
    urls: list[str] = []
    stats: dict[str, Any] = {}
    null_url = null_title = missing_chunk_id = missing_doc_id = 0
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                total += 1
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    invalid += 1
                    continue
                text = item.get("text") if isinstance(item, dict) else None
                if not isinstance(text, str) or not text.strip():
                    invalid += 1
                    continue
                texts.append(text)
                url = item.get("url")
                title = item.get("title")
                if not isinstance(url, str) or not url.strip():
                    null_url += 1
                else:
                    urls.append(url.strip())
                if not isinstance(title, str) or not title.strip():
                    null_title += 1
                if not item.get("chunk_id"):
                    missing_chunk_id += 1
                if not item.get("doc_id"):
                    missing_doc_id += 1
    except UnicodeDecodeError as exc:
        return {"readable": False, "read_error": f"UnicodeDecodeError: {exc}", "valid_chunks": 0,
                "invalid_lines": invalid, "non_blank_lines": total}
    except OSError as exc:
        return {"readable": False, "read_error": f"{type(exc).__name__}: {exc}", "valid_chunks": 0,
                "invalid_lines": invalid, "non_blank_lines": total}

    lengths = [len(t) for t in texts]
    letters = indic = non_ascii_letters = 0
    for t in texts:
        for ch in _LETTER.findall(t):
            letters += 1
            if not ch.isascii():
                non_ascii_letters += 1
        indic += len(_INDIC.findall(t))
    duplicate_hashes = Counter(hashlib.sha1(" ".join(t.split()).lower().encode("utf-8")).hexdigest() for t in texts)
    duplicate_chunks = sum(c - 1 for c in duplicate_hashes.values() if c > 1)
    stats.update(
        readable=True,
        non_blank_lines=total,
        valid_chunks=len(texts),
        invalid_lines=invalid,
        distinct_urls=len(set(urls)),
        chunks_without_url=null_url,
        chunks_without_title=null_title,
        chunks_without_chunk_id=missing_chunk_id,
        chunks_without_doc_id=missing_doc_id,
        duplicate_text_chunks=duplicate_chunks,
        text_length={
            "min": min(lengths) if lengths else 0,
            "median": int(statistics.median(lengths)) if lengths else 0,
            "max": max(lengths) if lengths else 0,
        },
        non_ascii_letter_share=round(non_ascii_letters / letters, 4) if letters else 0.0,
        indic_character_count=indic,
    )
    return stats


def term_frequency_profile(quality_index, *, top: int = 12) -> dict[str, Any]:
    """How many index terms can never count as 'distinctive' (audit finding F12)."""
    n = quality_index.n_chunks
    cfg = quality_index.cfg
    df: Counter = Counter()
    terms = [""] * len(quality_index.vocabulary)
    for term, token_id in quality_index.vocabulary.items():
        terms[token_id] = term
    for tokens in quality_index.doc_sets:
        df.update(terms[token] for token in tokens)
    threshold = cfg.distinctive_idf_fraction * quality_index.idf_max
    max_df = 0
    for candidate in range(1, n + 1):  # largest df whose idf still reaches the threshold
        if math.log(1.0 + (n - candidate + 0.5) / (candidate + 0.5)) >= threshold:
            max_df = candidate
        else:
            break
    dominant = [(term, count) for term, count in df.most_common() if count > max_df]
    return {
        "chunks": n,
        "vocabulary": len(df),
        "distinctive_max_df": max_df,
        "distinctive_max_df_share": round(max_df / n, 4) if n else 0.0,
        "non_distinctive_terms": len(dominant),
        "non_distinctive_share_of_vocabulary": round(len(dominant) / len(df), 4) if df else 0.0,
        "most_common_non_distinctive": [
            {"term": term, "chunks": count, "share": round(count / n, 3)} for term, count in dominant[:top]
        ],
    }


def snippet(text: Any, width: int = 110) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"

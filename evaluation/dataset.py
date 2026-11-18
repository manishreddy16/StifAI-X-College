"""Evaluation dataset: loading and strict validation of JSONL records.

Ground truth is only trusted when ``verification_status == "verified"``.
Records that are not verified may not carry expected sources/keywords, so an
unverified question can never be scored as a success or a failure by accident.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CATEGORIES = (
    "Admissions",
    "Courses and departments",
    "Fees and scholarships",
    "Placements",
    "Faculty and contact",
    "Examinations and academic regulations",
    "Hostel and transport",
    "General college information",
)
VERIFIED = "verified"
NEEDS_GROUND_TRUTH = "needs_ground_truth"
UNVERIFIED = "unverified"
STATUSES = (VERIFIED, NEEDS_GROUND_TRUTH, UNVERIFIED)
KINDS = ("retrieval", "context_dependent", "verification_behavior")
ANSWERABLE = ("yes", "no", "unknown")
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class DatasetError(Exception):
    """Dataset cannot be used. ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class EvalRecord:
    id: str
    question: str
    category: str
    question_kind: str = "retrieval"
    answerable: str = "unknown"
    expected_sources: tuple[str, ...] = ()
    expected_doc_ids: tuple[str, ...] = ()
    expected_keywords: tuple[str, ...] = ()
    candidate_sources: tuple[str, ...] = ()  # hints from project files; NEVER scored
    expect_official_referral: bool | None = None
    verification_status: str = NEEDS_GROUND_TRUTH
    verified_by: str = ""
    verified_on: str = ""
    notes: str = ""

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VERIFIED

    @property
    def is_retrieval_scorable(self) -> bool:
        return (
            self.is_verified
            and self.question_kind == "retrieval"
            and self.answerable == "yes"
            and bool(self.expected_sources or self.expected_doc_ids)
        )

    @property
    def is_verified_unanswerable(self) -> bool:
        return self.is_verified and self.answerable == "no"

    def to_dict(self) -> dict[str, Any]:
        out = {}
        for key, value in self.__dict__.items():
            out[key] = list(value) if isinstance(value, tuple) else value
        return out


@dataclass(frozen=True)
class Dataset:
    records: tuple[EvalRecord, ...]
    path: str
    sha256: str

    def by_id(self) -> dict[str, EvalRecord]:
        return {r.id: r for r in self.records}


def normalize_url(url: str) -> str:
    """Canonical form for comparing source URLs (query string is kept)."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url if "//" in url else "//" + url)
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{host}{path}{query}"


def _str_list(value: Any, name: str, problems: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        problems.append(f"'{name}' must be a list of non-empty strings")
        return ()
    return tuple(v.strip() for v in value)


def _parse_record(raw: Any) -> EvalRecord:
    problems: list[str] = []
    if not isinstance(raw, dict):
        raise DatasetError(["record is not a JSON object"])

    def text(name: str, required: bool = False) -> str:
        value = raw.get(name, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            problems.append(f"'{name}' must be a string")
            return ""
        if required and not value.strip():
            problems.append(f"'{name}' is required")
        return value.strip()

    rid = text("id", True)
    if rid and not _ID_RE.match(rid):
        problems.append("'id' may only contain letters, digits, '_', '-' and '.'")
    question = text("question", True)
    category = text("category", True)
    if category and category not in CATEGORIES:
        problems.append(f"unknown category {category!r}")
    kind = text("question_kind") or "retrieval"
    if kind not in KINDS:
        problems.append(f"'question_kind' must be one of {KINDS}")
    answerable = text("answerable") or "unknown"
    if answerable not in ANSWERABLE:
        problems.append(f"'answerable' must be one of {ANSWERABLE}")
    status = text("verification_status") or NEEDS_GROUND_TRUTH
    if status not in STATUSES:
        problems.append(f"'verification_status' must be one of {STATUSES}")
    sources = _str_list(raw.get("expected_sources"), "expected_sources", problems)
    doc_ids = _str_list(raw.get("expected_doc_ids"), "expected_doc_ids", problems)
    keywords = _str_list(raw.get("expected_keywords"), "expected_keywords", problems)
    candidates = _str_list(raw.get("candidate_sources"), "candidate_sources", problems)
    referral = raw.get("expect_official_referral")
    if referral is not None and not isinstance(referral, bool):
        problems.append("'expect_official_referral' must be true, false or null")
        referral = None
    verified_by = text("verified_by")
    verified_on = text("verified_on")
    notes = text("notes")

    if status == VERIFIED:
        if not verified_by:
            problems.append("verified records need 'verified_by'")
        try:
            date.fromisoformat(verified_on)
        except ValueError:
            problems.append("verified records need 'verified_on' as YYYY-MM-DD")
        if answerable == "unknown":
            problems.append("verified records must set 'answerable' to 'yes' or 'no'")
        if answerable == "yes" and kind == "retrieval" and not (sources or doc_ids):
            problems.append("verified answerable retrieval records need expected_sources or expected_doc_ids")
        if answerable == "no" and (sources or doc_ids):
            problems.append("a verified unanswerable record must not list expected sources")
    else:
        if sources or doc_ids or keywords:
            problems.append(
                "only verified records may set expected_sources/expected_doc_ids/"
                "expected_keywords; put unconfirmed hints in 'candidate_sources'"
            )
        if answerable != "unknown":
            problems.append("non-verified records must keep 'answerable' = 'unknown'")

    if problems:
        raise DatasetError([f"[{rid or '?'}] {p}" for p in problems])
    return EvalRecord(
        id=rid, question=question, category=category, question_kind=kind,
        answerable=answerable, expected_sources=sources, expected_doc_ids=doc_ids,
        expected_keywords=keywords, candidate_sources=candidates,
        expect_official_referral=referral, verification_status=status,
        verified_by=verified_by, verified_on=verified_on, notes=notes,
    )


def load_dataset(path: str | Path) -> Dataset:
    """Load and validate a JSONL dataset; raise ``DatasetError`` listing all problems."""
    path = Path(path)
    if not path.is_file():
        raise DatasetError([f"dataset file not found: {path}"])
    try:
        data = path.read_bytes()
        content = data.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise DatasetError([f"dataset file unreadable: {exc}"]) from exc

    errors: list[str] = []
    records: list[EvalRecord] = []
    seen: set[str] = set()
    for number, line in enumerate(content.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {number}: invalid JSON ({exc.msg})")
            continue
        try:
            record = _parse_record(raw)
        except DatasetError as exc:
            errors.extend(f"line {number}: {e}" for e in exc.errors)
            continue
        if record.id in seen:
            errors.append(f"line {number}: duplicate id {record.id!r}")
            continue
        seen.add(record.id)
        records.append(record)
    if not records and not errors:
        errors.append("dataset contains no records")
    if errors:
        raise DatasetError(errors)
    return Dataset(tuple(records), str(path), hashlib.sha256(data).hexdigest())

"""Deterministic answer-grounding checks.

These checks compare an answer with the evidence chunks it was generated from.
They detect *unsupported* content (numbers, contacts, URLs, thinly supported
sentences) and missing official-verification referrals.

LIMITATIONS: "no issues found" means no unsupported content was detected by
these lexical checks. It does NOT mean the answer is correct: evidence itself
may be outdated or wrong, paraphrases can be missed, and number words
("twelve") are not parsed. No LLM is used and no network call is made.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

DISCLAIMER = (
    "Deterministic lexical checks only. 'no_issues_found' does not mean the "
    "answer is correct, current or complete."
)

REFERRAL_RE = re.compile(
    r"(official (college )?website|official (admission|college|svce) |contact (the )?(svce |admissions? |college |relevant )?"
    r"(office|department|team)|check the (latest )?official|please (check|verify|confirm|contact)|"
    r"verify (it |this |that )?(on|with|from|at)|confirm (it |this )?(with|on|from)|"
    r"(couldn'?t|could not|can'?t|cannot|unable to|don'?t have) (find|verify|confirm|locate)|"
    r"not (available|published|listed) in (the )?(indexed|available))",
    re.I,
)
TIME_SENSITIVE_RE = re.compile(
    r"\b(current|currently|latest|deadline|last date|this year|upcoming|now|today|new)\b", re.I
)
KIND_TERMS = {
    "fee": ("fee", "fees", "tuition", "rs", "inr", "₹", "rupees", "amount", "scholarship", "payment", "lakh", "lakhs"),
    "placement": ("placement", "placements", "package", "lpa", "recruiter", "recruiters", "placed", "salary", "ctc"),
    "admission": ("admission", "admissions", "eapcet", "ecet", "seat", "seats", "intake", "cutoff", "rank", "deadline", "quota", "lateral"),
}
_STOP = set(
    "a an the and or of to in on at for from by with is are was were be been being this that these those it its as "
    "can may will shall should would could which who whom what when where how not no yes also any all more most "
    "you your we our they their them there here have has had do does did than then so such if but about into over "
    "per".split()
)
_YEAR_RANGE = re.compile(r"\b(20\d{2})\s*[-–/]\s*(\d{2,4})\b")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://[^\s)>\]\"']+")
_PHONE = re.compile(r"(?<![\w])\+?\d[\d\s().-]{8,}\d(?![\w])")
_SOURCE_REF = re.compile(r"\[?source\s*\d+\]?", re.I)
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]\s*)?\d{1,2}[.)]\s+", re.M)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # high | medium | low
    detail: str
    sentence: str = ""


@dataclass
class GroundingResult:
    verdict: str  # fail | warnings | no_issues_found
    findings: list[Finding] = field(default_factory=list)
    is_referral: bool = False
    evidence_count: int = 0
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def is_referral(text: str) -> bool:
    return bool(REFERRAL_RE.search(text or ""))


def _norm_number(raw: str) -> str:
    raw = raw.replace(",", "")
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    return raw.lstrip("0") or "0"


def _norm_year_range(a: str, b: str) -> str:
    return f"{a}-{b[-2:]}"


def _sentences(text: str) -> list[str]:
    text = _LIST_MARKER.sub("", text)
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _content_tokens(text: str) -> list[str]:
    out = []
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word in _STOP or len(word) <= 2 or word.isdigit():
            continue
        out.append(word[:-1] if word.endswith("s") and len(word) > 3 else word)
    return out


def _evidence_text(evidence: Sequence[dict[str, Any]]) -> str:
    return "\n".join(
        f"{c.get('title', '')}\n{c.get('text', '')}\n{c.get('url', '')}" for c in evidence
    )


def _numbers_in(text: str) -> tuple[set[str], set[str]]:
    ranges = {_norm_year_range(a, b) for a, b in _YEAR_RANGE.findall(text)}
    stripped = _YEAR_RANGE.sub(" ", text)
    stripped = _PHONE.sub(" ", stripped)
    return ranges, {_norm_number(n) for n in _NUMBER.findall(stripped)}


def _claim_kind(sentence: str, question: str = "") -> str | None:
    words = set(re.findall(r"[a-z₹]+", sentence.lower()))
    for kind, terms in KIND_TERMS.items():
        if words & set(terms):
            return kind
    words_q = set(re.findall(r"[a-z₹]+", question.lower()))
    for kind, terms in KIND_TERMS.items():
        if words_q & set(terms):
            return kind
    return None


def check_grounding(
    answer: str,
    evidence: Sequence[dict[str, Any]],
    *,
    question: str = "",
    expect_referral: bool | None = None,
    min_support: float = 0.5,
) -> GroundingResult:
    """Check ``answer`` against ``evidence`` chunks (dicts with title/text/url)."""
    answer = answer or ""
    evidence = [c for c in evidence if str(c.get("text", "")).strip()]
    findings: list[Finding] = []
    referral = is_referral(answer)

    if not answer.strip():
        findings.append(Finding("empty_answer", "high", "The answer is empty."))
        return GroundingResult("fail", findings, referral, len(evidence))

    ev_text = _evidence_text(evidence)
    ev_lower = ev_text.lower()
    ev_ranges, ev_numbers = _numbers_in(ev_text)
    ev_digits = re.sub(r"\D", "", ev_text)

    if not evidence and not referral:
        findings.append(Finding(
            "answer_without_evidence", "high",
            "No usable evidence was retrieved, but the answer does not direct the user to official verification.",
        ))

    if expect_referral and not referral:
        findings.append(Finding(
            "missing_official_verification_referral", "high",
            "This question expects the answer to direct the user to an official source to verify, but none was found.",
        ))

    for sentence in _sentences(answer):
        clean = _SOURCE_REF.sub(" ", sentence)
        kind = _claim_kind(clean, question)
        ranges, numbers = _numbers_in(clean)
        for rng in sorted(ranges - ev_ranges):
            findings.append(Finding(
                f"unsupported_{kind}_claim" if kind else "unsupported_number", "high" if kind else "medium",
                f"Academic-year/range '{rng}' does not appear in the evidence.", sentence))
        for num in sorted(numbers - ev_numbers):
            findings.append(Finding(
                f"unsupported_{kind}_claim" if kind else "unsupported_number", "high" if kind else "medium",
                f"Number '{num}' does not appear in the evidence.", sentence))
        for phone in _PHONE.findall(clean):
            digits = re.sub(r"\D", "", phone)
            if digits and digits not in ev_digits:
                findings.append(Finding("unsupported_phone", "high",
                                        f"Phone number '{phone.strip()}' not found in the evidence.", sentence))
        for email in _EMAIL.findall(clean):
            if email.lower() not in ev_lower:
                findings.append(Finding("unsupported_email", "high",
                                        f"Email '{email}' not found in the evidence.", sentence))
        for url in _URL.findall(clean):
            if url.rstrip(".,;").lower().rstrip("/") not in ev_lower.replace("/\n", "\n"):
                findings.append(Finding("unsupported_url", "high",
                                        f"URL '{url}' not found in the evidence.", sentence))

        tokens = _content_tokens(_URL.sub(" ", clean))
        if len(tokens) >= 4 and not (is_referral(clean) and not numbers):
            ev_vocab = set(_content_tokens(ev_text))
            ratio = sum(1 for t in tokens if t in ev_vocab) / len(tokens)
            if ratio < min_support:
                findings.append(Finding(
                    "low_lexical_support", "medium",
                    f"Only {ratio:.0%} of this sentence's content words appear in the evidence.", sentence))

    if (
        TIME_SENSITIVE_RE.search(question or "")
        and not referral
        and evidence
    ):
        findings.append(Finding(
            "time_sensitive_without_verification_pointer", "low",
            "The question is time-sensitive but the answer gives no pointer to verify on an official source."))

    # De-duplicate identical findings.
    unique, seen = [], set()
    for f in findings:
        key = (f.code, f.detail, f.sentence)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    findings = unique
    if any(f.severity == "high" for f in findings):
        verdict = "fail"
    elif findings:
        verdict = "warnings"
    else:
        verdict = "no_issues_found"
    return GroundingResult(verdict, findings, referral, len(evidence))

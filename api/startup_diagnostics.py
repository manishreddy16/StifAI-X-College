from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


def _parse_proc_status_rss_mb(status: str) -> float | None:
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            fields = line.split()
            if len(fields) >= 2:
                try:
                    return int(fields[1]) / 1024
                except ValueError:
                    return None
    return None


def process_rss_mb() -> float | None:
    """Return resident process memory in MiB on Linux, or None when unavailable."""
    try:
        status = Path("/proc/self/status").read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    return _parse_proc_status_rss_mb(status)


def _rss_label() -> str:
    rss_mb = process_rss_mb()
    return f"{rss_mb:.1f}" if rss_mb is not None else "unavailable"


def _details_label(details: dict[str, int]) -> str:
    return "".join(f" {key}={value}" for key, value in sorted(details.items()))


@contextmanager
def startup_phase(
    logger: logging.Logger,
    phase: str,
    *,
    details: dict[str, int] | None = None,
) -> Generator[dict[str, int], None, None]:
    """Log safe timing and RSS markers around a synchronous startup phase."""
    phase_details = dict(details or {})
    started = time.perf_counter()
    logger.info(
        "startup_phase=%s status=BEGIN elapsed_s=0.000 rss_mb=%s%s",
        phase,
        _rss_label(),
        _details_label(phase_details),
    )
    try:
        yield phase_details
    except BaseException:
        logger.info(
            "startup_phase=%s status=FAILED elapsed_s=%.3f rss_mb=%s%s",
            phase,
            time.perf_counter() - started,
            _rss_label(),
            _details_label(phase_details),
        )
        raise
    else:
        logger.info(
            "startup_phase=%s status=COMPLETE elapsed_s=%.3f rss_mb=%s%s",
            phase,
            time.perf_counter() - started,
            _rss_label(),
            _details_label(phase_details),
        )

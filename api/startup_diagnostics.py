from __future__ import annotations

import logging
import sys
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


def _emit(message: str) -> None:
    """Emit a startup diagnostic without relying on the application logger."""
    diagnostic_logger = logging.Logger("api.startup_diagnostics", level=logging.INFO)
    diagnostic_logger.propagate = False
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(logging.INFO)
    diagnostic_logger.addHandler(handler)
    try:
        diagnostic_logger.info(message)
        handler.flush()
    finally:
        diagnostic_logger.removeHandler(handler)
        handler.close()


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
    _emit(
        f"startup_phase={phase} status=BEGIN elapsed_s=0.000 "
        f"rss_mb={_rss_label()}{_details_label(phase_details)}"
    )
    try:
        yield phase_details
    except BaseException:
        _emit(
            f"startup_phase={phase} status=FAILED "
            f"elapsed_s={time.perf_counter() - started:.3f} "
            f"rss_mb={_rss_label()}{_details_label(phase_details)}"
        )
        raise
    else:
        _emit(
            f"startup_phase={phase} status=COMPLETE "
            f"elapsed_s={time.perf_counter() - started:.3f} "
            f"rss_mb={_rss_label()}{_details_label(phase_details)}"
        )

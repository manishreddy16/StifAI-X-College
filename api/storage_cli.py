"""Explicit bootstrap command for the opt-in shared knowledge-artifact store."""

from __future__ import annotations

import argparse
import json
import sys

from api.artifact_storage import StorageError, get_storage, storage_backend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed shared R2 storage from approved local SVCE knowledge artifacts.")
    parser.add_argument("command", choices=["seed-local"])
    parser.add_argument("--confirm-initial-seed", action="store_true",
                        help="Confirm that approved local knowledge artifacts should be uploaded to the configured bucket.")
    args = parser.parse_args(argv)
    if not args.confirm_initial_seed:
        parser.error("seed-local requires --confirm-initial-seed")
    if storage_backend() != "r2":
        print("R2 must be explicitly configured through STIF_STORAGE_BACKEND=r2.", file=sys.stderr)
        return 2
    try:
        result = get_storage().publish_local(allow_initial=True)
    except StorageError as exc:
        print(f"Storage seed failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

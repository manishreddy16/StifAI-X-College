"""Administration CLI (run from the project root):

    python -m api.manage init-db
    python -m api.manage create-admin --email you@example.com --name "Full Name"
    python -m api.manage set-password --email you@example.com
    python -m api.manage add-programme "Exact programme name"
    python -m api.manage import-programmes programmes.json     # JSON array of names
    python -m api.manage list-users

Passwords are read from a hidden prompt, or from the STIF_ADMIN_PASSWORD environment variable
for non-interactive use. They are never accepted as command-line arguments (shell history).
Programme names must come from official SVCE sources; nothing is pre-loaded.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from dotenv import load_dotenv

from api import auth_service, db, enquiry_service
from api.errors import ServiceError


def _password(confirm: bool) -> str:
    env = os.getenv("STIF_ADMIN_PASSWORD")
    if env:
        return env
    first = getpass.getpass("Password: ")
    if confirm and getpass.getpass("Repeat password: ") != first:
        raise SystemExit("Passwords did not match.")
    return first


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="python -m api.manage", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    c = sub.add_parser("create-admin"); c.add_argument("--email", required=True); c.add_argument("--name", required=True)
    s = sub.add_parser("set-password"); s.add_argument("--email", required=True)
    a = sub.add_parser("add-programme"); a.add_argument("name")
    i = sub.add_parser("import-programmes"); i.add_argument("file")
    sub.add_parser("list-users")
    args = p.parse_args(argv)

    db.init_db()
    conn = db.connect()
    try:
        if args.cmd == "init-db":
            print(f"Database ready: {db.database_description()}")
        elif args.cmd == "create-admin":
            user = auth_service.create_user(conn, email=args.email, full_name=args.name, password=_password(True), role="admin")
            print(f"Created admin {user.email}")
        elif args.cmd == "set-password":
            auth_service.set_password(conn, args.email, _password(True))
            print("Password updated; existing sessions were signed out.")
        elif args.cmd == "add-programme":
            print("Added:", enquiry_service.add_programme(conn, args.name)["name"])
        elif args.cmd == "import-programmes":
            with open(args.file, encoding="utf-8-sig") as fh:
                names = json.load(fh)
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                raise SystemExit("The file must contain a JSON array of programme names (strings).")
            added = skipped = 0
            for name in names:
                try:
                    enquiry_service.add_programme(conn, name); added += 1
                except ServiceError:
                    skipped += 1
            print(f"Added {added}, skipped {skipped} (invalid or already present).")
        elif args.cmd == "list-users":
            for r in conn.execute("SELECT email, role, is_active, created_at FROM users ORDER BY id"):
                print(f"{r['email']}\t{r['role']}\t{'active' if r['is_active'] else 'disabled'}\t{r['created_at']}")
    except ServiceError as exc:
        print(f"Error: {exc.message} {exc.fields or ''}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

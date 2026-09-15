"""Process due calendar tasks once - the whole runner "infrastructure".

No daemon, no queue, no scheduler library: run this script manually or
from cron (e.g. hourly). It opens the database, hands the session to
app.services.runner_service.run_due_tasks() and prints a summary.

Usage (from the repository root):
    python scripts/run_calendar_tasks.py
    python scripts/run_calendar_tasks.py --verbose
    python scripts/run_calendar_tasks.py --now 2026-10-01T00:00:00
    python scripts/run_calendar_tasks.py --database-url sqlite:///data/library.db

Exit codes: 0 = everything fine (or nothing due), 1 = at least one task
failed (failed tasks stay pending and are retried on the next run),
2 = bad command-line arguments.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import settings  # noqa: E402
from app.database import Base, make_engine, make_session_factory  # noqa: E402
import app.models  # noqa: F401,E402  (register all models on Base.metadata)
from app.services.runner_service import run_due_tasks  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Process pending calendar events that are due."
    )
    parser.add_argument(
        "--database-url", default=None, help="Defaults to the app's DATABASE_URL"
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Treat this ISO datetime as 'now' (useful for testing/simulation)",
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Max events per run (default 100)"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print every result message"
    )
    args = parser.parse_args(argv)

    now = None
    if args.now:
        try:
            now = datetime.fromisoformat(args.now)
        except ValueError:
            print(
                f"Invalid --now value: {args.now!r} "
                "(expected ISO format, e.g. 2026-10-01T09:00:00)"
            )
            return 2

    url = args.database_url or settings.database_url
    engine = make_engine(url)
    Base.metadata.create_all(engine)  # harmless no-op on existing databases
    session_factory = make_session_factory(engine)

    print(f"Calendar runner - database: {url}")
    with session_factory() as db:
        summary = run_due_tasks(db, now=now, limit=args.limit)
    engine.dispose()

    print(f"Run time: {summary['now']}")
    if summary["due"] == 0:
        print("No pending tasks due - nothing to do.")
    for result in summary["results"]:
        mark = "OK " if result["status"] == "completed" else "ERR"
        print(f"  [{mark}] #{result['id']} ({result['event_type']}) {result['title']}")
        if args.verbose or result["status"] != "completed":
            print(f"         -> {result['result_message']}")
    print(
        f"Summary: {summary['succeeded']} completed, {summary['failed']} failed "
        "(failed tasks stay pending and are retried on the next run)."
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())

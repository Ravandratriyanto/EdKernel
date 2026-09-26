"""Seed fake student accounts for lab / stub testing.

Creates an admin FIRST (so users.create_user's "first account becomes admin"
rule doesn't silently promote student01), then N students with predictable
emails + passwords, and writes a printable roster CSV.

    python -m stubtesting.seed_users            # admin + 30 students
    python -m stubtesting.seed_users --count 20

Re-runnable: accounts that already exist are left alone.

NOTE: turn auth ON for these to actually gate logins — set
settings.json auth_required=true (or the /dev toggle). With auth off, everyone
is treated as admin and the logins are moot.
"""
import argparse
import csv
from pathlib import Path

import users

ADMIN_USER = "admin@test.edkernel"
ADMIN_PW = "edkerneladmin"          # >= MIN_PASSWORD_LENGTH (8)
DOMAIN = "test.edkernel"
ROSTER = Path(__file__).parent / "test_accounts.csv"


def _ensure(username, password, role):
    """Create a user if absent; return (username, password, role, status)."""
    try:
        users.create_user(username, password, role)
        return (username, password, role, "created")
    except users.UserError as e:
        status = "exists" if "taken" in str(e).lower() else f"skipped ({e})"
        return (username, password, role, status)


def seed(count):
    users.init()
    # admin first — claims the forced-admin slot on an empty DB, and gives us a
    # known teacher/admin login to view the dev panel + quiz attempts.
    rows = [_ensure(ADMIN_USER, ADMIN_PW, "admin")]
    for n in range(1, count + 1):
        rows.append(_ensure(f"student{n:02d}@{DOMAIN}", f"edkernel{n:02d}", "student"))

    with ROSTER.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["username", "password", "role", "status"])
        w.writerows(rows)

    print(f"{'username':32} {'password':16} {'role':8} status")
    print("-" * 70)
    for u, p, r, s in rows:
        print(f"{u:32} {p:16} {r:8} {s}")
    made = sum(1 for *_, s in rows if s == "created")
    print(f"\n{made} created, {len(rows) - made} already existed. Roster CSV -> {ROSTER}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=30)
    args = ap.parse_args()
    seed(args.count)

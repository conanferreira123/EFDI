"""
Seed script: creates one default user per role for local development
and testing/demonstration purposes.

Idempotent: re-running this script will skip any username that already
exists rather than erroring out or creating duplicates.

Usage:
    venv/bin/python scripts/seed_users.py

SECURITY NOTE: these are well-known, intentionally simple development
credentials. This script should never be run against a production
database. APP_ENV is checked and the script refuses to run if
APP_ENV=production.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import get_db_context  # noqa: E402
from app.models.roles import UserRole  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402

# Importing app.models (rather than just app.models.user) guarantees
# every model -- and therefore every relationship() target -- is
# registered before any query runs. See app/models/__init__.py for why
# this matters.
import app.models  # noqa: E402,F401

SEED_USERS = [
    {
        "username": "admin",
        "email": "admin@efdi-corp.com",
        "full_name": "System Administrator",
        "password": "Admin@123",
        "role": UserRole.ADMIN.value,
    },
    {
        "username": "manager",
        "email": "manager@efdi-corp.com",
        "full_name": "Finance Manager",
        "password": "Manager@123",
        "role": UserRole.FINANCE_MANAGER.value,
    },
    {
        "username": "analyst",
        "email": "analyst@efdi-corp.com",
        "full_name": "Finance Analyst",
        "password": "Analyst@123",
        "role": UserRole.FINANCE_ANALYST.value,
    },
    {
        "username": "auditor",
        "email": "auditor@efdi-corp.com",
        "full_name": "Internal Auditor",
        "password": "Auditor@123",
        "role": UserRole.AUDITOR.value,
    },
]


def main() -> None:
    if settings.is_production:
        print("Refusing to seed default users: APP_ENV=production.")
        sys.exit(1)

    with get_db_context() as db:
        repo = UserRepository(db)
        created, skipped = [], []

        for spec in SEED_USERS:
            existing = repo.get_by_username(spec["username"])
            if existing:
                skipped.append(spec["username"])
                continue

            repo.create(
                username=spec["username"],
                email=spec["email"],
                full_name=spec["full_name"],
                password_hash=hash_password(spec["password"]),
                role=spec["role"],
            )
            created.append(spec["username"])

    print(f"Created {len(created)} user(s): {created}")
    print(f"Skipped {len(skipped)} existing user(s): {skipped}")
    print("\nDefault credentials for local testing:")
    print(f"{'ROLE':<18}{'USERNAME':<12}{'PASSWORD'}")
    for spec in SEED_USERS:
        print(f"{spec['role']:<18}{spec['username']:<12}{spec['password']}")


if __name__ == "__main__":
    main()

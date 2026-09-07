"""
User role definitions.

Defined as a plain Python enum (backed by a Postgres VARCHAR column,
not a native Postgres ENUM type) so that adding/renaming a role later
is a simple code change + data migration rather than an ALTER TYPE
operation, which is notoriously awkward in Postgres.
"""
import enum


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    FINANCE_MANAGER = "FINANCE_MANAGER"
    FINANCE_ANALYST = "FINANCE_ANALYST"
    AUDITOR = "AUDITOR"

    @classmethod
    def values(cls) -> list[str]:
        return [role.value for role in cls]

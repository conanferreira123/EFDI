"""
Validation result data structures.

A ValidationReport aggregates every ValidationIssue found across all
validators (required fields, date format, amount format, tax-ID format,
duplicate detection, business rules) run against a single document's
extraction result. Severity distinguishes hard failures (ERROR --
should block approval) from softer flags (WARNING -- worth a reviewer's
attention but not necessarily blocking).
"""
import enum
from dataclasses import dataclass, field


class ValidationSeverity(str, enum.Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationRuleType(str, enum.Enum):
    REQUIRED_FIELD = "REQUIRED_FIELD"
    DATE_FORMAT = "DATE_FORMAT"
    AMOUNT_FORMAT = "AMOUNT_FORMAT"
    TAX_ID_FORMAT = "TAX_ID_FORMAT"
    DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
    BUSINESS_RULE = "BUSINESS_RULE"


@dataclass
class ValidationIssue:
    rule_type: ValidationRuleType
    severity: ValidationSeverity
    field_key: str | None  # None for document-level issues (e.g. duplicate detection)
    message: str


@dataclass
class ValidationReportData:
    document_type: str
    issues: list[ValidationIssue] = field(default_factory=list)
    engine_name: str = ""

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.WARNING)

    @property
    def is_valid(self) -> bool:
        """A document is considered valid if it has zero ERROR-severity issues."""
        return self.error_count == 0

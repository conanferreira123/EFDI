"""
Approval workflow state machine.

Defines the allowed transitions between DocumentStatus values for
workflow actions (request approval, approve, reject), and which roles
may perform each action. This is intentionally a static, explicit table
rather than inferred logic, so the full set of valid transitions is
visible in one place and any change to workflow rules is a deliberate,
reviewable edit here.

Transition table:
  VALIDATED         --REQUEST_APPROVAL--> PENDING_APPROVAL
  PENDING_APPROVAL  --APPROVE----------> APPROVED
  PENDING_APPROVAL  --REJECT-----------> REJECTED

Resubmission after rejection is NOT a direct REJECTED -> PENDING_APPROVAL
transition. By design, a rejected document must go through the existing
validation pipeline again (re-run extraction/validation as needed,
reaching VALIDATED) before approval can be re-requested -- this
guarantees any fix was actually re-checked, not just resubmitted as-is.
REQUEST_APPROVAL is therefore only ever valid from VALIDATED, regardless
of whether the document is new or was previously rejected.
"""
import enum

from app.models.document_enums import DocumentStatus
from app.models.roles import UserRole


class WorkflowAction(str, enum.Enum):
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    APPROVE = "APPROVE"
    REJECT = "REJECT"

    @classmethod
    def values(cls) -> list[str]:
        return [a.value for a in cls]


# Maps (action) -> (required current status, resulting status)
TRANSITIONS: dict[WorkflowAction, tuple[str, str]] = {
    WorkflowAction.REQUEST_APPROVAL: (
        DocumentStatus.VALIDATED.value, DocumentStatus.PENDING_APPROVAL.value
    ),
    WorkflowAction.APPROVE: (
        DocumentStatus.PENDING_APPROVAL.value, DocumentStatus.APPROVED.value
    ),
    WorkflowAction.REJECT: (
        DocumentStatus.PENDING_APPROVAL.value, DocumentStatus.REJECTED.value
    ),
}

# Roles permitted to perform each action.
# - Any authenticated user who can already access the document (per
#   DocumentService's existing scoping rules) may request approval --
#   this mirrors who is allowed to upload/extract/validate in the first
#   place, since requesting approval is just "I'm done preparing this."
# - Only FINANCE_MANAGER, AUDITOR, and ADMIN may approve or reject,
#   per explicit instruction: analysts must not approve their own
#   submissions.
ALLOWED_ROLES: dict[WorkflowAction, tuple[UserRole, ...] | None] = {
    WorkflowAction.REQUEST_APPROVAL: None,  # None = any role with document access
    WorkflowAction.APPROVE: (UserRole.FINANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN),
    WorkflowAction.REJECT: (UserRole.FINANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN),
}

# Rejection requires a mandatory comment (so the analyst knows what to
# fix); approval comments are optional.
COMMENT_REQUIRED: dict[WorkflowAction, bool] = {
    WorkflowAction.REQUEST_APPROVAL: False,
    WorkflowAction.APPROVE: False,
    WorkflowAction.REJECT: True,
}


def get_required_status(action: WorkflowAction) -> str:
    return TRANSITIONS[action][0]


def get_resulting_status(action: WorkflowAction) -> str:
    return TRANSITIONS[action][1]


def is_role_allowed(action: WorkflowAction, role: str) -> bool:
    allowed = ALLOWED_ROLES[action]
    if allowed is None:
        return True
    return role in {r.value for r in allowed}


def is_comment_required(action: WorkflowAction) -> bool:
    return COMMENT_REQUIRED[action]

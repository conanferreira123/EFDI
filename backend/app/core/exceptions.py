"""
Domain-specific exception hierarchy.

Using typed exceptions (instead of raising HTTPException directly inside
services/repositories) keeps the business logic layer decoupled from
FastAPI/HTTP concerns. Routers/handlers translate these into proper
HTTP responses via the global exception handlers registered in main.py.
"""


class EFDIException(Exception):
    """Base class for all application-specific exceptions."""

    def __init__(self, message: str, *, status_code: int = 500, details: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundException(EFDIException):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str, identifier: str | int | None = None):
        message = f"{resource} not found"
        if identifier is not None:
            message = f"{resource} with id '{identifier}' not found"
        super().__init__(message, status_code=404, details={"resource": resource, "id": identifier})


class AlreadyExistsException(EFDIException):
    """Raised when attempting to create a resource that violates a uniqueness constraint."""

    def __init__(self, resource: str, field: str, value: str):
        message = f"{resource} with {field} '{value}' already exists"
        super().__init__(message, status_code=409, details={"resource": resource, "field": field, "value": value})


class ValidationFailedException(EFDIException):
    """Raised when input data or business-rule validation fails."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message, status_code=422, details={"errors": errors or []})


class AuthenticationException(EFDIException):
    """Raised when credentials are missing or invalid."""

    def __init__(self, message: str = "Invalid authentication credentials"):
        super().__init__(message, status_code=401)


class AuthorizationException(EFDIException):
    """Raised when an authenticated user lacks permission for an action."""

    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(message, status_code=403)


class FileProcessingException(EFDIException):
    """Raised when file upload, storage, or processing (OCR, parsing) fails."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, status_code=422, details=details)


class WorkflowException(EFDIException):
    """Raised when an invalid workflow state transition is attempted."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, status_code=409, details=details)


class AIServiceException(EFDIException):
    """Raised when an AI service, model invocation, or LLM agent fails."""

    error_name = "AI Service Error"

    def __init__(
        self,
        message: str = "Something went wrong while processing your request. Please try again.",
        *,
        status_code: int = 502,
        details: dict | None = None,
    ):
        super().__init__(message, status_code=status_code, details=details)

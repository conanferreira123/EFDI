"""
Document type and workflow status enums.

DocumentType reflects the real enterprise AP/R2R document taxonomy
provided by the client (AP-AR_DocuementTypes.xlsx), not a generic
placeholder set:

AP (Accounts Payable):
  POI - PO-based vendor invoice
  NPO - Non-PO-based invoice
  IMA - Employee reimbursement claim
  (DPR - Down payment request: exists in the taxonomy but the client's
   field-mapping sheet defines no extractable fields for it yet)

R2R (Accounts Receivable / GL / FA):
  MSI - Sales invoicing
  PSI - Pay-in-slip / customer receipt
  JER - Journal entry
  BKA - Bank document
  (LCA - Letter of credit: exists in the taxonomy but, like DPR, has no
   fields defined yet)

DPR and LCA are included as real enum values (they classify and can be
stored) but Phase 6 extraction is a documented no-op for them until the
client provides their field definitions -- see
app/extraction/field_schemas.py.

DocumentStatus matches the full Phase 8 workflow state machine -- defined
now (Phase 3) so the Document model's `status` column has its final,
complete set of valid values from the start, even though only UPLOADED
was reachable until OCR (Phase 4); classification (Phase 5) updates
document_type without changing status; extraction (Phase 6) is what
advances status to EXTRACTED.
"""
import enum


class DocumentType(str, enum.Enum):
    POI = "POI"  # PO-based vendor invoice
    NPO = "NPO"  # Non-PO-based invoice
    IMA = "IMA"  # Employee reimbursement claim
    MSI = "MSI"  # Sales invoice
    PSI = "PSI"  # Pay-in-slip / customer receipt
    JER = "JER"  # Journal entry
    BKA = "BKA"  # Bank document
    DPR = "DPR"  # Down payment request (no fields defined yet)
    LCA = "LCA"  # Letter of credit (no fields defined yet)
    UNKNOWN = "UNKNOWN"

    @classmethod
    def values(cls) -> list[str]:
        return [t.value for t in cls]

    @classmethod
    def types_with_defined_fields(cls) -> list["DocumentType"]:
        """Types that have an extraction field schema defined (excludes DPR, LCA, UNKNOWN)."""
        return [cls.POI, cls.NPO, cls.IMA, cls.MSI, cls.PSI, cls.JER, cls.BKA]


class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    OCR_COMPLETED = "OCR_COMPLETED"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    @classmethod
    def values(cls) -> list[str]:
        return [s.value for s in cls]


class AuditAction(str, enum.Enum):
    """
    Every user action the audit trail tracks. Deliberately one flat
    enum (not split per-resource) so a single AuditLog table and a
    single GET /audit/logs?action= filter can answer "show me every
    REJECT in the system" or "show me everyone who logged in today"
    without joining across resource-specific tables.
    """
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    USER_REGISTERED = "USER_REGISTERED"

    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_DELETED = "DOCUMENT_DELETED"

    OCR_RUN = "OCR_RUN",
    OCR_STARTED = "OCR_STARTED",
    OCR_COMPLETED = "OCR_COMPLETED",
    OCR_FAILED = "OCR_FAILED"
    CLASSIFICATION_RUN = "CLASSIFICATION_RUN"
    EXTRACTION_RUN = "EXTRACTION_RUN"
    EXTRACTION_FIELD_CORRECTED = "EXTRACTION_FIELD_CORRECTED"
    CLASSIFICATION_CORRECTED = "CLASSIFICATION_CORRECTED"
    VALIDATION_RUN = "VALIDATION_RUN"

    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    DOCUMENT_APPROVED = "DOCUMENT_APPROVED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"

    @classmethod
    def values(cls) -> list[str]:
        return [a.value for a in cls]


class PaymentStatus(str, enum.Enum):
    """Payment obligation status representing accounting state."""
    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"

    @classmethod
    def values(cls) -> list[str]:
        return [s.value for s in cls]


class ChunkSection(str, enum.Enum):
    """First-class semantic section for document_chunks in RAG retrieval."""
    HEADER = "HEADER"
    SELLER = "SELLER"
    BUYER = "BUYER"
    INVOICE_INFORMATION = "INVOICE_INFORMATION"
    LINE_ITEMS = "LINE_ITEMS"
    TAX = "TAX"
    TOTALS = "TOTALS"
    PAYMENT = "PAYMENT"
    REFERENCES = "REFERENCES"
    FOOTER = "FOOTER"
    OTHER = "OTHER"

    @classmethod
    def values(cls) -> list[str]:
        return [s.value for s in cls]


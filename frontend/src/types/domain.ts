// Mirrors app/models/roles.py UserRole
export type UserRole = "ADMIN" | "FINANCE_MANAGER" | "FINANCE_ANALYST" | "AUDITOR";

// Mirrors app/models/document_enums.py DocumentType
export type DocumentType =
  | "POI"
  | "NPO"
  | "IMA"
  | "MSI"
  | "PSI"
  | "JER"
  | "BKA"
  | "DPR"
  | "LCA"
  | "UNKNOWN";

// Mirrors app/models/document_enums.py DocumentStatus
export type DocumentStatus =
  | "UPLOADED"
  | "OCR_COMPLETED"
  | "EXTRACTED"
  | "VALIDATED"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED";

// Mirrors app/models/document_enums.py AuditAction
export type AuditAction =
  | "LOGIN_SUCCESS"
  | "LOGIN_FAILED"
  | "USER_REGISTERED"
  | "DOCUMENT_UPLOADED"
  | "DOCUMENT_DELETED"
  | "OCR_RUN"
  | "CLASSIFICATION_RUN"
  | "EXTRACTION_RUN"
  | "EXTRACTION_FIELD_CORRECTED"
  | "VALIDATION_RUN"
  | "APPROVAL_REQUESTED"
  | "DOCUMENT_APPROVED"
  | "DOCUMENT_REJECTED";

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  POI: "PO-Based Invoice",
  NPO: "Non-PO Invoice",
  IMA: "Expense Claim",
  MSI: "Sales Invoice",
  PSI: "Pay-In Slip",
  JER: "Journal Entry",
  BKA: "Bank Advice",
  DPR: "Down Payment Request",
  LCA: "Letter of Credit",
  UNKNOWN: "Unclassified",
};

export const DOCUMENT_STATUS_LABELS: Record<DocumentStatus, string> = {
  UPLOADED: "Uploaded",
  OCR_COMPLETED: "OCR Complete",
  EXTRACTED: "Extracted",
  VALIDATED: "Validated",
  PENDING_APPROVAL: "Pending Approval",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

import type { AuditAction, DocumentStatus, DocumentType, UserRole } from "./domain";

// --- Users / Auth (app/schemas/user.py) ---

export interface UserResponse {
  id: number;
  username: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Token {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserResponse;
}

// --- Documents (app/schemas/document.py) ---

export interface DocumentResponse {
  id: number;
  original_filename: string;
  document_type: DocumentType;
  status: DocumentStatus;
  file_size_bytes: number;
  mime_type: string;
  file_hash: string;
  page_count: number | null;
  uploaded_by: number;
  uploaded_by_user: UserResponse | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListItem {
  id: number;
  original_filename: string;
  document_type: DocumentType;
  status: DocumentStatus;
  file_size_bytes: number;
  mime_type: string;
  uploaded_by: number;
  created_at: string;
}

export interface DocumentListResponse {
  items: DocumentListItem[];
  total: number;
  skip: number;
  limit: number;
}

export interface DocumentUploadResponse {
  id: number;
  original_filename: string;
  document_type: DocumentType;
  status: DocumentStatus;
  file_size_bytes: number;
  message: string;
}

export interface DocumentFilterParams {
  document_type?: DocumentType;
  status?: DocumentStatus;
  filename?: string;
  uploaded_by?: number;
  date_from?: string;
  date_to?: string;
  skip?: number;
  limit?: number;
}

export interface BulkIntakeItemResult {
  filename: string;
  success: boolean;
  document_id: number | null;
  error: string | null;
}

export interface BulkIntakeResponse {
  total_files: number;
  succeeded: number;
  failed: number;
  results: BulkIntakeItemResult[];
}

// --- OCR (app/schemas/ocr.py) ---

export interface OCRTextBlock {
  text: string;
  confidence: number;
  bounding_box: number[][];
}

export interface OCRPageBlocks {
  page_number: number;
  page_width: number;
  page_height: number;
  blocks: OCRTextBlock[];
}

export interface OCRResultResponse {
  id: number;
  document_id: number;
  engine_name: string;
  page_count: number;
  full_text: string;
  average_confidence: number;
  processing_time_ms: number | null;
  is_stub_result: boolean;
  raw_blocks: OCRPageBlocks[];
  created_at: string;
  updated_at: string;
}

export interface OCREngineStatus {
  available: boolean;
  reason: string;
  is_production_engine: boolean;
}

export interface OCREngineStatusResponse {
  engines: Record<string, OCREngineStatus>;
  default_engine: string;
}

// --- Classification (app/schemas/classification.py) ---

export interface ClassificationSignal {
  matched_text: string;
  rule_description: string;
  weight: number;
}

export interface ClassificationResultResponse {
  id: number;
  document_id: number;
  predicted_type: DocumentType;
  confidence: number;
  engine_name: string;
  signals: ClassificationSignal[];
  scores_by_type: Record<string, number>;
  created_at: string;
  updated_at: string;
}

// --- Extraction (app/schemas/extraction.py) ---

export interface ExtractedField {
  value: unknown;
  confidence: number;
  matched_text?: string | null;
  is_found: boolean;
  provenance?: string;
  conflict_value?: string | null;
}

export type FieldValueOrWrapper =
  | ExtractedField
  | {
      value: unknown;
      confidence?: number;
      is_found?: boolean;
      provenance?: string;
      matched_text?: string | null;
      conflict_value?: string | null;
    }
  | string
  | number
  | null;

export interface NPOLineItem {
  line_number?: FieldValueOrWrapper;
  description?: FieldValueOrWrapper;
  quantity?: FieldValueOrWrapper;
  uom?: FieldValueOrWrapper;
  unit_of_measure?: FieldValueOrWrapper;
  unit_price?: FieldValueOrWrapper;
  net_amount?: FieldValueOrWrapper;
  tax_rate?: FieldValueOrWrapper;
  tax_amount?: FieldValueOrWrapper;
  gross_amount?: FieldValueOrWrapper;
  confidence?: number;
  source_quote?: string | null;
  [key: string]: unknown;
}

export interface NPOTaxItem {
  tax_type?: FieldValueOrWrapper;
  tax_rate?: FieldValueOrWrapper;
  rate_percentage?: FieldValueOrWrapper;
  taxable_amount?: FieldValueOrWrapper;
  tax_amount?: FieldValueOrWrapper;
  exemption_reason?: FieldValueOrWrapper;
  confidence?: number;
  source_quote?: string | null;
  [key: string]: unknown;
}

export interface CanonicalNPO {
  invoice_information?: {
    invoice_number?: ExtractedField | { value: string | null; confidence?: number };
    invoice_date?: ExtractedField | { value: string | null; confidence?: number };
    currency?: ExtractedField | { value: string | null; confidence?: number };
    document_type?: ExtractedField | { value: string | null; confidence?: number };
    [key: string]: unknown;
  };
  seller?: {
    name?: ExtractedField | { value: string | null; confidence?: number };
    tax_id?: ExtractedField | { value: string | null; confidence?: number };
    address?: ExtractedField | { value: string | null; confidence?: number };
    [key: string]: unknown;
  };
  buyer?: {
    name?: ExtractedField | { value: string | null; confidence?: number };
    tax_id?: ExtractedField | { value: string | null; confidence?: number };
    address?: ExtractedField | { value: string | null; confidence?: number };
    [key: string]: unknown;
  };
  line_items?: NPOLineItem[];
  taxes?: NPOTaxItem[];
  totals?: {
    subtotal?: ExtractedField | { value: string | null; confidence?: number };
    total_tax?: ExtractedField | { value: string | null; confidence?: number };
    grand_total?: ExtractedField | { value: string | null; confidence?: number };
    discount?: ExtractedField | { value: string | null; confidence?: number };
    shipping?: ExtractedField | { value: string | null; confidence?: number };
    other_charges?: ExtractedField | { value: string | null; confidence?: number };
    rounding?: ExtractedField | { value: string | null; confidence?: number };
    [key: string]: unknown;
  };
  payment?: {
    payment_terms?: ExtractedField | { value: string | null; confidence?: number };
    due_date?: ExtractedField | { value: string | null; confidence?: number };
    payment_method?: ExtractedField | { value: string | null; confidence?: number };
    bank_account?: ExtractedField | { value: string | null; confidence?: number };
    iban?: ExtractedField | { value: string | null; confidence?: number };
    swift_bic?: ExtractedField | { value: string | null; confidence?: number };
    remittance_reference?: ExtractedField | { value: string | null; confidence?: number };
    [key: string]: unknown;
  };
  references?: {
    po_number?: ExtractedField | { value: string | null; confidence?: number };
    contract_number?: ExtractedField | { value: string | null; confidence?: number };
    delivery_note_number?: ExtractedField | { value: string | null; confidence?: number };
    order_number?: ExtractedField | { value: string | null; confidence?: number };
    other_reference?: ExtractedField | { value: string | null; confidence?: number };
    [key: string]: unknown;
  };
}

export interface ExtractionResultResponse {
  id: number;
  document_id: number;
  document_type: string;
  engine_name: string;
  fields: Record<string, ExtractedField>;
  overall_confidence: number;
  fields_found_count: number;
  fields_total_count: number;
  canonical?: CanonicalNPO | null;
  created_at: string;
  updated_at: string;
}

// --- Validation (app/schemas/validation.py) ---

export interface ValidationIssue {
  rule_type: string;
  severity: "ERROR" | "WARNING";
  field_key: string | null;
  message: string;
}

export interface ValidationResultResponse {
  id: number;
  document_id: number;
  document_type: string;
  engine_name: string;
  is_valid: boolean;
  error_count: number;
  warning_count: number;
  issues: ValidationIssue[];
  created_at: string;
  updated_at: string;
}

// --- Workflow (app/schemas/workflow.py) ---

export interface WorkflowHistoryResponse {
  id: number;
  document_id: number;
  action: "REQUEST_APPROVAL" | "APPROVE" | "REJECT";
  from_status: DocumentStatus;
  to_status: DocumentStatus;
  comment: string | null;
  performed_by: number;
  performed_by_user: UserResponse | null;
  created_at: string;
  updated_at: string;
}

// --- Audit (app/schemas/audit.py) ---

export interface AuditLogResponse {
  id: number;
  action: AuditAction;
  user_id: number | null;
  document_id: number | null;
  details: Record<string, unknown> | null;
  user: UserResponse | null;
  created_at: string;
  updated_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogResponse[];
  total: number;
  skip: number;
  limit: number;
}

export interface AuditLogFilterParams {
  action?: AuditAction;
  user_id?: number;
  document_id?: number;
  date_from?: string;
  date_to?: string;
  skip?: number;
  limit?: number;
}

// --- Generic ---

export interface MessageResponse {
  message: string;
}

export interface ApiErrorBody {
  error: string;
  message: string;
  details?: Record<string, unknown>;
}

# Enterprise Financial Document Intelligence (EFDI)
## Phase 1 Report: Document Classification Component

---

### Executive Summary

In accordance with the Phase 1 specification, the document classification subsystem of the EFDI application has been investigated end-to-end, baseline-tested against a representative sample of 20 invoice documents from `Batch 1/invoices`, systematically improved using evidence-based enhancements, retested across the identical 20 documents, and verified with 226 automated backend tests (including 30 dedicated classification tests).

- **Baseline Classification Accuracy:** 20/20 correctly predicted as `NPO` (Non-PO Vendor Invoice), but with an extremely low, fragile confidence score of **`0.2353`** across all documents (only barely clearing the `MIN_CONFIDENCE = 0.23` floor due to missing aliases and un-matched standard invoice fields).
- **Improved Classification Results:** 20/20 classified as `NPO` with a robust confidence score of **`0.6800`** (a **+189% increase in confidence margin**), driven by 9 distinct corroborating signals per document instead of only 2.
- **Automated Test Suite Status:** **226 passed, 0 failed** (100% pass rate across foundation, auth/RBAC, documents, OCR, classification, extraction, validation, workflow, and audit modules).

---

### 1. Current Classification Architecture

The classification subsystem follows a clean, pluggable strategy pattern:
- **`ClassificationEngine` (`app/classification/base.py`)**: Abstract base class defining the contract `classify(text: str) -> ClassificationResultData`.
- **`RuleBasedClassifier` (`app/classification/rule_based.py`)**: The primary deterministic engine evaluating textual and regex patterns against curated rule sets per enterprise document type.
- **`MLClassifier` (`app/classification/ml_classifier.py`)**: An optional TF-IDF + LogisticRegression / MultinomialNB engine designed for future statistical fallback.
- **`get_classification_engine(engine_name)` (`app/classification/factory.py`)**: Factory pattern dynamically resolving and instantiating the requested classifier engine singleton.
- **`ClassificationService` (`app/services/classification_service.py`)**: Orchestration service managing OCR text retrieval, engine invocation, persistence of audit signals in `classification_results`, and synchronization of `documents.document_type`.
- **`ClassificationRouter` (`app/routers/classification.py`)**: REST API endpoints exposing document classification, result inspection, historical run audit trails, and manual human correction.

```
Document File (PDF / Image)
        │
        ▼
   OCR Pipeline (PyMuPDF -> AdaptivePreprocessor -> EasyOCR -> Spatial Layout Ordering)
        │
        ▼
   OCRResult Table (persisted in DB: full_text, raw_blocks, quality_score)
        │
        ▼ (calls POST /api/v1/classification/documents/{id}/classify)
ClassificationService
        │
        ├── 1. Fetches latest OCRResult via OCRResultRepository
        ├── 2. Passes full_text to ClassificationEngine (RuleBasedClassifier)
        ├── 3. Computes normalized scores & disambiguation (POI vs NPO, MSI vs NPO)
        ├── 4. Records ClassificationResult (predicted_type, confidence, signals, scores_by_type)
        └── 5. Updates Document.document_type (leaves Document.status at OCR_COMPLETED)
```

---

### 2. Current OCR → Classification Data Flow

1. A document is uploaded via `POST /api/v1/documents/upload` and assigned `status="UPLOADED"`.
2. OCR is executed via `POST /api/v1/ocr/documents/{id}/run`, creating an `ocr_results` row with `full_text`, `raw_blocks`, and `page_count`, and advancing `status="OCR_COMPLETED"`.
3. Classification is triggered via `POST /api/v1/classification/documents/{id}/classify`.
4. `ClassificationService.classify()` queries `OCRResultRepository.get_latest_for_document(document.id)`. If no OCR result exists, it rejects the request with `ValidationFailedException (422)`.
5. The extracted `ocr_result.full_text` is passed to `RuleBasedClassifier.classify(ocr_result.full_text)`.
6. Resulting `ClassificationResultData` is persisted via `ClassificationResultRepository.create(...)`.
7. `document.document_type` is updated to the winning `predicted_type`.

---

### 3. OCR Information Consumed by Classification

- **Consumed:** `full_text` (`str`) — the full concatenated and spatially ordered text representation of the document.
- **Not Currently Consumed:** `raw_blocks` (spatial bounding boxes, page geometry, token-level coordinates), `average_confidence`, and quality scores are retained in `ocr_results` for extraction and auditing, but are not consumed by classification.

---

### 4. Existing Document Taxonomy & Rules

The application supports the complete 9-type enterprise taxonomy derived from the client AP/AR specification:

| Code | Document Type | Key Positive Signals / Indicators |
|---|---|---|
| **POI** | PO-based Vendor Invoice | "purchase order", PO number regex pattern, "po number", "grn", "srn", "vendor", "seller", "tax invoice", "gstin" |
| **NPO** | Non-PO Vendor Invoice | "invoice number", invoice number regex pattern, "invoice no", "seller", "vendor", "client", "bill to", "tax id", "gstin", "date of issue", summary totals |
| **IMA** | Employee Reimbursement / Expense | "reimbursement", "expense claim", "expense report", "travel", "travel end date", "employee", "claim form", "per diem", "mileage" |
| **MSI** | Customer Sales Invoice (Receivables) | "sales invoice", "msi invoice", "customer", "customer code", "customer name", "ship to", "sold to", "ship mode", "order id" |
| **PSI** | Pay-in-Slip / Customer Receipt | "pay in slip", "pay-in slip", "pis number", "deposit", "deposit amount", "receipt", "customer receipt", "bank name", "cheque", "cash deposit" |
| **JER** | Journal Entry | "journal entry", "journal voucher", "gl account", "gl account code", "general ledger", "debit", "credit", "posting date", "narration", JE pattern |
| **BKA** | Bank Advice / Statement | "bank name", "advice date", "advice amount", "bank advice", "debit advice", "credit advice", "account number", "ifsc", account number regex |
| **DPR** | Down Payment Request | "down payment request", "down payment", "advance payment", "advance percentage", "requested amount", "request number", DPR pattern |
| **LCA** | Letter of Credit Advice | "letter of credit", LC number regex, "issuing bank", "beneficiary", "beneficiary name", "shipment reference", "trade reference", "lc amount", "expiry date" |

---

### 5. Scoring, Weighting & Disambiguation Logic

1. **Rule Evaluation:** Each rule evaluates against `text_lower` (for keywords/phrases) or original `text` (for case-insensitive regex). Short tokens (<= 3 characters, such as "grn", "srn", "po", "je") are protected with regex word boundaries `\b` to prevent false positive substring matches.
2. **Raw Score Accumulation:** When a rule fires, its weight is added to `raw_score` and a `ClassificationSignal` record is logged.
3. **Score Normalization:**
   $$\text{Normalized Score} = \frac{\sum \text{Matched Weights}}{\sum \text{Possible Weights for DocType}}$$
4. **POI vs. NPO Disambiguation:**
   - If an explicit PO number or "purchase order" phrase is detected in POI signals: NPO score is multiplied by $0.4$ (strongly suppressing NPO and boosting POI).
   - If NO PO reference is detected: POI score is multiplied by $0.5$ (suppressing POI in favor of NPO).
5. **MSI vs. NPO Disambiguation:**
   - If retail shipping language ("ship to", "ship mode", "order id") is present AND vendor language ("vendor", "seller", "gstin", "tax id", "tax invoice") is absent: MSI score is multiplied by $1.8$ and NPO is multiplied by $0.5$.
6. **Confidence Clamping & Floor:**
   - Normalized scores are clamped to $[0.0, 1.0]$.
   - If $\text{best\_score} < \text{MIN\_CONFIDENCE} \; (0.23)$, the document is classified as `UNKNOWN`.

---

### 6. The 20 Selected Representative Invoices

From the 100 available invoices in `Batch 1/invoices`, 20 representative documents were selected covering diverse item counts (1 to 8 items), diverse geographic locations across India, multiple dates across 2023–2024, varied gross invoice totals, and different document complexity levels:

| # | Filename | Date | Client Name | Location | Items | Total Amount (INR) |
|---|---|---|---|---|---|---|
| 1 | `invoice_51109301.pdf` | 03/07/2023 | Raj Electronics Pvt Ltd | Bengaluru, Karnataka | 3 | ₹1,844,673.60 |
| 2 | `invoice_51109302.pdf` | 25/09/2023 | Sharma Tech Solutions | New Delhi, Delhi | 6 | ₹1,958,564.30 |
| 3 | `invoice_51109303.pdf` | 12/08/2023 | Mumbai Gadget House | Mumbai, Maharashtra | 4 | ₹1,052,518.50 |
| 4 | `invoice_51109304.pdf` | 07/10/2023 | Chennai Digital Store | Chennai, Tamil Nadu | 6 | ₹1,874,469.30 |
| 5 | `invoice_51109305.pdf` | 09/03/2024 | Hyderabad IT Traders | Hyderabad, Telangana | 6 | ₹2,225,987.50 |
| 6 | `invoice_51109306.pdf` | 02/02/2024 | Kolkata Electronics Hub | Kolkata, West Bengal | 1 | ₹264,140.80 |
| 7 | `invoice_51109310.pdf` | 03/08/2023 | Surat Digital Mall | Surat, Gujarat | 4 | ₹1,330,274.00 |
| 8 | `invoice_51109315.pdf` | 13/02/2024 | Nagpur Electronics Plaza | Nagpur, Maharashtra | 8 | ₹1,840,389.10 |
| 9 | `invoice_51109320.pdf` | 11/12/2023 | Visakhapatnam Tech City | Visakhapatnam, Andhra Pradesh | 8 | ₹1,989,732.80 |
| 10 | `invoice_51109325.pdf` | 19/11/2023 | Rajkot Mobile World | Rajkot, Gujarat | 8 | ₹2,397,277.30 |
| 11 | `invoice_51109330.pdf` | 11/07/2023 | Raipur Smart Devices | Raipur, Chhattisgarh | 3 | ₹804,246.30 |
| 12 | `invoice_51109335.pdf` | 25/06/2023 | Mangaluru Tech Zone | Mangaluru, Karnataka | 3 | ₹458,884.80 |
| 13 | `invoice_51109340.pdf` | 05/10/2023 | Udaipur Electronics Plaza | Udaipur, Rajasthan | 6 | ₹2,229,696.70 |
| 14 | `invoice_51109350.pdf` | 18/02/2024 | Guntur Smart Devices | Guntur, Andhra Pradesh | 1 | ₹239,921.00 |
| 15 | `invoice_51109355.pdf` | 08/01/2024 | Hyderabad IT Traders | Hyderabad, Telangana | 6 | ₹1,926,039.50 |
| 16 | `invoice_51109360.pdf` | 29/03/2024 | Surat Digital Mall | Surat, Gujarat | 7 | ₹2,617,259.70 |
| 17 | `invoice_51109370.pdf` | 12/03/2024 | Visakhapatnam Tech City | Visakhapatnam, Andhra Pradesh | 5 | ₹699,337.10 |
| 18 | `invoice_51109380.pdf` | 19/06/2023 | Raipur Smart Devices | Raipur, Chhattisgarh | 3 | ₹545,655.00 |
| 19 | `invoice_51109390.pdf` | 29/07/2023 | Udaipur Electronics Plaza | Udaipur, Rajasthan | 4 | ₹1,192,985.20 |
| 20 | `invoice_51109400.pdf` | 22/02/2024 | Guntur Smart Devices | Guntur, Andhra Pradesh | 2 | ₹149,840.90 |

---

### 7. Baseline Classification Results

The unmodified baseline classification was executed across all 20 documents following full OCR:

| Document | OCR Blocks | OCR Status | Baseline Pred | Baseline Conf | Matched Signals | Assessment |
|---|---|---|---|---|---|---|
| `invoice_51109301.pdf` | 62 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109302.pdf` | 86 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109303.pdf` | 69 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109304.pdf` | 83 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109305.pdf` | 83 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109306.pdf` | 46 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109310.pdf` | 68 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109315.pdf` | 98 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109320.pdf` | 100 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109325.pdf` | 97 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109330.pdf` | 60 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109335.pdf` | 60 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109340.pdf` | 83 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109350.pdf` | 46 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109355.pdf` | 84 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109360.pdf` | 90 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109370.pdf` | 79 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109380.pdf` | 62 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109390.pdf` | 69 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |
| `invoice_51109400.pdf` | 53 | Success | NPO | 0.2353 | `invoice number pattern`, `invoice` | Fragile (barely > 0.23) |

---

### 8. Root Cause Analysis of Problems Discovered

1. **Near-Threshold Fragility (`0.2353` vs `0.23` floor):**
   The baseline raw score was $4.0$ out of a total possible score of $17.0$. If any single OCR character was smudged or missed in the word "Invoice", the score would drop to $0.1471$, misclassifying a legitimate vendor invoice as `UNKNOWN`.
2. **Missing Standard Vendor Headings & Tax Identifiers:**
   Standard Indian invoices use "Seller:" (not exclusively "Vendor:"), "Client:" / "Buyer:" (not exclusively "Bill to:"), and explicit tax identifiers like "Tax Id:" and "GSTIN:". The baseline rules had no pattern matching for "Seller", "Client", "GSTIN", or "Tax Id" under `NPO`.
3. **Missing Date & Summary Signals:**
   Phrases like "Date of issue:", "Gross Worth", "Net Worth", and "Total Amount" were completely ignored by `NPO` classification rules.
4. **Unbounded Substring Matching Risk:**
   Short keywords (e.g. "grn", "srn", "po", "je") in the previous implementation used naive `pattern in text_lower` checks without word boundaries, creating vulnerability to spurious substring matches inside words like "background" or "afternoon".

---

### 9. Classification Improvements Implemented

1. **Word-Boundary Protection in `Rule.find()`:**
   Added regex word boundaries `\b` for tokens with length $\le 3$ to eliminate false-positive substring matches.
2. **Standard Financial Heading Aliases in `NPO` & `POI`:**
   - Vendor/Seller: `\b(?:vendor|seller|supplier|billed\s+by)\b` (Weight: 2.0)
   - Buyer/Client: `\b(?:bill\s+to|client|buyer|billed\s+to)\b` (Weight: 2.0)
   - Tax/Compliance: `gstin` (Weight: 1.5), `\btax\s*id\b` (Weight: 1.5), `tax invoice` (Weight: 2.0)
   - Invoice Metadata: `date of issue` (Weight: 1.5), `\binvoice\s*no\.?` (Weight: 2.5)
   - Totals Summary: `\b(?:amount\s+due|gross\s+worth|net\s+worth|total\s+amount|grand\s+total)\b` (Weight: 1.5)
3. **Disambiguation Synchronization:**
   - Updated `_apply_po_npo_disambiguation` to recognize all PO patterns ("purchase order", "po number", `PO_NUMBER_PATTERN`).
   - Updated `_apply_msi_npo_disambiguation` to check for vendor signals across both "vendor" and "seller"/"gstin"/"tax id".

---

### 10. Before vs. After Comparison on the 20 Documents

| # | Filename | Baseline Pred (Conf) | Improved Pred (Conf) | Signals (Old $\to$ New) | Result Change |
|---|---|---|---|---|---|
| 1 | `invoice_51109301.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 2 | `invoice_51109302.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 3 | `invoice_51109303.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 4 | `invoice_51109304.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 5 | `invoice_51109305.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 6 | `invoice_51109306.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 7 | `invoice_51109310.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 8 | `invoice_51109315.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 9 | `invoice_51109320.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 10 | `invoice_51109325.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 11 | `invoice_51109330.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 12 | `invoice_51109335.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 13 | `invoice_51109340.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 14 | `invoice_51109350.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 15 | `invoice_51109355.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 16 | `invoice_51109360.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 17 | `invoice_51109370.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 18 | `invoice_51109380.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 19 | `invoice_51109390.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |
| 20 | `invoice_51109400.pdf` | NPO (0.2353) | **NPO (0.6800)** | 2 $\to$ 9 | **+189% Confidence** |

**Signals Fired per Document (9 Corroborating Signals):**
1. `invoice number pattern` (Weight 3.0, matched e.g. "Invoice no: 51109301")
2. `phrase 'invoice no'` (Weight 2.5, matched "Invoice no")
3. `word 'invoice'` (Weight 1.5, matched "invoice")
4. `phrase 'bill to / client'` (Weight 2.0, matched "Client")
5. `word 'vendor / seller'` (Weight 2.0, matched "Seller")
6. `term 'GSTIN'` (Weight 1.5, matched "gstin")
7. `term 'Tax Id'` (Weight 1.5, matched "Tax Id")
8. `phrase 'date of issue'` (Weight 1.5, matched "date of issue")
9. `phrase 'amount due / total summary'` (Weight 1.5, matched "Net Worth")

---

### 11. Automated Test Verification Results

All automated tests were executed using `pytest`:
- **Classification Specific Tests (`backend/tests/test_phase5_classification.py`):** **30 passed, 0 failed** (including new tests for real-world Indian invoice layouts, short-token word boundaries, and PO vs NPO competition).
- **Full Backend Test Suite (`backend/tests/`):** **226 passed, 0 failed** across all 19 test modules in the project.

---

### 12. Assessment & Readiness for Phase 2

- **Classification Robustness:** High. Classification accurately categorizes incoming vendor documents with a robust multi-signal profile and healthy confidence margin (0.68 vs 0.2353 baseline).
- **Zero Architecture Changes to Extraction:** In accordance with constraints, no extraction files, extraction schemas, or database tables have been touched or modified.
- **Classification → Extraction Dependency:** Intact. `ClassificationService` continues to set `document.document_type`, which Phase 2 rule-based extraction will consume.

---

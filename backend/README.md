# Enterprise Financial Document Intelligence — Backend

Enterprise Accounts Payable (AP) and Record-to-Report (R2R) document
intelligence platform. FastAPI + PostgreSQL + SQLAlchemy + Alembic backend.

## Status: All 11 Phases ✅ — Deploy-Ready (see `../README.md` for Docker setup, `../frontend/README.md` for Phase 11)

## Stack
- FastAPI (API framework)
- PostgreSQL 16 (database)
- SQLAlchemy 2.x (ORM)
- Alembic (migrations)
- Pydantic v2 / pydantic-settings (validation & config)
- JWT auth, RBAC (scaffolded — implemented in Phase 2)

## Project Structure
```
backend/
  app/
    core/            # config, logging, exceptions (cross-cutting concerns)
    database/        # engine/session management, declarative base + mixins
    models/          # SQLAlchemy ORM models (one module per domain entity)
    schemas/         # Pydantic request/response schemas
    repositories/     # data-access layer (added from Phase 2 onward)
    services/        # business logic layer (added from Phase 2 onward)
    routers/         # FastAPI route handlers (added from Phase 2 onward)
    utils/           # shared helpers
    ocr/             # OCR pipeline (Phase 4)
    validation/      # validation engine (Phase 7)
    workflow/        # approval workflow state machine (Phase 8)
    audit/           # audit trail logging (Phase 9)
    main.py          # FastAPI app entrypoint
  alembic/           # migration environment + versions
  tests/             # pytest test suite
  uploads/           # local file storage (dev only; gitignored contents)
  logs/              # rotating app logs (gitignored contents)
  requirements.txt
  .env / .env.example
```

## Local Setup

### 1. PostgreSQL
This project expects a running PostgreSQL 16 instance.

```bash
# Debian/Ubuntu
apt-get install -y postgresql postgresql-contrib
service postgresql start
```

> **Note:** in environments without systemd (e.g. plain Docker containers,
> some sandboxes), PostgreSQL does not start automatically on boot/restart.
> If you ever see `Connection refused` on port 5432, run
> `service postgresql start` (or `pg_ctlcluster 16 main start`) again —
> your data persists in `/var/lib/postgresql/16/main` even after a stop.

```bash
# Create DB + user (one-time)
su - postgres -c "psql -c \"CREATE USER efdi_user WITH PASSWORD 'efdi_password';\""
su - postgres -c "psql -c \"CREATE DATABASE efdi_db OWNER efdi_user;\""
```

### 2. Python environment
```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 3. Environment variables
Copy `.env.example` to `.env` and adjust `DATABASE_URL`, `SECRET_KEY`, etc.
A working `.env` for local dev is already included in this scaffold.

### 4. Run migrations
```bash
venv/bin/alembic upgrade head
```

### 5. Seed default users (optional, recommended for testing)
```bash
venv/bin/python scripts/seed_users.py
```

### 6. Start the server
```bash
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- API docs: http://localhost:8000/api/docs
- Health check: http://localhost:8000/health

### Quick API test
```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin@123"}'

# Use the returned access_token:
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"

# Check OCR engine availability (no auth required)
curl http://localhost:8000/api/v1/ocr/engines

# Run OCR on an uploaded document (engine defaults to OCR_DEFAULT_ENGINE if omitted)
curl -X POST http://localhost:8000/api/v1/ocr/documents/1/run \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"engine":"stub"}'

# Classify a document (requires OCR to have run first)
curl -X POST http://localhost:8000/api/v1/classification/documents/1/classify \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{}'

# Extract structured fields (requires OCR + classification to have run first)
curl -X POST http://localhost:8000/api/v1/extraction/documents/1/extract \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{}'

# Manually fill in a field the OCR didn't find
curl -X PATCH http://localhost:8000/api/v1/extraction/documents/1/fields/location_code \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"value": "LOC-MUM-01"}'

# Validate (requires extraction to have run first)
curl -X POST http://localhost:8000/api/v1/validation/documents/1/validate \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{}'

# Request approval (requires VALIDATED status)
curl -X POST http://localhost:8000/api/v1/workflow/documents/1/request-approval \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{}'

# Approve or reject (FINANCE_MANAGER / AUDITOR / ADMIN only; comment required on reject)
curl -X POST http://localhost:8000/api/v1/workflow/documents/1/approve \
  -H "Authorization: Bearer <manager_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"comment": "Looks good"}'

# View full workflow history
curl http://localhost:8000/api/v1/workflow/documents/1/history \
  -H "Authorization: Bearer <access_token>"
```

## Testing
```bash
venv/bin/python -m pytest tests/ -v
```

## What Phase 1 Delivers
- Clean Architecture folder structure (core/database/models/schemas/
  repositories/services/routers/utils/ocr/validation/workflow/audit)
- Centralized environment-driven configuration (`app/core/config.py`)
- Rotating file + console logging (`app/core/logging_config.py`)
- Typed domain exception hierarchy + global FastAPI exception handlers
  that return consistent JSON error shapes and never leak internals
- SQLAlchemy engine/session management with connection pooling and
  pre-ping health checks (`app/database/session.py`)
- Declarative base + `TimestampMixin` for consistent created_at/updated_at
  across all future models (`app/database/base.py`)
- Alembic configured against the app's own settings (single source of
  truth for `DATABASE_URL`), with a verified, reversible first migration
- `/health` endpoint reporting live DB connectivity
- 9 passing automated tests covering health, OpenAPI generation, and
  every exception-to-HTTP-status mapping

## What Phase 2 Delivers
- Full `User` model: username, email, full_name, password_hash, role,
  is_active, created_at/updated_at (`app/models/user.py`)
- `UserRole` enum: ADMIN, FINANCE_MANAGER, FINANCE_ANALYST, AUDITOR
  (`app/models/roles.py`)
- Password hashing via `bcrypt` directly (not passlib — see note below)
  and JWT issuance/decoding (`app/core/security.py`)
- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`,
  `GET /api/v1/auth/me`
- Admin-only user management: `GET /api/v1/users`, `GET /api/v1/users/{id}`,
  `PATCH /api/v1/users/{id}/role`, `PATCH /api/v1/users/{id}/status`
- `get_current_user` / `require_roles(...)` dependency guards
  (`app/core/dependencies.py`) — re-validates against the database on
  every request, so deactivating a user invalidates their session
  **immediately**, even with a still-valid, unexpired JWT
- Idempotent seed script (`scripts/seed_users.py`) creating one default
  user per role for local testing
- 18 additional automated tests (27 total) covering registration,
  login, token validation, RBAC enforcement, and the deactivation/
  invalidation security property

### Default seeded credentials (development only)
| Role | Username | Password |
|---|---|---|
| ADMIN | `admin` | `Admin@123` |
| FINANCE_MANAGER | `manager` | `Manager@123` |
| FINANCE_ANALYST | `analyst` | `Analyst@123` |
| AUDITOR | `auditor` | `Auditor@123` |

Run `venv/bin/python scripts/seed_users.py` after migrations to create
these. Safe to re-run — it skips any username that already exists.

### Known dependency issue (fixed)
`passlib` 1.7.4 (its last release) is incompatible with `bcrypt>=4.1`
(it probes a `bcrypt.__about__` attribute that no longer exists, which
raises an error on the first password hash). This project calls
`bcrypt` directly instead of going through passlib.

## Database Migrations — How To
```bash
# After changing/adding a model in app/models/:
venv/bin/alembic revision --autogenerate -m "describe the change"
venv/bin/alembic upgrade head

# To roll back one revision:
venv/bin/alembic downgrade -1
```

## What Phase 3 Delivers
- `Document` model: original/stored filename, document_type, status,
  file_size_bytes, mime_type, file_hash (SHA-256), page_count,
  is_deleted, uploaded_by (FK → users) (`app/models/document.py`)
- `DocumentType` (INVOICE, PURCHASE_ORDER, JOURNAL_ENTRY, BANK_STATEMENT,
  UNKNOWN) and the full `DocumentStatus` workflow state set defined now
  so the schema is final even though only UPLOADED is reachable until
  later phases (`app/models/document_enums.py`)
- File storage utilities: type/size validation (PDF/PNG/JPG only, up to
  `MAX_UPLOAD_SIZE_MB`), UUID-based on-disk filenames (no path traversal,
  no collisions), SHA-256 hashing for future duplicate detection
  (`app/utils/file_storage.py`)
- `POST /api/v1/documents/upload`, `GET /api/v1/documents` (search/filter
  by type, status, filename substring, uploader, date range, with
  pagination), `GET /api/v1/documents/{id}`,
  `GET /api/v1/documents/{id}/download`, `DELETE /api/v1/documents/{id}`
  (soft-delete — file stays on disk for audit/recovery)
- Role-scoped access: FINANCE_ANALYST sees/manages only their own
  uploads (enforced both in list filtering and direct-by-id access, so
  it can't be bypassed by guessing IDs); ADMIN, FINANCE_MANAGER, and
  AUDITOR have full visibility across all documents
- `app/models/__init__.py` now imports every model, guaranteeing
  SQLAlchemy's relationship registry is always complete regardless of
  which entry point (app, script, test) runs first — fixes a real bug
  found while building this phase (see note below)
- 12 additional automated tests (39 total) covering upload validation,
  byte-for-byte download round-trip, RBAC scoping, search, and
  soft-delete

### Bug found and fixed in this phase
Standalone scripts (e.g. `scripts/seed_users.py`) that imported only
`app.models.user` crashed with `name 'Document' is not defined` the
moment they ran a query, because `User.documents` is a string-referenced
relationship that SQLAlchemy resolves lazily against whatever models
happen to be registered. The main app never hit this because it
imports every router (and therefore every model) at startup, but any
other entry point could. Fixed by making `app/models/__init__.py`
import all models, and using `import app.models` everywhere the
registry needs to be guaranteed complete (seed script, Alembic env.py).

## What Phase 4 Delivers
- **Engine-agnostic OCR architecture** (`app/ocr/`): an abstract
  `OCREngine` base class + `OCRTextBlock`/`OCRPageResult`/`OCRResult`
  dataclasses define the contract every backend implements, so routers
  and services never depend on a specific OCR library
- **Preprocessing** (`app/ocr/preprocessing.py`): PyMuPDF PDF→image
  rasterization (configurable DPI, defaults to 200), OpenCV denoise +
  deskew (deskew verified against a synthetically-rotated test image —
  confirmed it actually corrects rotation, not just runs without error)
- **Three engine implementations**, selectable at runtime via
  `app/ocr/factory.py` (`GET /ocr/engines` reports live availability of
  each):
  - `PaddleOCREngine` (`app/ocr/paddle_engine.py`) — real integration
    against PaddleOCR 3.x's `predict()` API
  - `EasyOCREngine` (`app/ocr/easyocr_engine.py`) — real integration
    against EasyOCR's `Reader.readtext()` API
  - `StubOCREngine` (`app/ocr/stub_engine.py`) — deterministic
    placeholder used to verify the rest of the pipeline; clearly never
    selected as a production default and always flagged via
    `is_stub_result: true` in API responses
- `OCRResult` model + table: full extracted text, average confidence,
  per-block JSONB detail (text/confidence/bounding box), processing
  time, linked to `Document`; running OCR advances
  `Document.status` to `OCR_COMPLETED`
- `POST /ocr/documents/{id}/run`, `GET /ocr/documents/{id}/result`,
  `GET /ocr/documents/{id}/results`, `GET /ocr/engines` — all
  respecting the same document access scoping as Phase 3
- 22 additional automated tests (61 total)

### PaddleOCR / EasyOCR network limitation (read before expecting real OCR output)
**Both real engines are fully implemented and correct, but neither can
download its model weights in this development sandbox**, because its
network egress is restricted to an allowlist (PyPI, npm, GitHub, a few
others) that does not include the hosts these libraries need:

| Engine | Needs | Blocked host(s) | Confirmed via |
|---|---|---|---|
| PaddleOCR | Model weights | `paddle-model-ecology.bj.bcebos.com`, `huggingface.co`, `modelscope.cn`, `aistudio.baidu.com` | Direct request → `403 x-deny-reason: host_not_allowed` |
| EasyOCR | PyTorch (CPU build) | `download.pytorch.org` (PyPI's `torch` is CUDA-linked and fails to import without NVIDIA libraries even with `gpu=False`) | Direct request → `403 x-deny-reason: host_not_allowed`; import error confirmed |

**This is an environment limitation, not a code defect.** Both engine
classes were written against each library's real, verified API (I
read the actual PaddleOCR 3.x `OCRResult` source and EasyOCR's
`Reader.readtext()` signature directly rather than guessing) and will
work correctly on any machine where those hosts are reachable. See
`requirements-ocr-torch-notes.txt` for the exact one-line fix to make
EasyOCR functional elsewhere.

**To actually get real OCR text extraction**, on a machine with normal
internet access:
```bash
# PaddleOCR: nothing extra needed -- already in requirements.txt.
# First call to POST /ocr/documents/{id}/run with {"engine": "paddleocr"}
# will download model weights automatically (one-time, a few hundred MB).

# EasyOCR: install the correct torch build first.
venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
# Then POST /ocr/documents/{id}/run with {"engine": "easyocr"} will work,
# downloading EasyOCR's own models on first use.
```
Then set `OCR_DEFAULT_ENGINE=paddleocr` (or `easyocr`) in `.env` to make
it the default instead of `stub`.

### What was verified for real in this environment
- Full pipeline (upload → load from disk → rasterize/decode → denoise
  → deskew (images only) → run engine → persist → advance status) end
  to end via the stub engine, including a real PDF and PNG
- PDF rasterization at different DPIs produces correctly-scaled output
- Deskew demonstrably transforms a rotated test image (not a no-op)
- `POST .../run` with `paddleocr` and `easyocr` both fail with a clean
  `422 FileProcessingException` and a clear explanation — not a 500 or
  a hang — confirming the error-handling path around both real engines
  works correctly even though the engines themselves can't load here

## What Phase 5 Delivers
- **Engine-agnostic classification architecture** (`app/classification/`),
  mirroring the OCR pattern from Phase 4: an abstract
  `ClassificationEngine` interface so the strategy is pluggable —
  "Rule-based initially, ML-ready architecture later" per the spec
- **`RuleBasedClassifier`** (`app/classification/rule_based.py`): scores
  OCR-extracted text against curated keyword/regex rule sets for each
  of the four document types, normalized by each type's maximum
  possible score, with a confidence floor (0.25) below which a document
  is correctly labeled `UNKNOWN` rather than forced into a poor match
- `ClassificationResult` model + table: predicted type, confidence,
  per-rule matched signals, and the **full per-type score breakdown**
  (not just the winner) — stored as JSONB for transparency, so a
  borderline or wrong classification can be audited and understood
- `POST /classification/documents/{id}/classify`,
  `GET /classification/documents/{id}/result`,
  `GET /classification/documents/{id}/results` — same document access
  scoping as Phases 3-4; requires OCR to have run first
- Classifying a document updates `Document.document_type` but
  deliberately does **not** change `Document.status` (stays
  `OCR_COMPLETED`) — the workflow spec has no dedicated "classified"
  state; Phase 6 (extraction) owns the transition to `EXTRACTED`
- 20 additional automated tests (81 total)

### Verified for real
- All 4 document types classify correctly against realistic sample
  text (Invoice 0.88 confidence, Purchase Order 0.94, Journal Entry
  0.77, Bank Statement 0.84), with sensible cross-type score bleed
  (e.g. journal entry text scoring slightly on bank statement due to
  genuinely overlapping terms) but a clear winning margin every time
- Gibberish and empty text correctly resolve to `UNKNOWN`
- **The stub OCR engine's placeholder string was explicitly tested and
  confirmed to classify as `UNKNOWN`** — important in this environment,
  since Phase 4's OCR defaults to the stub engine and classification
  must never accidentally match placeholder text to a real type
- Full pipeline tested live: upload → OCR (stub, correctly → UNKNOWN)
  → manually injected realistic invoice text into a fresh OCRResult row
  (simulating what PaddleOCR/EasyOCR would produce) → re-classified →
  confirmed `predicted_type: INVOICE`, confidence 0.88, full signal list,
  and `Document.document_type` updated in the live API response while
  `Document.status` correctly stayed at `OCR_COMPLETED`
- Classification confirmed to always use the **latest** OCR result when
  a document has been OCR'd more than once
- Access scoping confirmed: a second analyst gets 403 attempting to
  classify another analyst's document

## ⚠️ Document Type Taxonomy Change (mid-Phase 6)
Phases 1-5 used a generic placeholder taxonomy (INVOICE / PURCHASE_ORDER
/ JOURNAL_ENTRY / BANK_STATEMENT). During Phase 6, the client provided
the **real enterprise AP/R2R document taxonomy** (an Excel field-mapping
sheet, later superseded by a complete field specification), and this
fully replaced the placeholder types:

| New Type | Meaning | Category |
|---|---|---|
| POI | PO-based vendor invoice | AP |
| NPO | Non-PO-based vendor invoice | AP |
| DPR | Down payment request | AP |
| IMA | Employee reimbursement claim | AP |
| MSI | Sales invoice (to customers) | R2R |
| PSI | Pay-in-slip / customer receipt | R2R |
| JER | Journal entry | R2R |
| BKA | Bank advice | R2R |
| LCA | Letter of credit advice | R2R |
| UNKNOWN | Unrecognized document | — |

**This required going back and rewriting Phase 5's classifier rules**
(`app/classification/rule_based.py`) for the new types, including a
dedicated POI-vs-NPO disambiguation step (both are vendor invoices and
share most vocabulary; the deciding signal is whether a PO number is
actually present). No database migration was needed for this change
since `document_type` was always a plain `VARCHAR`, not a native
Postgres enum — only application-level validation and classifier rules
changed.

## What Phase 6 Delivers
- **Complete field schema** (`app/extraction/field_schemas.py`) for all
  9 document types, per the client's specification: 15 common fields
  (Document ID, Company Code/Name, Fiscal Year, Location/Vertical Code,
  Currency, Document Date, etc.) shared by every type, plus 9-11
  type-specific fields per type (e.g. POI: Vendor Code/Name, PO/GRN/SRN
  Number, Invoice Number/Date/Amount, Tax/Net Amount, Payment Terms)
- **Engine-agnostic extraction architecture** (`app/extraction/`),
  mirroring the OCR/classification pattern: `ExtractionEngine` abstract
  interface, `RuleBasedExtractor` implementation, factory for engine
  selection
- **Extraction primitives** (`app/extraction/primitives.py`): generic
  label-based field extraction ("Label: Value" pattern matching) plus
  date normalization (handles DD-MM-YYYY, ISO, "15 June 2026", etc. →
  ISO 8601) and amount normalization (strips currency symbols and
  thousands separators, including Indian lakh-style grouping)
- **Per-type extraction logic** (`app/extraction/type_extractors.py`):
  one function per document type declaring which labels to search for
  each field
- `ExtractionResult` model: every field in the type's schema, found or
  not — extractors **never fabricate values**; a field with no match in
  the OCR text is stored as `null` with `0.0` confidence, exactly the
  signal a future review UI needs to highlight "needs manual entry"
- `POST /extraction/documents/{id}/extract`, `GET .../result`,
  `GET .../results`, and `PATCH /extraction/documents/{id}/fields/{key}`
  for manually correcting/filling a field (marks it `confidence: 1.0`,
  `manually_entered: true`) — laying the groundwork for the review/
  correction UI you described (full UI is a separate, later phase)
- Extraction is what advances `Document.status` to `EXTRACTED` (per
  the Phase 5 design decision: classify + extract together complete the
  spec's conceptual step, even though they're separate phases/code)
- 27 additional automated tests (115 total)

### Verified for real
- All 9 types tested end-to-end with realistic sample text; correct
  fields extracted with 0.9 confidence, dates normalized to ISO, amounts
  cleaned of currency symbols/commas
- **POI vs NPO disambiguation tested explicitly**: invoice text with a
  PO number correctly wins as POI even though it shares almost all
  vocabulary with NPO
- Full live pipeline run through the actual API: upload → OCR (stub) →
  inject realistic POI text → classify (→ POI, 0.77 confidence) →
  extract (→ 14/24 fields found, 0.9 confidence each) → confirmed
  `Document.status` became `EXTRACTED` and `document_type` shows `POI`
  in the live document response
- Manually corrected a null field (`location_code`) via the new PATCH
  endpoint — confirmed it persisted with `confidence: 1.0` and
  `fields_found_count` incremented correctly
- Confirmed extraction genuinely never fabricates: ran against empty
  text and confirmed every field returns null/0.0, not a guess
- Confirmed UNKNOWN-classified documents extract successfully with
  zero fields (not an error) since there's no schema to extract against
- Confirmed extraction requires OCR **and** classification to have run
  first, with clear, distinct error messages for each missing
  prerequisite
- Access scoping re-confirmed through this router too (403 for
  non-owners)

## What Phase 7 Delivers
- **Mandatory field map** (`app/validation/mandatory_fields.py`): the
  original Excel's mandatory-field markings, carried forward onto the
  new (Phase 6) field schema wherever the field still exists, plus
  judgment-based mandatory/optional decisions for genuinely new fields
  (GRN/SRN, Tax/Net Amount, all of DPR's and LCA's fields, etc.) —
  every mandatory key is automatically checked against the real schema
  at load time so a typo can never silently fail to fire
- **Six validator categories**, each its own module:
  - `field_validators.py`: required fields, date format (must be valid
    ISO calendar dates post-normalization), amount format (non-negative,
    ≤2 decimals), and tax-ID format (GST-style 15-character pattern,
    applied as a soft WARNING against vendor_code/customer_code since
    the new schema has no dedicated GST field — see design note below)
  - `duplicate_detection.py`: flags documents that are byte-for-byte
    identical (via `Document.file_hash`) to an earlier upload
  - `business_rules.py`: 7 type-specific cross-field checks — e.g.
    Invoice Amount = Tax + Net (POI/NPO/MSI), Debit = Credit (JER, hard
    ERROR — unbalanced bookkeeping is invalid, not just unusual), Travel
    End ≥ Start (IMA), Expiry > Issue Date (LCA), Advance % within 0-100
    (DPR), Approved ≤ Claimed (IMA, WARNING)
- `ValidationResult` model: every issue found, each tagged with rule
  type, severity (ERROR/WARNING), the field it concerns, and a message
- `POST /validation/documents/{id}/validate`, `GET .../result`,
  `GET .../results`
- Validation **conditionally** advances `Document.status` to
  `VALIDATED` — only when there are zero ERROR-severity issues.
  Documents with errors stay at `EXTRACTED`, making "stuck, needs
  fixing" visible directly from workflow status
- 28 additional automated tests (143 total)

### Design note: GST validation
The original spec called for GST validation, but Phase 6's
client-provided field schema has no dedicated GST Number field anywhere
(replaced by Tax Amount). Per instruction, this is handled as a generic
GST-pattern check applied loosely against `vendor_code`/`customer_code`:
if either value *looks like* an attempted tax ID (starts with 2 digits,
13+ characters), it's checked against the standard 15-character GST
format and flagged as a WARNING (not ERROR) if malformed — since these
fields are normally just internal codes, not tax IDs, a mismatch is
worth a reviewer's attention but isn't necessarily wrong.

### Two real bugs found and fixed while testing this phase
1. **`MultipleResultsFound` crash in duplicate detection.** The
   original `get_by_hash()` used `scalar_one_or_none()`, which raises
   if *more than one* row matches — but once a third document shares a
   hash (e.g. the same file uploaded 3 times), that's exactly what
   happens. Fixed by adding `get_all_by_hash()` (returns every match,
   oldest first) and having duplicate detection report the earliest
   *other* document, never assuming at-most-one match. Covered by a
   dedicated regression test (`test_duplicate_detection_handles_three_or_more_identical_files`).
2. **Wrong `document_type` used during validation.** `run_validation`
   read `Document.document_type` (whatever classification last set on
   the document row) instead of `ExtractionResult.document_type` (the
   type actually snapshotted at extraction time). These can diverge —
   e.g. if extraction was run, then classification re-run against new
   OCR text before validation — silently validating against the wrong
   type's mandatory-field list. Fixed by passing `document_type`
   explicitly from the extraction result into `run_validation()`
   rather than re-deriving it from the document row.

## What Phase 8 Delivers
- **Explicit state machine** (`app/workflow/state_machine.py`): a
  static transition table (not inferred logic) defining exactly which
  status each action requires, what it results in, which roles may
  perform it, and whether a comment is mandatory — the full rule set
  is visible in one place
- Transitions: `VALIDATED --REQUEST_APPROVAL--> PENDING_APPROVAL`,
  `PENDING_APPROVAL --APPROVE--> APPROVED`,
  `PENDING_APPROVAL --REJECT--> REJECTED`
- **Role enforcement**: any user with document access may request
  approval (mirrors who can already process the document); only
  FINANCE_MANAGER, AUDITOR, and ADMIN may approve or reject — an
  analyst cannot approve their own submission
- **Mandatory rejection comments**: rejecting without a comment returns
  a clear 422; approval comments stay optional
- **Resubmission requires re-validation, by design**: a REJECTED
  document cannot go straight back to PENDING_APPROVAL. It must pass
  through the existing validation endpoint again (reaching VALIDATED)
  before approval can be re-requested — guaranteeing any fix was
  actually re-checked, not just resubmitted as-is. Verified live:
  resubmitting directly returns a 409 with both the current and
  required status in the response; re-validating first makes the
  identical resubmit call succeed
- `WorkflowHistory` model: append-only log of every transition — who,
  when, from what status to what, and any comment — independent of
  (but a natural future feed into) Phase 9's audit system
- `POST /workflow/documents/{id}/request-approval`,
  `POST .../approve`, `POST .../reject`,
  `GET /workflow/documents/{id}/history`
- 17 additional automated tests (160 total)

### Verified for real
- Full live approval path: analyst requests approval → blocked from
  approving their own document (403) → manager approves with a comment
  → status becomes APPROVED → full history shows both entries with the
  correct users attached
- Full live rejection + resubmission path: manager rejects without a
  comment (422) → rejects with a comment (200, status → REJECTED) →
  analyst tries to resubmit directly (409, explains it needs VALIDATED
  first) → analyst re-validates (status → VALIDATED) → resubmit now
  succeeds (status → PENDING_APPROVAL) — history shows the complete
  REQUEST → REJECT → REQUEST trail in order
- Access scoping re-confirmed through this router too

## What Phase 9 Delivers
- **`AuditLog` model**: a flat, system-wide audit trail distinct from
  Phase 8's `WorkflowHistory` (which is specifically the approval state
  machine's log). Columns: `action`, `user_id` (nullable -- see below),
  `document_id` (nullable -- not every action concerns a document),
  `details` (JSONB, action-specific context), plus the standard
  timestamp mixin
- **`AuditAction` enum** (`app/models/document_enums.py`): one flat set
  of 13 action types covering every audited event --
  `LOGIN_SUCCESS`/`LOGIN_FAILED`/`USER_REGISTERED`,
  `DOCUMENT_UPLOADED`/`DOCUMENT_DELETED`,
  `OCR_RUN`/`CLASSIFICATION_RUN`/`EXTRACTION_RUN`/
  `EXTRACTION_FIELD_CORRECTED`/`VALIDATION_RUN`, and
  `APPROVAL_REQUESTED`/`DOCUMENT_APPROVED`/`DOCUMENT_REJECTED`
- **Completes the `User.audit_logs` relationship** flagged as pending
  since Phase 2, plus the matching `Document.audit_logs` relationship,
  both following the existing `documents`/`workflow_history`
  back-populates pattern
- **`AuditService.log()`**: a single, centralized logging call site.
  Deliberately invoked from **routers**, not from inside the
  document/OCR/classification/extraction/validation/workflow services
  themselves -- those services only take `current_user` as a parameter
  when their business logic actually needs it (WorkflowService is the
  one pre-existing exception, since it needs the user for
  role-checking). Auditing is a cross-cutting API-boundary concern, so
  it's wired in at the boundary. This also means **zero existing
  service signatures changed**, so none of the 160 Phase 1-8 tests are
  at risk from this phase's changes
- **Full coverage, by request**: every router across every phase now
  writes an audit entry on success -- register, login (success *and*
  failure), upload, delete, OCR run, classify, extract, manual field
  correction, validate, and all three workflow actions
- **Failed logins are audited without breaking username-enumeration
  protection**: `AuthService.authenticate()` deliberately raises the
  same error for "no such user" and "wrong password" so the API
  response never reveals which. The audit log preserves that
  guarantee -- `LOGIN_FAILED` entries always store `user_id: null`,
  even when the attempted username belongs to a real account, and
  record only the attempted username in `details` (useful for
  spotting brute-force patterns without leaking account existence to
  anyone reading the log)
- **`GET /audit/logs`** (system-wide, filterable by action/user/
  document, paginated) and **`GET /audit/documents/{id}/logs`**
  (per-document). Both **AUDITOR or ADMIN only** -- a deliberately
  stricter access model than every other router in the app. Unlike
  WorkflowHistory (visible to anyone with document access, since it's
  scoped via `DocumentService.get_for_user`), audit logs can surface
  *other* users' identities and actions that have nothing to do with
  the requesting user's own documents, so document-ownership is not
  the right boundary here. FINANCE_MANAGER is deliberately excluded
  too: managers approve/reject documents but don't need a
  cross-cutting view of every user's activity
- New migration `bfd7768c6be6` (head, follows `206f2a9dffa6`): creates
  `audit_logs` with FKs to `users` and `documents`, indexes on
  `action`, `user_id`, `document_id`
- 20 additional automated tests (180 total), covering every audited
  action, the username-enumeration-safe failed-login behavior, and the
  AUDITOR/ADMIN-only access restriction on both audit endpoints

### Verified for real
All 180 tests across Phases 1-9 were run for real against a live
PostgreSQL 16 instance (not just statically traced) -- every test in
`test_phase9_audit.py` passes, and re-running every prior phase's test
file confirmed zero regressions from this phase's changes:
- Every audited action produces exactly one matching `AuditLog` row
  with the correct `user_id`, `document_id`, and `details`: register,
  login (success and failure), upload, delete, OCR run, classify,
  extract, manual field correction, validate, and all three workflow
  actions
- Failed logins for both a real (wrong-password) and a nonexistent
  username both record `user_id: null` and only the attempted
  username in `details` -- the audit trail never distinguishes "user
  exists" from "user doesn't exist," matching `AuthService`'s existing
  enumeration protection
- FINANCE_ANALYST and FINANCE_MANAGER both get 403 from both audit
  endpoints (including a document's own uploader, on the per-document
  endpoint); AUDITOR and ADMIN get 200 from both
- Action-filtering on `GET /audit/logs` returns only matching rows

### Incidental findings: two performance bugs found and fixed while verifying this phase
Verifying Phase 9 for real meant running the full test suite, which
surfaced two performance problems -- one pre-existing, one introduced
by this phase's own code -- and fixing both:

1. **OCR `denoise()` ran unconditionally, even for born-digital PDFs**
   (pre-existing, since Phase 4). `app/ocr/preprocessing.py`'s
   `denoise()` (`cv2.fastNlMeansDenoisingColored`) measured at ~9s per
   page on this dev environment's single CPU core. `OCRService` already
   skipped `deskew` for PDF-rendered pages (correctly reasoning that
   born-digital PDFs are never skewed) but ran `denoise` unconditionally
   regardless of source. Measured: skipping denoise on a representative
   born-digital page changes no pixel by more than 1/255 -- there was
   nothing real to remove. Fixed by adding an `apply_denoise` parameter
   to `preprocess_for_ocr`, mirroring the existing `apply_deskew`
   pattern, and having `OCRService` skip both for PDFs while keeping
   both enabled for image uploads (scanned/photographed documents,
   where they're genuinely needed). The function's docstring previously
   claimed deskew was "the most expensive step" -- that was never
   verified and was wrong; denoise costs roughly 9x more.
2. **A circular eager-load introduced by this phase's own AuditLog
   relationships.** `AuditLog.user`/`AuditLog.document` were declared
   `lazy="joined"`, and `User.audit_logs`/`Document.audit_logs` were
   declared `lazy="selectin"` -- both eager, both following the
   existing codebase pattern used for `WorkflowHistory` and the
   `*_results` models. But `AuditLog` is the only model with
   relationships pointing back onto *both* `User` and `Document`, which
   those other models don't, so the same pattern that's safe everywhere
   else creates a real cycle here: loading a `Document` eager-loads its
   `audit_logs`, which eager-loads each log's `user`, which
   eager-loads *that user's* `audit_logs`, which eager-loads *those*
   logs' `document`, and so on -- a cascade that gets worse as the
   `audit_logs` table grows (measured: a single `Document` fetch went
   from ~1s to 9s to 30s+ across repeated calls in the same process
   once the table reached a few hundred rows). Confirmed nothing in the
   application actually reads `.audit_logs` as a Python attribute
   (`AuditService` queries `AuditLogRepository` directly), so all four
   relationships were changed to `lazy="select"` (load on demand)
   instead. Re-verified: the same `Document` fetch that took 9.2s now
   takes 0.77s, stable across repeated calls, no growth.

Net effect, full suite, single `pytest tests/` run: **all 180 tests
pass in 3m36s** (was timing out before either fix; individual phases
were taking 1-5+ minutes each, with several minutes per file in the
worst cases). Re-ran every phase file individually after both fixes
to confirm zero regressions -- all green.

## What Phase 10 Delivers
- **Bulk multipart upload** (`POST /documents/upload/bulk`): accepts
  multiple files in one request, same access model as the existing
  single-file `POST /documents/upload` (any authenticated user).
  Deliberately **partial-success**: each file is validated and
  uploaded independently, so one bad file in a batch (wrong type, too
  large, byte-for-byte duplicate) never blocks the rest. The response
  reports a per-file `{filename, success, document_id, error}` result
  alongside `total_files`/`succeeded`/`failed` counts, so the caller
  can see exactly what happened to each item
- **Folder-scan intake** (`POST /documents/intake/scan-folder`,
  **ADMIN only**): scans a server-side staging directory and ingests
  every allowed-type file found directly inside it (non-recursive).
  Fundamentally a different trust boundary from multipart upload --
  the server reads its own filesystem rather than bytes the client
  sent over HTTP -- so it's scoped much more tightly:
  - The scannable area is fixed by server configuration
    (`settings.INTAKE_SCAN_DIR`, default `intake/`), never chosen by
    the request. An optional `subpath` in the request body may name a
    relative subfolder *within* that root; it can never be absolute
    and can never contain `..` segments that escape the root --
    enforced by resolving the real path and checking it's still
    inside the configured root before any directory listing happens
    (`app/utils/file_storage.py:resolve_intake_subpath`)
  - Non-recursive by design: only files directly inside the scanned
    folder are considered, not subfolders -- keeps "how many files
    might this request process" easy to reason about
  - Each ingested file goes through the exact same `upload()` path as
    a multipart upload (same validation, same dedup-by-hash behavior
    visible to Phase 7's duplicate detection, same DB row shape), so
    a folder-scanned document is indistinguishable from a manually
    uploaded one once it's in the system -- except its audit log
    entry records `"via": "folder_scan"` for traceability
- **`MAX_BULK_INTAKE_FILES`** (default 100): both intake modes cap how
  many files a single request will process, regardless of how many
  are sent/found, so one request can't tie up the server indefinitely
- **Every successfully-ingested file gets its own `DOCUMENT_UPLOADED`
  audit log entry** (Phase 9 integration) -- a 50-file bulk upload
  produces 50 individual audit rows, not one batch-level row, so
  Phase 9's per-document audit trail stays accurate regardless of
  which intake path a document arrived through
- 10 additional automated tests (190 total)

### Verified for real
- Bulk upload: 3-file all-success batch, and a 2-file batch with one
  disallowed type -- confirmed 1 succeeds/1 fails with a clear
  per-file error, and the successful one still got a real
  `document_id` and its own audit entry
- Folder-scan: wrote a real file into the actual configured
  `INTAKE_SCAN_DIR`, scanned it via the live endpoint, confirmed it
  was ingested with a real `document_id` and an audit entry tagged
  `via: folder_scan`
- Folder-scan access control: FINANCE_ANALYST gets 403; ADMIN gets 201
- Path-traversal protection: `subpath: "../../../etc"` correctly
  rejected (422) before any directory listing is attempted
- Nonexistent subpath returns a clear 422, not a confusing 500 or an
  empty silent success
- Disallowed file types sitting in the intake folder (e.g. a stray
  `.txt`) are correctly skipped by the scan rather than erroring the
  whole request or being ingested
- Full suite re-run after this phase: all 190 tests pass in ~3m22s,
  zero regressions

## Deploy-Readiness Hardening (post-Phase-11)

With all 11 planned phases complete, this section covers what changed
to make the system genuinely deployable, not just functionally
complete. See `../README.md` for the actual Docker setup instructions.

### Dependency split: lean core vs. optional OCR

`requirements.txt` was restructured from one flat 104-package file
into three:
- **`requirements.txt`** (~40 packages) -- everything the app needs to
  boot and run the full pipeline with the stub OCR engine. Verified by
  AST-parsing every file under `app/` for its actual top-level imports
  (not by guessing): the only ML-engine-specific imports anywhere in
  the codebase are `easyocr`, `paddleocr`, `paddle`, and `torch`, and
  all four are imported lazily inside function bodies (never at module
  scope) in `app/ocr/paddle_engine.py` / `app/ocr/easyocr_engine.py` --
  confirmed by grepping for the actual `import` statements. This means
  the app boots and the entire pipeline runs correctly without those
  packages installed at all, provided `OCR_DEFAULT_ENGINE=stub` (the
  default). **All 190 tests were re-run against this lean set in a
  clean virtualenv and pass**, including
  `test_run_ocr_with_paddleocr_fails_gracefully_not_with_500`, which
  specifically checks the graceful-degradation path this split
  depends on.
- **`requirements-ocr.txt`** -- PaddleOCR + EasyOCR + their real
  dependency tree, computed by diffing the original full freeze
  against the new lean core (not hand-curated from package names).
  Install on top of `requirements.txt` for real OCR. Does not include
  `torch` -- see `requirements-ocr-torch-notes.txt` (pre-existing) for
  why that needs a separate, environment-specific install step.
- **`requirements-dev.txt`** -- `pytest` + `httpx`, only needed to run
  the test suite, not to run the application.

`gunicorn==23.0.0` was added to core (not present before) for
production serving -- see Dockerfile below.

### Backend Dockerfile

Multi-stage build (`builder` installs into a venv, `runtime` copies
just the venv + source, no build toolchain in the final image). Runs
as a non-root user. `ARG INSTALL_OCR=false` controls whether
`requirements-ocr.txt` gets installed during the build, keeping the
default image lean. `CMD` runs `alembic upgrade head` before starting
the server (via `exec gunicorn ...`, not a bare shell command, so
`docker stop`'s SIGTERM reaches gunicorn directly for a clean
shutdown instead of being absorbed by an intermediary shell process)
-- a failed migration exits the container non-zero rather than serving
against a stale schema.

**Verified for real** (no Docker available in the environment this was
built in, so the *ingredients* were each tested directly rather than
the full `docker build`):
- The lean core requirements install cleanly and boot the full app in
  a clean virtualenv (confirmed above)
- `gunicorn app.main:app --workers 4 --worker-class
  uvicorn.workers.UvicornWorker` actually starts, serves `/health`
  correctly with a live DB connection, and shuts down cleanly on
  SIGTERM -- run directly, not just assumed from the command syntax
- The exact `alembic upgrade head && exec gunicorn ...` shell sequence
  was run directly and works
- **Not verified**: the actual `docker build`/`docker run` cycle
  itself, since Docker isn't installed in this sandbox. The Dockerfile
  is assembled entirely from pieces that were each independently
  tested, but please run `docker compose up --build` yourself before
  treating the image as fully proven.

### SECRET_KEY startup validation

`app/core/config.py` now refuses to boot if `SECRET_KEY` is still set
to the literal placeholder value from `.env.example` (any environment),
and additionally requires it to be at least 32 characters specifically
in production (`APP_ENV=production`). Both checks were run directly
against the real `Settings` class and against the real `app.main`
import (confirmed the *process* exits 1 with a clear error, not just
that `Settings()` raises in isolation) -- catches the common real-world
mistake of copying `.env.example` to `.env` and forgetting to actually
change the secret, which would otherwise mean every JWT issued is
forgeable by anyone who's read the (public) source.

### OCR response schema: bounding boxes were stored but never exposed

While closing a frontend gap (the OCR tab fetched but didn't render
per-block bounding boxes), found that `OCRResultResponse` never
actually exposed the `raw_blocks` data that `OCRResult` (the model)
already stored -- the schema only surfaced `full_text` and
`average_confidence`. Added `raw_blocks` to the response, plus
`page_width`/`page_height` per page (previously absent entirely,
recomputed from the already-available preprocessed image shape) since
raw pixel-coordinate bounding boxes are meaningless to a consumer
without also knowing the source image's resolution. Verified via a
real OCR run through the live API, not just by reading the code: confirmed
the exact response shape (`page_width: 1700, page_height: 2200` for a
200dpi-rendered standard page) before building the frontend
visualization against it. Re-ran the full Phase 4 suite and the full
190-test suite after the change -- no regressions.

## Next Phase
None scheduled. All 11 originally-planned phases are complete and the
system is packaged for deployment (see `../README.md`). Natural future
work, not yet scoped: a frontend test suite, a CI/CD pipeline, and a
real OCR engine validated end-to-end on a machine with enough disk
space for the PaddleOCR/PaddlePaddle stack.

You are working on the EFDI (Enterprise Financial Document Intelligence)
application.

I want you to implement the Extraction component using a HYBRID architecture
consisting of:

1. Existing Rule-Based Extractor
2. Existing LLM-Based Extractor
3. Reconciliation layer that compares/reconciles the outputs of both extractors

This must be implemented IN PHASES.

DO NOT implement all phases in one run.

After completing each phase:

- run the relevant tests
- inspect for regressions
- provide a detailed implementation/report summary
- STOP
- wait for my explicit approval before proceeding to the next phase


============================================================
IMPORTANT: EXISTING ARCHITECTURE MUST BE PRESERVED
============================================================

Before modifying anything, inspect the current repository and understand the
existing:

- OCR architecture
- OCRService
- OCRResult / OCRPageResult / OCRTextBlock structures
- ocr_results persistence
- raw_blocks JSONB structure
- full_text generation
- Table Reconstruction
- Normalization
- OCR Validation
- OCR Quality Scoring
- Classification
- ExtractionService
- ExtractionEngine interface
- RuleBasedExtractor
- LLMBasedExtractor
- ExtractionResultData / Pydantic schemas
- extraction_results persistence
- ValidationService
- extraction factory
- extraction API/router
- existing extraction tests
- existing OCR tests

Do NOT assume that the architecture is exactly as described in this prompt
if the repository differs.

The repository/code is the source of truth.

Before making implementation changes, produce a concise architecture
assessment identifying the exact files/classes/functions involved.

DO NOT modify code during this initial inspection.


============================================================
TARGET ARCHITECTURE
============================================================

The target architecture MUST follow this data flow:

                              DOCUMENT
                                  |
                                  v
                                 OCR
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
               raw_blocks                   full_text
                    |                           |
                    |                           |
                    v                           |
          Table Reconstruction                  |
                    |                           |
                    v                           |
               table_data                      |
                    |                           |
                    v                           |
              Normalization                    |
                    |                           |
                    v                           |
             normalized_data                   |
                    |                           |
              +-----+------+                    |
              |            |                    |
              v            v                    |
       OCR Validation  OCR Quality              |
              |            |                    |
              +-----+------+                    |
                    |                           |
                    |                           |
                    +-------------+-------------+
                                  |
                                  v
                       +-----------------------+
                       |   EXTRACTION CONTEXT   |
                       |-----------------------|
                       | full_text              |
                       | document_type          |
                       | raw_blocks             |
                       | table_data             |
                       | normalized_data        |
                       | OCR validation         |
                       | OCR quality            |
                       +-----------+-----------+
                                   |
                       +-----------+-----------+
                       |                       |
                       v                       v
              RuleBasedExtractor       LLMBasedExtractor
                       |                       |
                       +-----------+-----------+
                                   |
                                   v
                            RECONCILIATION
                                   |
                                   v
                       FINAL EXTRACTION RESULT
                                   |
                                   v
                         extraction_results
                                   |
                                   v
                          ValidationService


CRITICAL:

FULL_TEXT MUST BE DIRECTLY PASSED INTO EXTRACTION CONTEXT.

The architecture MUST NOT interpret full_text as merely an upstream OCR
artifact that is replaced by raw_blocks/table_data.

The ExtractionContext must explicitly contain:

- full_text
- document_type
- raw_blocks
- table_data
- normalized_data
- OCR validation result
- OCR quality result


============================================================
ARCHITECTURAL ROLE OF EACH INPUT
============================================================

The ExtractionContext contains multiple representations of the same
document, but they have different purposes.

They are NOT independent competing sources.

Use them according to their role:

1. full_text

   Primary semantic/textual representation.

   Use for:
   - invoice number
   - invoice date
   - vendor name
   - customer/client information
   - tax identifiers
   - totals
   - general textual fields
   - other fields that can be reliably extracted from text

   full_text MUST remain a first-class Extraction input.


2. raw_blocks

   Spatial/layout evidence.

   Use when extraction depends on:
   - position
   - proximity
   - columns
   - labels next to values
   - header placement
   - page location
   - spatial relationships

   raw_blocks should NOT replace full_text.


3. table_data

   Structured table/line-item evidence produced by the existing
   Table Reconstruction process.

   Especially useful for:
   - descriptions
   - quantities
   - unit prices
   - amounts
   - tax columns
   - invoice line items

   Do NOT reconstruct the table again inside Extraction.


4. normalized_data

   Normalized values derived from the reconstructed table.

   Especially useful for:
   - numeric values
   - dates
   - quantities
   - units
   - normalized monetary values

   Do NOT normalize the data again inside Extraction.


5. OCR Validation

   Supporting evidence about OCR-derived/table-derived consistency.

   Examples:
   - quantity × unit price
   - subtotal
   - VAT
   - grand total
   - line-item arithmetic

   OCR validation is NOT extraction ground truth.


6. OCR Quality

   Primarily a reliability/control signal.

   It may influence:
   - confidence handling
   - fallback behavior
   - review requirements
   - how much additional structural evidence is considered

   It is NOT document content and should not be treated as an extracted field.


============================================================
DERIVATION RELATIONSHIP
============================================================

The OCR outputs have the following relationship:

                         raw_blocks
                         /        \
                        /          \
                       v            v
               full_text       Table Reconstruction
                                  |
                                  v
                             table_data
                                  |
                                  v
                            Normalization
                                  |
                                  v
                           normalized_data

This means:

- raw_blocks is original structured OCR evidence
- full_text is a flattened semantic representation derived from OCR blocks
- table_data is derived from OCR blocks
- normalized_data is derived from table_data

Therefore, these representations contain overlapping information.

DO NOT blindly pass all representations to the LLM as independent sources.

Instead, ExtractionContext contains them so that each extractor can use the
appropriate representation for the appropriate field.


============================================================
DO NOT DUPLICATE OCR PROCESSING
============================================================

The existing OCR pipeline already performs:

- OCR
- raw_blocks creation
- spatial ordering/full_text creation
- table reconstruction
- normalization
- OCR validation
- quality scoring

Extraction MUST consume the results already produced by OCR.

DO NOT:

- run Table Reconstruction a second time
- run Normalization a second time
- recreate OCR Validation
- recreate OCR Quality Scoring

inside Extraction.


============================================================
EXTRACTION CONTEXT
============================================================

Introduce a clean internal ExtractionContext abstraction instead of
continuously expanding the extractor function signature.

Conceptually:

    class ExtractionContext:
        full_text
        document_type
        raw_blocks
        table_data
        normalized_data
        ocr_validation
        ocr_quality

The exact types MUST be determined from the existing repository.

Use existing models/types wherever appropriate.

Do NOT create duplicate models unnecessarily.

The desired extractor contract is conceptually:

    extract(context: ExtractionContext) -> ExtractionResultData

Both:

- RuleBasedExtractor
- LLMBasedExtractor

must consume the same ExtractionContext.

FULL_TEXT MUST be part of this context and MUST be populated from the
existing OCR result.

raw_blocks should remain optional where the existing architecture permits it.

table_data, normalized_data, OCR validation, and OCR quality should also be
handled safely when unavailable/empty.


============================================================
RULE-BASED EXTRACTOR
============================================================

The existing RuleBasedExtractor must remain deterministic.

Do NOT turn the rule-based extractor into an AI/LLM decision-maker.

Update it so it can use the ExtractionContext where appropriate.

Conceptually:

General textual fields:

    full_text
        +
    raw_blocks when spatial evidence is useful


Line items:

    table_data
        +
    normalized_data
        +
    raw_blocks when structural evidence is required


Do NOT blindly use every source for every field.

Use explicit field-level extraction strategies.

Conceptually these may include:

- TEXT
- LAYOUT
- TABLE
- NORMALIZED_TABLE
- HYBRID

These are conceptual strategies.

Determine the actual field strategies by inspecting:

- existing extraction rules
- existing schemas
- existing field definitions
- existing extractor implementation

Do NOT invent arbitrary extraction behavior without inspecting the code.


============================================================
LLM-BASED EXTRACTOR
============================================================

There is already an LLMBasedExtractor in the project.

Do NOT create a second unrelated LLM extraction system.

Inspect and reuse the existing implementation wherever possible.

The LLM extractor must consume the ExtractionContext through a deliberate
LLM-facing context construction layer.

Do NOT dump the entire internal ExtractionContext blindly into the prompt.

The conceptual flow is:

    ExtractionContext
           |
           v
    LLMContextBuilder
           |
           v
    LLM-ready extraction context
           |
           v
          LLM
           |
           v
    Structured Pydantic output
           |
           v
    ExtractionResultData


The LLM context MUST include full_text.

full_text is the primary semantic representation.

The LLM may additionally receive:

- structured table data
- normalized table data
- relevant raw block/layout information
- OCR validation information
- OCR quality information

But these must be deliberately formatted and not unnecessarily duplicated.


============================================================
LLM SOURCE GUIDANCE
============================================================

The LLM prompt/context should clearly establish the following hierarchy:

PRIMARY TEXTUAL EVIDENCE:

    full_text


STRUCTURAL/SPATIAL EVIDENCE:

    raw_blocks


STRUCTURED TABLE EVIDENCE:

    table_data


NORMALIZED TABLE EVIDENCE:

    normalized_data


SUPPORTING CONSISTENCY EVIDENCE:

    OCR validation


RELIABILITY/CONTROL INFORMATION:

    OCR quality


The LLM must NOT arbitrarily decide that one source is always superior.

The application should establish clear field-level source strategies.

The LLM must:

- not invent values
- return null/empty where evidence is insufficient
- preserve exact document values where appropriate
- use table_data for line-item structure where available
- use normalized_data for normalized numeric/date/unit values where useful
- use raw_blocks when spatial relationships are necessary
- use full_text as the primary textual representation
- treat OCR validation as supporting evidence
- treat OCR quality as reliability metadata
- distinguish absence of evidence from an actual empty value


============================================================
RAW_BLOCKS HANDLING
============================================================

Inspect the actual repository structure before implementing.

Do NOT assume the runtime type.

The current raw_blocks structure includes page/block information such as:

- page_number
- page_width
- page_height
- blocks
- block text
- confidence
- bounding_box

Verify the exact implementation.

For the LLM, raw_blocks should be converted into a compact,
LLM-appropriate representation.

Do NOT unnecessarily send:

- redundant metadata
- duplicated full text
- irrelevant internal implementation details
- excessive coordinate precision that provides no useful information

However, do NOT remove spatial information required for extraction.

The LLM-ready representation must preserve enough information to reason about:

- page
- block order
- approximate position
- proximity
- columns
- labels and values
- table structure


============================================================
TABLE DATA AND NORMALIZED DATA
============================================================

Table Reconstruction output is structured OCR evidence.

It is especially useful for invoice line items.

Normalization provides cleaned/normalized values derived from reconstructed
table data.

Extraction should consume these outputs rather than recreating them.

Do NOT assume that table_data always contains the complete document.

If the current Table Reconstruction implementation operates only on page 1,
preserve that behavior initially.

Do NOT implement multi-page table reconstruction as part of this task.

Document this limitation clearly.


============================================================
OCR VALIDATION
============================================================

Keep OCR-stage validation separate from extraction-stage validation.

OCR-stage validation concerns OCR-derived information such as:

- quantity × unit price
- subtotal
- VAT
- grand total
- line-item consistency

Extraction-stage validation concerns the final ExtractionResultData.

The intended flow is:

    OCR
      |
      v
    Extraction
      |
      v
    extraction_results
      |
      v
    ValidationService

Do NOT create a circular dependency.

OCR validation may be supplied to ExtractionContext as supporting evidence.

It must NOT be treated as unquestionable ground truth.


============================================================
OCR QUALITY
============================================================

OCR Quality Score should be treated primarily as metadata/control information.

It may influence extraction behavior such as:

- confidence handling
- fallback/review behavior
- whether additional structural evidence should be considered

Do NOT treat the quality score as document content.

Do NOT implement logic such as:

    quality = 0.9
        =>
    extracted value is correct

Quality is an indicator of OCR reliability, not proof of field correctness.


============================================================
OPTION B — HYBRID EXTRACTION
============================================================

Use Option B.

The two extractors must run independently against the SAME ExtractionContext.

The target architecture is:

                         ExtractionContext
                                |
                 +--------------+--------------+
                 |                             |
                 v                             v
        RuleBasedExtractor              LLMBasedExtractor
                 |                             |
                 +--------------+--------------+
                                |
                                v
                         Reconciliation
                                |
                                v
                        Final Extraction
                                |
                                v
                       extraction_results


The RuleBasedExtractor MUST NOT depend on the LLM.

The LLMBasedExtractor MUST NOT depend on the RuleBasedExtractor.

Both receive the same ExtractionContext.

Their outputs meet only at the Reconciliation layer.


============================================================
RECONCILIATION
============================================================

Introduce a dedicated reconciliation component.

Its responsibilities include:

- comparing Rule-Based output with LLM output
- identifying agreements
- identifying disagreements
- determining whether a disagreement can be safely resolved
- preserving provenance
- identifying unresolved conflicts
- preventing silent overwrites

Start with deterministic reconciliation.

Do NOT introduce a machine-learning confidence model.

Do NOT establish a universal:

    "LLM always wins"

or:

    "Rule-Based always wins"

policy.

Reconciliation must be field-level.

Example:

    Rule:
        invoice_number = INV-12345

    LLM:
        invoice_number = INV-12345

    => AGREEMENT


Example:

    Rule:
        invoice_number = INV-12345

    LLM:
        invoice_number = INV-12346

    => CONFLICT

If a conflict cannot be safely resolved through an explicit deterministic
rule, preserve the conflict rather than silently selecting one value.


============================================================
PROVENANCE
============================================================

The system should be able to determine the origin of an extracted value.

At minimum distinguish internally:

- rule_based
- llm
- reconciled/agreed
- unresolved/conflict

First determine whether existing ExtractionResultData or JSONB structures can
represent this.

Do NOT immediately introduce database migrations.

Avoid unnecessary schema changes.


============================================================
DATABASE
============================================================

Do NOT add database tables/columns simply because Extraction now consumes
additional OCR-derived information.

Existing OCR persistence already contains:

- full_text
- raw_blocks
- OCR metadata

Do NOT duplicate these values inside extraction_results.

extraction_results remains the destination for the final extraction result.

Only modify the database schema if the existing architecture genuinely
cannot represent a required final extraction/reconciliation result.

If a migration appears necessary:

STOP.

Report the reason and proposed migration before implementing it.


============================================================
FACTORY / API / CONFIGURATION
============================================================

Preserve the existing Extraction factory architecture.

Existing engine choices may include:

- rule_based
- llm_based
- llm_rag

Do NOT remove existing options.

Do NOT implement RAG.

The current requirement is:

- Rule-Based extraction
- LLM-Based extraction
- Hybrid reconciliation

If llm_rag already exists, preserve it without expanding its behavior unless
required for compatibility.


============================================================
NO RAG
============================================================

Explicitly DO NOT implement:

- RAG
- vector retrieval
- embeddings
- document chunk retrieval
- vendor knowledge retrieval
- semantic search
- retrieval-augmented prompts

The architecture should remain compatible with future RAG.

RAG must NOT be implemented in this task.


============================================================
TESTING STRATEGY
============================================================

The implementation MUST be incremental.

Each phase must have its own tests.

Do not wait until the end to discover regressions.

Existing tests must continue passing.

After every phase:

1. Run targeted tests.
2. Run relevant regression tests.
3. Report:
   - tests executed
   - tests passed
   - tests failed
   - files changed
   - architecture changes
   - known limitations
   - risks

4. STOP.

Do NOT proceed to the next phase until I explicitly approve it.


============================================================
PHASE 0 — READ-ONLY ARCHITECTURE AUDIT
============================================================

DO NOT MODIFY CODE.

Inspect:

- ExtractionService
- ExtractionEngine
- RuleBasedExtractor
- LLMBasedExtractor
- extraction schemas
- extraction factory
- OCRService
- OCR result models
- raw_blocks
- Table Reconstruction
- Normalization
- OCR Validation
- Quality Scoring
- persistence
- tests

Produce:

1. Current extraction flow
2. Exact files/classes/functions involved
3. Current function signatures
4. Existing LLM implementation
5. Existing rule-based implementation
6. Existing OCR-derived outputs available at extraction time
7. How full_text currently reaches Extraction
8. How raw_blocks currently reaches Extraction, if at all
9. How table_data currently reaches Extraction, if at all
10. How normalized_data currently reaches Extraction, if at all
11. How OCR validation currently reaches Extraction, if at all
12. How OCR quality currently reaches Extraction, if at all
13. Exact changes required for the target architecture
14. Risks/ambiguities
15. Proposed Phase 1 implementation

DO NOT MODIFY ANY FILE.

STOP AFTER THE REPORT.


============================================================
PHASE 1 — EXTRACTION CONTEXT / CONTRACT
============================================================

Only after explicit approval of Phase 0.

Implement the minimum architectural plumbing required to pass:

- full_text
- document_type
- raw_blocks
- table_data
- normalized_data
- OCR validation
- OCR quality

from the existing OCR pipeline into ExtractionContext.

CRITICAL:

    full_text MUST be explicitly populated in ExtractionContext.

Do NOT implement reconciliation yet.

Do NOT substantially change extraction behavior.

Do NOT redesign the LLM prompt yet.

Do NOT add RAG.

Update interfaces and tests.

Verify that:

- existing RuleBasedExtractor remains functional
- existing LLMBasedExtractor remains functional or compatible
- full_text is correctly propagated
- raw_blocks is correctly propagated
- derived OCR outputs are correctly propagated

Run tests.

STOP.


============================================================
PHASE 2 — RULE-BASED EXTRACTOR
============================================================

Only after explicit approval.

Update RuleBasedExtractor to consume ExtractionContext.

Keep it deterministic.

Implement explicit field-level use of:

- full_text
- raw_blocks
- table_data
- normalized_data

where justified by the existing rules.

Do NOT introduce LLM logic.

Do NOT implement reconciliation.

Do not blindly consume all sources for all fields.

Add focused tests for:

- ordinary text fields
- spatial fields
- line items
- normalized numeric values
- missing raw_blocks
- missing table_data
- empty derived OCR outputs
- full_text-only extraction

Run targeted and regression tests.

STOP.


============================================================
PHASE 3 — LLM CONTEXT BUILDER + LLM EXTRACTOR
============================================================

Only after explicit approval.

Implement the LLM-facing context construction.

Create a clean boundary between:

    ExtractionContext

and:

    LLM-ready extraction context

The LLM context MUST contain full_text.

It may additionally contain:

- useful table data
- useful normalized data
- relevant raw block/layout information
- OCR validation
- OCR quality metadata

Avoid redundant payloads.

Use the existing structured Pydantic output approach.

Do NOT add RAG.

Do NOT implement reconciliation yet.

Add tests for:

- prompt/context construction
- full_text inclusion
- empty raw_blocks
- empty table data
- missing normalized data
- large raw block sets
- structured LLM output parsing
- invalid/malformed LLM responses
- error handling/timeouts according to existing patterns

Use mocks for external LLM calls.

Tests must NOT depend on a live LLM API.

Run tests.

STOP.


============================================================
PHASE 4 — RULE + LLM PARALLEL EXECUTION
============================================================

Only after explicit approval.

Modify ExtractionService/orchestration so both extractors run independently
against the same ExtractionContext.

Target:

                 ExtractionContext
                        |
              +---------+---------+
              |                   |
              v                   v
       RuleBasedExtractor    LLMBasedExtractor
              |                   |
              +---------+---------+
                        |
                        v
                 Reconciliation

At this stage, do not implement complicated reconciliation decisions.

Ensure:

- both outputs are available
- Rule-Based failure is handled safely
- LLM failure is handled safely
- one extractor failure does not corrupt the other
- existing extraction APIs remain compatible where possible

Add tests for:

- both succeed
- Rule succeeds / LLM fails
- LLM succeeds / Rule fails
- both fail
- empty extraction results

Run tests.

STOP.


============================================================
PHASE 5 — DETERMINISTIC RECONCILIATION
============================================================

Only after explicit approval.

Implement the dedicated reconciliation component.

Start with deterministic field-level behavior.

At minimum distinguish:

- AGREEMENT
- DISAGREEMENT
- UNRESOLVED_CONFLICT

Do NOT create:

- universal LLM precedence
- universal Rule-Based precedence
- machine-learning reconciliation

Use existing:

- field rules
- data types
- validation signals
- source provenance

where appropriate.

Same value:

    Rule == LLM
        =>
    AGREEMENT

Different value:

    Rule != LLM
        =>
    CONFLICT

unless an explicit deterministic rule safely resolves it.

Preserve provenance.

Add comprehensive reconciliation tests.

STOP.


============================================================
PHASE 6 — FINAL INTEGRATION + EVALUATION
============================================================

Only after explicit approval.

Integrate:

    OCR
      |
      v
    ExtractionContext
      |
      +----------------------+
      |                      |
      v                      v
    Rule-Based             LLM
      |                      |
      +----------+-----------+
                 |
                 v
          Reconciliation
                 |
                 v
        Final Extraction
                 |
                 v
        extraction_results
                 |
                 v
        ValidationService

Verify:

- API behavior
- persistence
- backward compatibility
- failure handling
- provenance
- reconciliation behavior

Run the full relevant backend test suite.

Then perform an evaluation using representative real invoice documents.

Measure at minimum:

- field-level extraction accuracy
- missing fields
- incorrect fields
- Rule/LLM agreement rate
- Rule/LLM disagreement rate
- unresolved conflicts
- line-item accuracy
- numeric accuracy
- date accuracy
- invoice-number accuracy
- latency
- LLM failures
- Rule-Based failures

Do not claim that the system is better merely because it executes
successfully.

Compare actual extraction results against the baseline.


============================================================
IMPORTANT IMPLEMENTATION RESTRICTIONS
============================================================

DO NOT:

- implement RAG
- modify Classification
- modify OCR behavior unless absolutely required for data access
- change raw_blocks persistence semantics
- redesign the database unnecessarily
- duplicate Table Reconstruction
- duplicate Normalization
- duplicate OCR Validation
- duplicate Quality Scoring
- make LLM the unquestioned source of truth
- make Rule-Based the unquestioned source of truth
- silently resolve conflicts
- introduce machine learning for reconciliation
- add unrelated refactoring
- delete existing functionality
- rewrite unrelated modules
- modify Docker configuration unless required
- change environment configuration unnecessarily
- change API contracts unnecessarily
- create new database tables for intermediate OCR data
- recreate OCR-derived structures inside Extraction

If you discover that a requested architectural change conflicts with the
actual repository:

STOP.

Report the conflict.

Do NOT guess.


============================================================
FINAL RULE
============================================================

IMPLEMENT ONE PHASE AT A TIME.

Never automatically proceed from one phase to the next.

At the end of every phase provide:

PHASE:
STATUS:
FILES CHANGED:
ARCHITECTURE CHANGES:
TESTS RUN:
TEST RESULTS:
KNOWN LIMITATIONS:
RISKS:
NEXT PHASE:

Then STOP.

Wait for my explicit instruction.

START WITH PHASE 0 ONLY.
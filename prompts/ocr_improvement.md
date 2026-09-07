Revise OCR Quality Improvement Implementation Plan — DO NOT IMPLEMENT YET

I reviewed the OCR Quality Improvement Implementation Plan you produced.

Do NOT start coding or modifying the project yet.

The current plan has the right general direction, but it needs to be revised before implementation. Update the implementation plan to address the following issues and requirements.

The goal is still:

Improve the quality, accuracy, structure, and reliability of OCR extraction while preserving the current EFDI architecture and maintaining backward compatibility.

1. PDF + IMAGE support is mandatory

The improvement must not become a PDF-only solution.

The current OCR architecture must be treated as supporting both:

PDF
IMAGE


Analyze both paths separately and identify:

Current PDF processing pipeline.

Current image processing pipeline.

What preprocessing is shared.

What preprocessing is format-specific.

How both paths eventually reach the common OCR engine.

Whether either path currently has quality problems that the other does not.

The revised architecture should look conceptually like:

                    INPUT
                      │
             ┌────────┴────────┐
             │                 │
            PDF              IMAGE
             │                 │
        PDF rendering      Image loading
             │                 │
             └────────┬────────┘
                      ↓
             Image Quality Analysis
                      ↓
            Adaptive Preprocessing
                      ↓
                    OCR
                      ↓
            Common OCR Processing


Do not design a PDF-only solution.

2. VERIFY THE ACTUAL CURRENT DPI BEFORE PROPOSING CHANGES

The previous plan made assumptions about PDF rendering DPI.

Do not assume the current DPI.

Inspect the actual source code and document:

Current DPI:
File:
Class/function:
Configuration source:
Runtime value:


If different code paths use different DPI values, document all of them.

Only after establishing the actual baseline should you recommend a DPI change.

3. Do NOT prematurely choose 400–450 DPI

The previous plan proposed increasing PDF rendering to approximately:

400–450 DPI


Do not treat this as the predetermined solution.

Instead, design a benchmark.

For example:

Current DPI
   ↓
300 DPI
   ↓
400 DPI


or another justified range.

Measure:

OCR accuracy
Critical field accuracy
Table accuracy
Processing time
Memory usage
Rendered image size


Select the final DPI based on evidence.

The final implementation should keep the value configurable.

4. Do NOT present GPU as an OCR accuracy improvement

Separate:

Accuracy improvements

preprocessing

rendering quality

OCR configuration

layout reconstruction

recognition strategy

validation

from:

Performance improvements

GPU

batching

parallelism

GPU may improve processing speed, but do not claim that enabling GPU inherently improves OCR accuracy.

If GPU support is recommended, classify it as a performance optimization, not a quality improvement.

5. Verify EasyOCR configuration against the ACTUAL installed version

Inspect:

Installed EasyOCR version.

Actual initialization code.

Actual readtext() usage.

Supported parameters.

Current language configuration.

Current detection settings.

Current recognition settings.

Current thresholds.

Current paragraph handling.

Current rotation handling.

Current magnification settings.

Do not recommend parameters unless they are actually supported by the installed EasyOCR version.

For every proposed parameter change, document:

Parameter:
Current value:
Supported by installed version:
Proposed value:
Expected effect:
Risk:
Benchmark required:


Do not invent EasyOCR parameters.

6. Bounding-box / spatial layout reconstruction MUST become a first-class component

This is a major requirement.

The current OCR output already contains information such as:

text
confidence
bounding box
page


The plan must explicitly investigate how that spatial information can be used to reconstruct document structure.

The target architecture should include something similar to:

EasyOCR
   ↓
OCR Blocks
   ↓
Bounding-box Analysis
   ↓
Reading Order
   ↓
Line Detection
   ↓
Row Detection
   ↓
Column Detection
   ↓
Table Detection
   ↓
Structured Representation


Do not rely primarily on regex over flattened OCR text.

Regex may be useful for field validation or normalization, but it should not be the primary mechanism for reconstructing arbitrary invoice layouts.

7. Design REAL table reconstruction

The plan must go beyond:

structured_blocks


and explicitly describe how invoice tables can be reconstructed.

For example:

Description | Qty | Unit | Net Price | Net Worth | VAT | Gross Worth


should be reconstructed from OCR blocks based on their spatial relationships.

Investigate:

X coordinates.

Y coordinates.

Bounding-box widths/heights.

Vertical overlap.

Horizontal overlap.

Row spacing.

Column alignment.

Header detection.

Repeated row patterns.

Page regions.

The plan should explain how this can work across different invoice layouts.

Do not assume all invoices use identical coordinates.

8. Ground-truth-based benchmarking is required

The previous plan discussed benchmarking but did not sufficiently define ground truth.

Determine whether the supplied invoice dataset contains enough information to establish expected values.

For critical fields, define ground truth such as:

Invoice number
Invoice date
Seller
Buyer
GSTIN
Currency
Quantity
Unit price
Net amount
VAT
Gross amount
Grand total


If reliable ground truth does not exist, explicitly state:

Ground truth unavailable.

Then propose a controlled method for manually creating a verified benchmark subset.

Do not claim objective OCR accuracy without ground truth.

9. Evaluate the ENTIRE 100-invoice dataset

Use the complete dataset:

C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI\Batch 1\invoices


Do not optimize specifically for:

invoice_51109301.pdf


That document should remain the baseline regression case, but the solution must generalize across the dataset.

The plan must identify:

Number of documents.

File types.

Page counts.

Layout variations.

Quality variations.

Native-text vs scanned documents where detectable.

Any unusual cases.

The plan should define how current vs improved OCR will be compared across the dataset.

10. Use invoice_51109301.pdf as a regression baseline

Continue using:

C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI\invoice_51109301.pdf


as the baseline.

Document the known OCR issues, including examples such as:

pCs
3_
flattened table structure


But determine the actual root cause rather than assuming the OCR engine itself is responsible.

Classify each issue as potentially caused by:

PDF rendering
image quality
preprocessing
OCR recognition
bounding-box interpretation
reading order
layout reconstruction
normalization


11. Adaptive preprocessing — NOT blanket preprocessing

The proposed preprocessing architecture must be adaptive.

Do NOT simply apply:

denoise
+
sharpen
+
threshold
+
deskew


to every image.

Instead design:

Input
 ↓
Image Quality Analyzer
 ↓
Determine characteristics
 ↓
Select preprocessing strategy
 ↓
OCR


Potential cases:

Clean image
→ minimal preprocessing

Low contrast
→ contrast enhancement

Skewed
→ deskew

Noisy
→ denoise

Low resolution
→ upscale

Poor scan
→ appropriate combination


Explain how the system would determine which operations to apply.

12. Do NOT introduce pdf2image unless benchmarking proves it is necessary

The current architecture already has PDF processing.

Do not introduce:

pdf2image


merely because it is another PDF rendering option.

First determine whether the current PDF renderer is adequate.

Only propose pdf2image if there is measurable evidence that it provides a meaningful quality improvement over the existing renderer.

If proposed, document:

Why existing renderer is insufficient
Expected improvement
Performance impact
Dependency impact
Maintenance impact
Migration/rollback implications


Otherwise explicitly recommend retaining the current renderer.

13. Improve the architecture around OCR, not just the OCR engine

The revised plan should distinguish:

OCR recognition


from:

Document understanding


The target pipeline should conceptually be:

PDF / IMAGE
     ↓
Input analysis
     ↓
Adaptive preprocessing
     ↓
OCR engine
     ↓
Raw OCR blocks
     ↓
Layout reconstruction
     ↓
Structured invoice extraction
     ↓
Normalization
     ↓
Validation
     ↓
Quality scoring
     ↓
Persistence
     ↓
Audit


The goal is not simply:

"Make EasyOCR recognize more characters."

The goal is:

Produce accurate, structured, validated invoice information while retaining the raw OCR evidence.

14. Preserve RAW OCR output

Do not replace raw OCR with processed text.

Maintain:

RAW OCR
   ↓
NORMALIZED OCR
   ↓
STRUCTURED DATA


The raw layer must remain available for:

auditing

debugging

comparison

reprocessing

quality evaluation

Preserve:

raw text
raw blocks
bounding boxes
confidence
page information
engine
processing metadata


15. Database compatibility

Review the current:

OCRResult
OCRResultRepository
ocr_results
full_text
raw_blocks
confidence
processing_time


Determine exactly what the improved pipeline would need to persist.

If proposing new fields, specify:

Field
Data type
Purpose
Why persistence is necessary
Backward compatibility
Migration impact


Do not create the migration yet.

Do not introduce database changes merely because they are convenient.

16. API compatibility

Review the current OCR API and ensure the existing response remains compatible.

If proposing fields such as:

quality_score
quality_status
structured_invoice
critical_field_confidence
preprocessing_strategy


specify:

Field
Type
Purpose
Required/optional
Backward compatibility


Existing consumers of:

full_text
page_count
engine_name
confidence


must continue to work.

17. Preserve OCR auditing

The OCR audit feature has already been implemented.

The revised plan must preserve:

OCR_STARTED
OCR_COMPLETED
OCR_FAILED


Do not remove or bypass the existing audit service.

Consider whether useful additional metadata should be captured, such as:

OCR engine
preprocessing strategy
DPI
quality score
reprocessing attempt
final quality status


If additional audit changes are proposed, clearly explain why.

Do not implement them yet.

18. Unsupported file handling

The revised plan must explicitly address files that are not currently supported by OCR.

The architecture should be:

Uploaded File
      ↓
File Type Detection
      ↓
 ┌────────┬────────┬─────────────┐
 PDF    IMAGE   Unsupported
  │        │          │
  ↓        ↓          ↓
PDF OCR Image OCR   Reject
  │        │
  └────┬───┘
       ↓
Common OCR Pipeline


Do not send unsupported formats through OCR.

Future formats such as:

DOCX
XLSX
TXT


may eventually receive their own extraction processors, but do not implement them as part of this OCR improvement.

19. Image OCR must be explicitly covered

The revised plan must contain a dedicated section for image OCR.

Investigate:

resolution

orientation

skew

noise

blur

contrast

compression

color mode

resizing

preprocessing

The solution must improve image OCR without unnecessarily duplicating the PDF pipeline.

20. Quality evaluation must be measurable

Define objective metrics.

At minimum:

Invoice number accuracy
Date accuracy
Seller accuracy
Buyer accuracy
GSTIN accuracy
Quantity accuracy
Unit price accuracy
Net amount accuracy
VAT accuracy
Gross amount accuracy
Grand total accuracy
Line-item accuracy
Table reconstruction accuracy
Character/word accuracy where feasible
Confidence
Processing time


Compare:

CURRENT PIPELINE
vs
IMPROVED PIPELINE


Do not rely solely on subjective inspection.

21. Quality scoring should be separated from OCR confidence

Do not equate:

EasyOCR confidence


with:

Document quality


The revised plan should distinguish:

OCR recognition confidence


from:

overall extraction quality


A future quality score may combine:

OCR confidence
critical field confidence
table confidence
format validation
financial validation


Design this carefully before implementation.

22. Validation must not silently alter OCR

If the system detects:

Quantity × Unit Price != Net Amount


or:

Subtotal + VAT != Grand Total


the system should flag the discrepancy.

It must not silently modify OCR output to make the numbers balance.

Preserve:

raw value
normalized value
validation result


where applicable.

23. Reprocessing strategy

Design a future quality gate:

OCR
 ↓
Quality Evaluation
 ↓
 ┌─────────────┐
 │             │
GOOD       LOW QUALITY
 │             │
 ↓             ↓
STORE       REPROCESS


Possible reprocessing approaches:

different preprocessing
different DPI
different EasyOCR configuration
alternative OCR engine


Do not implement automatic engine switching yet unless justified.

First establish whether reprocessing provides measurable improvement.

24. Testing requirements

The revised plan must include:

Unit tests

For:

PDF rendering
image processing
preprocessing
deskew
quality analysis
layout reconstruction
table reconstruction
normalization
validation
quality scoring


Integration tests

For:

PDF upload → OCR → DB
IMAGE upload → OCR → DB


Regression tests

Using:

invoice_51109301.pdf


Dataset benchmark

Using the entire:

Batch 1\invoices


dataset.

25. Explicitly separate QUALITY from PERFORMANCE

The revised plan should have two separate categories.

Quality

Recognition accuracy
Layout accuracy
Table reconstruction
Field extraction
Normalization
Validation


Performance

Processing time
Memory
GPU
Batching
Concurrency


Do not mix the two.

26. Preserve current architecture

The revised solution should extend, not replace, the existing architecture.

Preserve wherever practical:

OCR Router
OCR Service
OCR Factory
OCREngine abstraction
EasyOCREngine
OCRResult
OCR Repository
Audit Service
PostgreSQL persistence
Existing API
Frontend integration


If a new component is proposed, explain why it belongs in the architecture.

Potential components may include:

ImageQualityAnalyzer
AdaptivePreprocessor
LayoutAnalyzer
TableExtractor
InvoiceExtractor
TextNormalizer
QualityEvaluator
InvoiceValidator


But do not add components merely for the sake of abstraction.

27. Required revised implementation plan

Update the existing:

OCR_QUALITY_IMPROVEMENT_IMPLEMENTATION_PLAN.md


Do not create an implementation or modify application code.

The revised plan must include at minimum:

1. Executive Summary

2. Current Architecture

3. Current PDF Pipeline

4. Current Image Pipeline

5. Test Dataset Inventory

6. Test Dataset Matrix

7. Current EasyOCR Configuration

8. Verified Runtime Configuration

9. Current OCR Output Structure

10. Baseline OCR Results

11. Root Cause Analysis

12. Proposed Target Architecture

13. Adaptive Preprocessing

14. PDF Rendering Strategy

15. Image Processing Strategy

16. EasyOCR Configuration Strategy

17. Bounding-box/Layout Reconstruction

18. Table Reconstruction

19. Invoice Field Extraction

20. Normalization

21. Context-aware Error Correction

22. Quality Evaluation

23. Validation

24. Reprocessing

25. Alternative OCR Engine Strategy

26. Unsupported File Handling

27. Database Impact

28. API Impact

29. Frontend Impact

30. Audit Impact

31. Testing Strategy

32. Ground Truth Strategy

33. Benchmarking Strategy

34. Current vs Proposed Architecture

35. Implementation Phases

36. Priority Ranking

37. Risks

38. Backward Compatibility

39. Acceptance Criteria

40. Rollback Strategy


28. Priority ranking

Clearly rank the proposed changes.

For each recommendation provide:

Priority:
Expected quality improvement:
Implementation complexity:
Performance impact:
Risk:
Architectural impact:
Reason:


I specifically want to know which smallest set of changes should be implemented first to achieve the biggest measurable improvement.

29. Acceptance criteria

The revised plan must contain measurable acceptance criteria.

For example:

Improved OCR must outperform the current baseline on the benchmark dataset.

Critical invoice fields must show measurable accuracy improvement.

Table reconstruction must improve over current flat-text extraction.

PDF OCR must not regress.

Image OCR must not regress.

Raw OCR evidence must remain available.

Database persistence must continue working.

Existing OCR API consumers must continue working.

OCR audit events must continue working.

Unsupported file types must be rejected safely.

Processing time must remain within an agreed threshold.


Use actual baseline measurements where possible.

30. FINAL STOP CONDITION

After revising:

OCR_QUALITY_IMPROVEMENT_IMPLEMENTATION_PLAN.md


STOP.

Do not:

write application code

modify Python files

modify database models

create migrations

modify .env

install packages

change EasyOCR configuration

modify frontend code

modify audit code

modify test documents

commit changes

Instead, report:

What was changed in the implementation plan.

The actual OCR architecture verified.

The actual PDF pipeline verified.

The actual image pipeline verified.

The test dataset characteristics.

The most important OCR problems discovered.

Their likely root causes.

The highest-priority proposed improvements.

Any remaining uncertainties.

The recommended first implementation phase.

Then WAIT FOR MY EXPLICIT APPROVAL.

Do not proceed to implementation until I explicitly say:

Approved — proceed with implementation.

The workflow must remain:

INSPECT
   ↓
VERIFY
   ↓
BENCHMARK
   ↓
IDENTIFY ROOT CAUSES
   ↓
REVISE PLAN
   ↓
STOP
   ↓
WAIT FOR APPROVAL
   ↓
IMPLEMENT ONLY AFTER APPROVAL

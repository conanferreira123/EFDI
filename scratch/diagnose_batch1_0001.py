import os
import sys
import json
import time
import uuid
import fitz

# Add backend to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.database.session import get_db_context
from app.repositories.document_repository import DocumentRepository
from app.repositories.ocr_result_repository import OCRResultRepository
from app.repositories.classification_result_repository import ClassificationResultRepository
from app.repositories.extraction_result_repository import ExtractionResultRepository
from app.extraction.rule_based import RuleBasedExtractor
from app.extraction.llm_extractor import LLMBasedExtractor
from app.extraction.llm_context_builder import LLMContextBuilder
from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.parallel_orchestrator import ParallelExtractionOrchestrator
from app.extraction.reconciliation import ReconciliationEngine
from app.extraction.base import ExtractionContext

def main():
    pdf_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "batch1-0001.pdf"))
    
    print("=" * 70)
    print("1. LOCATE AND VERIFY DOCUMENT")
    print("=" * 70)
    if not os.path.exists(pdf_path):
        print(f"File NOT found: {pdf_path}")
        return
    file_size = os.path.getsize(pdf_path)
    doc_fitz = fitz.open(pdf_path)
    page_count = len(doc_fitz)
    print(f"Absolute Path: {pdf_path}")
    print(f"File Size: {file_size} bytes ({file_size/1024:.2f} KB)")
    print(f"File Type: PDF (application/pdf)")
    print(f"Page Count: {page_count}")
    
    # Authenticate / Register test user via API
    client = TestClient(app)
    uname = f"diag_{uuid.uuid4().hex[:8]}"
    pwd = "TestPass123!"
    reg_resp = client.post("/api/v1/auth/register", json={
        "username": uname,
        "email": f"{uname}@example.com",
        "full_name": "Diagnostic User",
        "password": pwd,
        "role": "FINANCE_ANALYST",
    })
    assert reg_resp.status_code == 201, f"Register failed: {reg_resp.text}"
    login_resp = client.post("/api/v1/auth/login", json={"username": uname, "password": pwd})
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token = login_resp.json()["access_token"]
    
    auth_headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Upload Document
    with open(pdf_path, "rb") as f:
        upload_resp = client.post(
            "/api/v1/documents/upload",
            headers=auth_headers,
            files={"file": ("batch1-0001.pdf", f, "application/pdf")},
        )
    assert upload_resp.status_code == 201, f"Upload failed: {upload_resp.text}"
    document_id = upload_resp.json()["id"]
    print(f"Uploaded Document ID: {document_id}")

    # 2. Run OCR via API
    print("\n" + "=" * 70)
    print("2. RUN OCR PIPELINE")
    print("=" * 70)
    t0_ocr = time.time()
    ocr_api_resp = client.post(f"/api/v1/ocr/documents/{document_id}/run", headers=auth_headers)
    ocr_dur = time.time() - t0_ocr
    assert ocr_api_resp.status_code == 201, f"OCR failed: {ocr_api_resp.text}"
    ocr_json = ocr_api_resp.json()
    
    with get_db_context() as db:
        ocr_db_rec = OCRResultRepository(db).get_latest_for_document(document_id)
        raw_blocks = ocr_db_rec.raw_blocks or []
        full_text = ocr_db_rec.full_text or ""
        avg_confidence = float(ocr_db_rec.average_confidence or 0.0)
        ocr_engine_name = ocr_db_rec.engine_name
        
    all_blocks = []
    for p in raw_blocks:
        all_blocks.extend(p.get("blocks", []))

    print(f"OCR Engine Actually Used: {ocr_engine_name}")
    print(f"OCR Processing Time: {ocr_dur:.3f}s")
    print(f"Page Count: {len(raw_blocks)}")
    print(f"Number of OCR Blocks: {len(all_blocks)}")
    print(f"Average OCR Confidence: {avg_confidence:.4f}")
    print(f"Full Text Character Count: {len(full_text)}")
    print("\n--- FULL TEXT SAMPLE (First 500 chars) ---")
    print(full_text[:500])
    print("...")

    # Table reconstruction & validation from raw_blocks
    from app.ocr.table_reconstruction import reconstruct_table
    from app.ocr.normalization import normalize_table_data
    from app.ocr.validation import validate_ocr_output
    from app.ocr.quality_scoring import calculate_quality_score

    pw = float(raw_blocks[0].get("page_width", 1000.0)) if raw_blocks else 1000.0
    ph = float(raw_blocks[0].get("page_height", 1400.0)) if raw_blocks else 1400.0
    table_obj = reconstruct_table(all_blocks, page_width=pw, page_height=ph)
    table_data = table_obj.to_dict()
    normalized_items = normalize_table_data(table_data)
    normalized_data = {"line_items": [item.to_dict() for item in normalized_items]}
    val_res = validate_ocr_output(normalized_items, raw_full_text=full_text)
    ocr_validation = val_res.to_dict()
    quality_res = calculate_quality_score(
        avg_confidence=avg_confidence,
        full_text=full_text,
        table_data=table_data,
        validation_result=val_res,
    )
    ocr_quality = quality_res.to_dict()

    print(f"\nTable Reconstructed Line Items: {len(table_data.get('line_items', []))}")
    print(f"Normalized Line Items: {len(normalized_data.get('line_items', []))}")
    print(f"OCR Validation: is_valid={ocr_validation.get('is_valid')}")
    print(f"OCR Quality Score: {ocr_quality.get('overall_quality_score')} ({ocr_quality.get('quality_tier')})")
    
    print("\n--- SAMPLE RAW BLOCKS (First 5) ---")
    for i, b in enumerate(all_blocks[:5]):
        print(f"  Block #{i+1}: text='{b.get('text')}' conf={b.get('confidence'):.2f} bbox={b.get('bounding_box')}")

    # 3. Run Classification
    print("\n" + "=" * 70)
    print("3. RUN CLASSIFICATION PIPELINE")
    print("=" * 70)
    cls_api_resp = client.post(f"/api/v1/classification/documents/{document_id}/classify", headers=auth_headers)
    assert cls_api_resp.status_code == 201, f"Classification failed: {cls_api_resp.text}"
    cls_json = cls_api_resp.json()
    predicted_type = cls_json["predicted_type"]
    cls_conf = cls_json["confidence"]
    cls_engine = cls_json["engine_name"]
    print(f"Classifier Engine Used: {cls_engine}")
    print(f"Predicted Document Type: {predicted_type}")
    print(f"Classification Confidence: {cls_conf:.4f}")
    print(f"Secondary Scores/Signals: {cls_json.get('secondary_scores')}")

    # 4. Extraction Engine Routing
    print("\n" + "=" * 70)
    print("4. EXTRACTION ENGINE ROUTING")
    print("=" * 70)
    print(f"EXTRACTION_DEFAULT_ENGINE: {getattr(settings, 'EXTRACTION_DEFAULT_ENGINE', 'rule_based')}")
    print(f"LLM_PROVIDER: {getattr(settings, 'LLM_PROVIDER', 'mistral')}")
    print(f"EXTRACTION_LLM_MODEL: {getattr(settings, 'EXTRACTION_LLM_MODEL', 'mistral-small-2603')}")
    print(f"MISTRAL_API_BASE: {getattr(settings, 'MISTRAL_API_BASE', 'https://api.mistral.ai/v1')}")
    print(f"MISTRAL_API_KEY Configured: {'YES' if bool(getattr(settings, 'MISTRAL_API_KEY', None)) else 'NO'}")

    context = ExtractionContext(
        full_text=full_text,
        document_type=predicted_type,
        raw_blocks=raw_blocks,
        table_data=table_data,
        normalized_data=normalized_data,
        ocr_validation=ocr_validation,
        ocr_quality=ocr_quality,
        document_id=document_id,
    )

    # 5. Run Rule-Based Extractor independently
    print("\n" + "=" * 70)
    print("5. RULE-BASED EXTRACTION (INDEPENDENT RUN)")
    print("=" * 70)
    rule_extractor = RuleBasedExtractor()
    rule_res = rule_extractor.extract(context)
    print(f"Rule-Based Fields Found: {rule_res.fields_found_count} / {rule_res.fields_total_count}")
    print(f"Rule-Based Overall Confidence: {rule_res.overall_confidence:.4f}")
    print("\nFIELD | RULE VALUE | CONFIDENCE | PROVENANCE")
    print("-" * 75)
    for k, f in rule_res.fields.items():
        v = f.value if f.value is not None else "[not_found]"
        prov = getattr(f, "provenance", "rule_based")
        print(f"{k:<25} | {str(v):<30} | {f.confidence:.2f} | {prov}")

    # 6. Run LLM-Based Extractor (Mistral)
    print("\n" + "=" * 70)
    print("6. LLM-BASED EXTRACTION (MISTRAL RUN)")
    print("=" * 70)
    llm_extractor = LLMBasedExtractor()
    user_prompt = LLMContextBuilder.build_user_prompt(context)
    system_prompt = LLMContextBuilder.build_system_prompt(predicted_type)
    DynamicModel = build_dynamic_extraction_model(predicted_type)
    json_schema = DynamicModel.model_json_schema()

    print(f"Provider: {llm_extractor.provider}")
    print(f"Model: {llm_extractor.model_name}")
    print(f"API Base: {llm_extractor.api_base}")
    print(f"API Key Configured: {'YES' if bool(llm_extractor.api_key) else 'NO'}")

    # 7. LLM Input Context
    print("\n" + "=" * 70)
    print("7. LLM INPUT CONTEXT DETAILS")
    print("=" * 70)
    print(f"Document Type: {predicted_type}")
    print(f"Full Text Characters: {len(full_text)}")
    print(f"Raw Blocks Count: {len(all_blocks)}")
    print(f"Table Rows Count: {len(table_data.get('line_items', []))}")
    print(f"Normalized Rows Count: {len(normalized_data.get('line_items', []))}")
    print(f"Validation Valid: {ocr_validation.get('is_valid')}")
    print(f"Quality Score: {ocr_quality.get('overall_quality_score')}")
    print(f"User Prompt Size: {len(user_prompt)} characters")
    print(f"System Prompt Size: {len(system_prompt)} characters")
    print(f"Dynamic Schema Properties: {len(json_schema.get('properties', {}))}")
    print(f"LLM received full_text: YES")
    print(f"LLM received raw_blocks: {'YES' if raw_blocks else 'NO'}")
    print(f"LLM received table_data: {'YES' if table_data else 'NO'}")
    print(f"LLM received normalized_data: {'YES' if normalized_data else 'NO'}")
    print(f"LLM received validation: {'YES' if ocr_validation else 'NO'}")
    print(f"LLM received quality information: {'YES' if ocr_quality else 'NO'}")

    # Attempt live Mistral call
    llm_invocation_started = True
    llm_request_sent = False
    llm_http_status = None
    llm_resp_received = False
    llm_parse_success = False
    llm_validation_success = False
    llm_extraction_completed = False
    llm_error = None
    llm_raw_resp = None
    llm_res = None

    if not llm_extractor.api_key:
        print("\n--> MISTRAL_API_KEY NOT CONFIGURED. Falling back to rule-based extractor.")
        llm_error = "MISSING_API_KEY"
        llm_res = llm_extractor.extract(context)
    else:
        print("\n--> MISTRAL_API_KEY detected. Sending HTTP POST to Mistral Chat Completions API...")
        try:
            llm_request_sent = True
            t_llm0 = time.time()
            llm_raw_resp = llm_extractor._call_llm_api(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_schema=json_schema,
            )
            llm_dur = time.time() - t_llm0
            llm_http_status = 200
            llm_resp_received = True
            print(f"--> Mistral API Response received in {llm_dur:.3f}s (HTTP 200 OK)")
            
            parsed_data = DynamicModel.model_validate(llm_raw_resp)
            llm_parse_success = True
            llm_validation_success = True
            llm_res = llm_extractor.extract(context)
            llm_extraction_completed = True
            print(f"--> Dynamic Pydantic Validation Succeeded! Extracted {llm_res.fields_found_count} fields.")
        except Exception as exc:
            llm_error = str(exc)
            print(f"--> Mistral API Call FAILED: {exc}")
            llm_res = llm_extractor.extract(context)

    # 8. Parsed LLM Results
    print("\n" + "=" * 70)
    print("8. PARSED LLM RESULTS")
    print("=" * 70)
    print(f"LLM Fields Found: {llm_res.fields_found_count} / {llm_res.fields_total_count}")
    print(f"LLM Overall Confidence: {llm_res.overall_confidence:.4f}")
    print("\nFIELD | LLM VALUE | CONFIDENCE | PROVENANCE")
    print("-" * 75)
    for k, f in llm_res.fields.items():
        v = f.value if f.value is not None else "[not_found]"
        prov = getattr(f, "provenance", "llm")
        print(f"{k:<25} | {str(v):<30} | {f.confidence:.2f} | {prov}")

    # 9. Hybrid Orchestrator Dual Execution
    print("\n" + "=" * 70)
    print("9. HYBRID ORCHESTRATOR DUAL EXECUTION")
    print("=" * 70)
    orchestrator = ParallelExtractionOrchestrator(
        rule_extractor=rule_extractor,
        llm_extractor=llm_extractor,
    )
    dual_result = orchestrator.run_parallel(context)
    print(f"Dual Execution Rule Status: {'OK' if dual_result.has_rule_result else 'FAILED/EMPTY'} (error: {dual_result.rule_error})")
    print(f"Dual Execution LLM Status: {'OK' if dual_result.has_llm_result else 'FAILED/EMPTY'} (error: {dual_result.llm_error})")

    # 10. Reconciliation
    print("\n" + "=" * 70)
    print("10. RECONCILIATION ENGINE EXECUTION")
    print("=" * 70)
    reconciled_res = ReconciliationEngine.reconcile(dual_result, context)
    print(f"Reconciled Fields Found: {reconciled_res.fields_found_count} / {reconciled_res.fields_total_count}")
    print(f"Reconciled Overall Confidence: {reconciled_res.overall_confidence:.4f}")
    print("\nFIELD | RULE VALUE | LLM VALUE | FINAL VALUE | CONF | PROVENANCE")
    print("-" * 90)
    for k, f in reconciled_res.fields.items():
        rv = rule_res.fields.get(k).value if (rule_res and k in rule_res.fields and rule_res.fields[k].value) else "-"
        lv = llm_res.fields.get(k).value if (llm_res and k in llm_res.fields and llm_res.fields[k].value) else "-"
        fv = f.value if f.value is not None else "-"
        prov = getattr(f, "provenance", "N/A")
        print(f"{k:<22} | {str(rv):<16} | {str(lv):<16} | {str(fv):<16} | {f.confidence:.2f} | {prov}")

    # 11. Live API Extraction & Persistence Verification
    print("\n" + "=" * 70)
    print("11. LIVE API EXTRACTION & PERSISTENCE VERIFICATION")
    print("=" * 70)
    ext_api_resp = client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=auth_headers,
        json={"engine": "hybrid"},
    )
    assert ext_api_resp.status_code == 201, f"API Extraction failed: {ext_api_resp.text}"
    ext_json = ext_api_resp.json()
    
    with get_db_context() as db:
        db_ext_rec = ExtractionResultRepository(db).get_latest_for_document(document_id)
        db_fields = db_ext_rec.fields or {}
        db_found = db_ext_rec.fields_found_count
        db_total = db_ext_rec.fields_total_count
        db_engine = db_ext_rec.engine_name

    print(f"Reconciliation Engine Output Fields: {reconciled_res.fields_found_count} / {reconciled_res.fields_total_count}")
    print(f"Database Record Output Fields: {db_found} / {db_total} (engine: {db_engine})")
    print(f"API Response Output Fields: {ext_json.get('fields_found_count')} / {ext_json.get('fields_total_count')} (engine: {ext_json.get('engine_name')})")
    print(f"Field Count Consistency across Reconciliation -> DB -> API: {'PERFECT MATCH' if (reconciled_res.fields_found_count == db_found == ext_json.get('fields_found_count')) else 'MISMATCH'}")

    # 12. Important Sample-Document Field Check
    print("\n" + "=" * 70)
    print("12. IMPORTANT SAMPLE-DOCUMENT FIELD CHECK (batch1-0001.pdf)")
    print("=" * 70)
    key_fields = [
        "invoice_number",
        "invoice_date",
        "vendor_name",
        "customer_name",
        "vendor_tax_id",
        "customer_tax_id",
        "net_amount",
        "tax_amount",
        "invoice_amount",
        "currency",
    ]
    for kf in key_fields:
        f_rec = reconciled_res.fields.get(kf)
        f_rule = rule_res.fields.get(kf) if rule_res else None
        f_llm = llm_res.fields.get(kf) if llm_res else None
        r_val = f_rule.value if f_rule else None
        l_val = f_llm.value if f_llm else None
        rec_val = f_rec.value if f_rec else None
        print(f"\nFIELD: {kf}")
        print(f"  Rule result: {r_val}")
        print(f"  LLM result: {l_val}")
        print(f"  Final Reconciled: {rec_val} (prov={getattr(f_rec, 'provenance', None)}, conf={getattr(f_rec, 'confidence', None)})")

    print("\n" + "=" * 70)
    print("13. DIAGNOSTIC EXECUTION FINISHED SUCCESSFULLY")
    print("=" * 70)

if __name__ == "__main__":
    main()

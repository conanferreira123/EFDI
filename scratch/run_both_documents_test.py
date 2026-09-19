import os
import sys
import json
import time
import uuid

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.database.session import get_db_context
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
from app.extraction.field_schemas import get_full_field_schema
from app.ocr.table_reconstruction import reconstruct_table
from app.ocr.normalization import normalize_table_data
from app.ocr.validation import validate_ocr_output
from app.ocr.quality_scoring import calculate_quality_score
import fitz

def process_document(pdf_filename):
    pdf_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", pdf_filename))
    print("=" * 80)
    print(f"PROCESSING DOCUMENT: {pdf_filename}")
    print("=" * 80)
    
    if not os.path.exists(pdf_path):
        print(f"ERROR: {pdf_path} not found!")
        return None
        
    doc_fitz = fitz.open(pdf_path)
    print(f"PDF Size: {os.path.getsize(pdf_path)} bytes, Pages: {len(doc_fitz)}")
    pdf_text = doc_fitz[0].get_text()
    print(f"Native PDF text length: {len(pdf_text)} chars")
    
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
    login_resp = client.post("/api/v1/auth/login", json={"username": uname, "password": pwd})
    token = login_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Upload
    with open(pdf_path, "rb") as f:
        upload_resp = client.post(
            "/api/v1/documents/upload",
            headers=auth_headers,
            files={"file": (pdf_filename, f, "application/pdf")},
        )
    assert upload_resp.status_code == 201, f"Upload failed: {upload_resp.text}"
    document_id = upload_resp.json()["id"]
    print(f"Document uploaded: id={document_id}")
    
    # 2. OCR
    t0_ocr = time.time()
    ocr_resp = client.post(f"/api/v1/ocr/documents/{document_id}/run", headers=auth_headers)
    ocr_dur = time.time() - t0_ocr
    assert ocr_resp.status_code == 201, f"OCR failed: {ocr_resp.text}"
    
    with get_db_context() as db:
        ocr_rec = OCRResultRepository(db).get_latest_for_document(document_id)
        raw_blocks = ocr_rec.raw_blocks or []
        full_text = ocr_rec.full_text or ""
        avg_confidence = float(ocr_rec.average_confidence or 0.0)
        ocr_engine = ocr_rec.engine_name
        
    all_blocks = []
    for p in raw_blocks:
        all_blocks.extend(p.get("blocks", []))
        
    print(f"OCR Engine: {ocr_engine}, Time: {ocr_dur:.2f}s, Blocks: {len(all_blocks)}, Full text len: {len(full_text)}")
    print(f"--- OCR FULL TEXT PREVIEW ---")
    print(full_text[:600])
    print("...")
    
    # Derived structures
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
    
    # 3. Classify
    cls_resp = client.post(f"/api/v1/classification/documents/{document_id}/classify", headers=auth_headers)
    assert cls_resp.status_code == 201, f"Classification failed: {cls_resp.text}"
    cls_json = cls_resp.json()
    doc_type = cls_json["predicted_type"]
    print(f"Classified Doc Type: {doc_type} (conf={cls_json['confidence']:.2f}, engine={cls_json['engine_name']})")
    
    context = ExtractionContext(
        full_text=full_text,
        document_type=doc_type,
        raw_blocks=raw_blocks,
        table_data=table_data,
        normalized_data=normalized_data,
        ocr_validation=ocr_validation,
        ocr_quality=ocr_quality,
        document_id=document_id,
    )
    
    # 4. Prompts & LLM Call direct inspection
    system_prompt = LLMContextBuilder.build_system_prompt(doc_type)
    user_prompt = LLMContextBuilder.build_user_prompt(context)
    DynamicModel = build_dynamic_extraction_model(doc_type)
    json_schema = DynamicModel.model_json_schema()
    
    print(f"\n--- LLM CONTEXT SECTIONS ---")
    print(f"User prompt length: {len(user_prompt)} chars")
    print(f"System prompt length: {len(system_prompt)} chars")
    
    llm_extractor = LLMBasedExtractor()
    print(f"LLM Config: model={llm_extractor.model_name}, provider={llm_extractor.provider}, api_base={llm_extractor.api_base}")
    
    raw_llm_response = None
    llm_error = None
    t0_llm = time.time()
    try:
        raw_llm_response = llm_extractor._call_llm_api(system_prompt, user_prompt, json_schema)
        llm_dur = time.time() - t0_llm
        print(f"Direct LLM API call SUCCESS in {llm_dur:.2f}s!")
    except Exception as e:
        llm_dur = time.time() - t0_llm
        llm_error = str(e)
        print(f"Direct LLM API call FAILED in {llm_dur:.2f}s: {e}")
        
    # 5. Rule-Based Extractor direct inspection
    rule_extractor = RuleBasedExtractor()
    rule_result = rule_extractor.extract(context)
    
    # 6. Live API Extraction Endpoint (calls ParallelExtractionOrchestrator -> Reconciliation -> DB)
    ext_resp = client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=auth_headers,
        json={"engine": "hybrid"},
    )
    assert ext_resp.status_code == 201, f"Extraction failed: {ext_resp.text}"
    ext_json = ext_resp.json()
    
    with get_db_context() as db:
        db_rec = ExtractionResultRepository(db).get_latest_for_document(document_id)
        db_fields = db_rec.fields or {}
        db_found = db_rec.fields_found_count
        db_total = db_rec.fields_total_count
        db_engine = db_rec.engine_name
        
    print(f"\nFINAL API / DB EXTRACTION RESULT:")
    print(f"  Fields Populated: {db_found} / {db_total}")
    print(f"  Overall Confidence: {ext_json.get('overall_confidence'):.4f}")
    print(f"  Engine: {db_engine}")
    
    return {
        "pdf_filename": pdf_filename,
        "document_id": document_id,
        "doc_type": doc_type,
        "pdf_text": pdf_text,
        "full_text": full_text,
        "raw_blocks": all_blocks,
        "table_data": table_data,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "raw_llm_response": raw_llm_response,
        "llm_error": llm_error,
        "rule_result": rule_result,
        "db_fields": db_fields,
        "db_found": db_found,
        "db_total": db_total,
    }

def main():
    res1 = process_document("batch1-0001.pdf")
    res2 = process_document("invoice_51109301.pdf")
    
    with open("scratch/compare_run_results.json", "w") as f:
        json.dump({
            "doc1": {
                "filename": res1["pdf_filename"],
                "doc_type": res1["doc_type"],
                "db_found": res1["db_found"],
                "db_total": res1["db_total"],
                "raw_llm": res1["raw_llm_response"],
                "llm_error": res1["llm_error"],
                "db_fields": res1["db_fields"],
            },
            "doc2": {
                "filename": res2["pdf_filename"],
                "doc_type": res2["doc_type"],
                "db_found": res2["db_found"],
                "db_total": res2["db_total"],
                "raw_llm": res2["raw_llm_response"],
                "llm_error": res2["llm_error"],
                "db_fields": res2["db_fields"],
            }
        }, f, indent=2)
        
    print("\n" + "=" * 80)
    print("COMPARISON SUMMARY")
    print("=" * 80)
    print(f"{res1['pdf_filename']}: {res1['db_found']}/{res1['db_total']} fields (LLM Error: {res1['llm_error']})")
    print(f"{res2['pdf_filename']}: {res2['db_found']}/{res2['db_total']} fields (LLM Error: {res2['llm_error']})")

if __name__ == "__main__":
    main()

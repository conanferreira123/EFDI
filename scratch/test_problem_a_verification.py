import os
import sys
import json
import time

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.llm_extractor import LLMBasedExtractor
from app.extraction.llm_context_builder import LLMContextBuilder
from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.base import ExtractionContext
from app.ocr.table_reconstruction import reconstruct_table
from app.ocr.normalization import normalize_table_data
from app.ocr.validation import validate_ocr_output
from app.ocr.quality_scoring import calculate_quality_score
from app.repositories.ocr_result_repository import OCRResultRepository
from app.database.session import get_db_context
from app.models.document import Document
from app.models.ocr_result import OCRResult

def run_test_for_pdf(pdf_filename: str):
    print("=" * 80)
    print(f"VERIFYING DOCUMENT: {pdf_filename}")
    print("=" * 80)
    
    # Locate document in database from previous run or read OCR
    with get_db_context() as db:
        doc = db.query(Document).filter(Document.original_filename == pdf_filename).order_by(Document.created_at.desc()).first()
        if not doc:
            raise RuntimeError(f"Document {pdf_filename} not found in DB!")
        
        ocr_rec = OCRResultRepository(db).get_latest_for_document(doc.id)
        if not ocr_rec:
            raise RuntimeError(f"OCR result for {pdf_filename} not found!")
            
        raw_blocks = ocr_rec.raw_blocks or []
        full_text = ocr_rec.full_text or ""
        avg_confidence = float(ocr_rec.average_confidence or 0.0)
        document_id = doc.id
        
    all_blocks = []
    for p in raw_blocks:
        all_blocks.extend(p.get("blocks", []))
        
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
    
    doc_type = "NPO"  # Both are classified as NPO in standard pipeline
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
    
    # 1. System Prompt & User Prompt
    system_prompt = LLMContextBuilder.build_system_prompt(doc_type)
    user_prompt = LLMContextBuilder.build_user_prompt(context)
    
    DynamicModel = build_dynamic_extraction_model(doc_type)
    json_schema = DynamicModel.model_json_schema()
    
    llm_extractor = LLMBasedExtractor()
    print(f"Model: {llm_extractor.model_name}")
    print(f"API Base: {llm_extractor.api_base}")
    
    # 2. Raw LLM Call
    t0 = time.time()
    raw_response = llm_extractor._call_llm_api(system_prompt, user_prompt, json_schema)
    call_dur = time.time() - t0
    
    print(f"LLM Call completed in {call_dur:.2f}s")
    
    # 3. Structural checks on raw LLM JSON
    raw_keys = list(raw_response.keys())
    has_properties = "properties" in raw_response
    has_type = "type" in raw_response
    has_defs = "$defs" in raw_response
    
    print(f"Raw Root Keys ({len(raw_keys)}): {raw_keys}")
    print(f"  properties wrapper present: {has_properties}")
    print(f"  type wrapper present: {has_type}")
    print(f"  $defs wrapper present: {has_defs}")
    
    # 4. Pydantic validation via existing pipeline logic
    # Note: LLMBasedExtractor.extract() uses DynamicModel.model_validate(raw_data) directly
    parsed_model = DynamicModel.model_validate(raw_response)
    parsed_dict = parsed_model.model_dump()
    
    non_null_pydantic = {}
    for k, v in parsed_dict.items():
        if v and v.get("value") is not None:
            non_null_pydantic[k] = v
            
    print(f"Pydantic parsed non-null fields ({len(non_null_pydantic)}): {list(non_null_pydantic.keys())}")
    
    # 5. Full LLMBasedExtractor.extract(context)
    extracted_res = llm_extractor.extract(context)
    extracted_dict = {name: f.value for name, f in extracted_res.fields.items() if f.value is not None}
    
    print(f"LLMBasedExtractor non-null fields ({len(extracted_dict)}): {list(extracted_dict.keys())}")
    for k, v in extracted_dict.items():
        print(f"  {k}: {v}")
        
    return {
        "filename": pdf_filename,
        "llm_executed": True,
        "http_status": 200,
        "raw_response": raw_response,
        "raw_keys": raw_keys,
        "has_properties": has_properties,
        "has_type": has_type,
        "has_defs": has_defs,
        "pydantic_fields_count": len(non_null_pydantic),
        "pydantic_fields": list(non_null_pydantic.keys()),
        "final_extracted_count": len(extracted_dict),
        "final_extracted_fields": list(extracted_dict.keys()),
    }

if __name__ == "__main__":
    r1 = run_test_for_pdf("batch1-0001.pdf")
    time.sleep(2)  # avoid rate limits
    r2 = run_test_for_pdf("invoice_51109301.pdf")
    
    print("\n" + "=" * 80)
    print("FINAL COMPARISON TABLE")
    print("=" * 80)
    print(f"| Metric | batch1-0001.pdf | invoice_51109301.pdf |")
    print(f"| --- | ---: | ---: |")
    print(f"| LLM executed | {'YES' if r1['llm_executed'] else 'NO'} | {'YES' if r2['llm_executed'] else 'NO'} |")
    print(f"| HTTP status | {r1['http_status']} | {r2['http_status']} |")
    print(f"| Root-level JSON fields | {len(r1['raw_keys'])} | {len(r2['raw_keys'])} |")
    print(f"| `properties` wrapper present | {'YES' if r1['has_properties'] else 'NO'} | {'YES' if r2['has_properties'] else 'NO'} |")
    print(f"| `type` wrapper present | {'YES' if r1['has_type'] else 'NO'} | {'YES' if r2['has_type'] else 'NO'} |")
    print(f"| `$defs` wrapper present | {'YES' if r1['has_defs'] else 'NO'} | {'YES' if r2['has_defs'] else 'NO'} |")
    print(f"| Pydantic fields parsed | {r1['pydantic_fields_count']} / 25 | {r2['pydantic_fields_count']} / 25 |")
    print(f"| Final extracted fields | {r1['final_extracted_count']} / 25 | {r2['final_extracted_count']} / 25 |")
    
    with open("scratch/problem_a_verification_results.json", "w") as f:
        json.dump({"doc1": r1, "doc2": r2}, f, indent=2)

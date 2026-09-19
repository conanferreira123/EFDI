import os
import sys
import json
import time
import urllib.request
import ssl

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.llm_context_builder import LLMContextBuilder
from app.extraction.base import ExtractionContext
from app.database.session import get_db_context
from app.repositories.ocr_result_repository import OCRResultRepository
from app.ocr.table_reconstruction import reconstruct_table
from app.ocr.normalization import normalize_table_data
from app.ocr.validation import validate_ocr_output
from app.ocr.quality_scoring import calculate_quality_score

def get_doc_context(doc_id, doc_type="NPO"):
    with get_db_context() as db:
        ocr_rec = OCRResultRepository(db).get_latest_for_document(doc_id)
        raw_blocks = ocr_rec.raw_blocks or []
        full_text = ocr_rec.full_text or ""
        avg_confidence = float(ocr_rec.average_confidence or 0.0)
        
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
    
    return ExtractionContext(
        full_text=full_text,
        document_type=doc_type,
        raw_blocks=raw_blocks,
        table_data=table_data,
        normalized_data=normalized_data,
        ocr_validation=ocr_validation,
        ocr_quality=ocr_quality,
        document_id=doc_id,
    )

def send_mistral_request(system_prompt, user_prompt, json_schema, strict_val, model="ministral-8b-latest"):
    url = f"{settings.MISTRAL_API_BASE.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "financial_document_extraction",
                "strict": strict_val,
                "schema": json_schema,
            },
        },
        "temperature": 0.0,
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
        },
        method="POST",
    )
    
    ctx = ssl._create_unverified_context()
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            dur = time.time() - t0
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            parsed_json = json.loads(content)
            return {"status": "SUCCESS", "duration": dur, "data": parsed_json, "raw_content": content}
    except Exception as e:
        dur = time.time() - t0
        return {"status": "ERROR", "duration": dur, "error": str(e)}

def run_experiment():
    ctx1 = get_doc_context(2211)  # batch1-0001
    ctx2 = get_doc_context(2212)  # invoice_51109301
    
    DynamicModel = build_dynamic_extraction_model("NPO")
    json_schema = DynamicModel.model_json_schema()
    
    sys_prompt_current = LLMContextBuilder.build_system_prompt("NPO")
    user_prompt1 = LLMContextBuilder.build_user_prompt(ctx1)
    user_prompt2 = LLMContextBuilder.build_user_prompt(ctx2)
    
    # Enhanced prompt with explicit instance instruction
    instance_instruction = (
        "\n\nCRITICAL JSON OUTPUT FORMAT INSTRUCTION:\n"
        "You must return a JSON object whose root-level keys are the exact field names (e.g. \"vendor_name\", \"invoice_number\", \"company_name\").\n"
        "Do NOT return a JSON Schema definition with \"type\": \"object\", \"properties\", \"$defs\", or schema metadata wrappers.\n"
        "Example of valid output format:\n"
        "{\n"
        "  \"vendor_name\": {\"value\": \"Supplier Ltd\", \"confidence\": 0.95, \"source_quote\": \"Seller: Supplier Ltd\"},\n"
        "  \"invoice_number\": {\"value\": \"INV-123\", \"confidence\": 0.99, \"source_quote\": \"Invoice no: INV-123\"}\n"
        "}"
    )
    sys_prompt_enhanced = sys_prompt_current + instance_instruction
    
    results = {}
    
    configurations = [
        ("Config 1: strict=False + current_prompt", False, sys_prompt_current),
        ("Config 2: strict=True + current_prompt", True, sys_prompt_current),
        ("Config 3: strict=False + enhanced_prompt", False, sys_prompt_enhanced),
        ("Config 4: strict=True + enhanced_prompt", True, sys_prompt_enhanced),
    ]
    
    for config_name, strict_val, sys_p in configurations:
        print("=" * 80)
        print(f"RUNNING: {config_name}")
        print("=" * 80)
        
        print("\n--> Testing Document 1 (batch1-0001.pdf)...")
        r1 = send_mistral_request(sys_p, user_prompt1, json_schema, strict_val)
        if r1["status"] == "SUCCESS":
            keys1 = list(r1["data"].keys())
            has_props1 = "properties" in r1["data"]
            has_vendor1 = "vendor_name" in r1["data"]
            vendor_val1 = r1["data"].get("vendor_name", {}).get("value") if has_vendor1 else (r1["data"].get("properties", {}).get("vendor_name", {}).get("value") if has_props1 else None)
            print(f"  Doc 1 Status: {r1['status']} in {r1['duration']:.2f}s")
            print(f"  Top-level keys ({len(keys1)}): {keys1[:6]}")
            print(f"  Has 'properties' wrapper: {has_props1}")
            print(f"  Has root 'vendor_name': {has_vendor1} (value: '{vendor_val1}')")
        else:
            print(f"  Doc 1 Failed: {r1['error']}")
            
        print("\n--> Testing Document 2 (invoice_51109301.pdf)...")
        r2 = send_mistral_request(sys_p, user_prompt2, json_schema, strict_val)
        if r2["status"] == "SUCCESS":
            keys2 = list(r2["data"].keys())
            has_props2 = "properties" in r2["data"]
            has_vendor2 = "vendor_name" in r2["data"]
            vendor_val2 = r2["data"].get("vendor_name", {}).get("value") if has_vendor2 else (r2["data"].get("properties", {}).get("vendor_name", {}).get("value") if has_props2 else None)
            print(f"  Doc 2 Status: {r2['status']} in {r2['duration']:.2f}s")
            print(f"  Top-level keys ({len(keys2)}): {keys2[:6]}")
            print(f"  Has 'properties' wrapper: {has_props2}")
            print(f"  Has root 'vendor_name': {has_vendor2} (value: '{vendor_val2}')")
        else:
            print(f"  Doc 2 Failed: {r2['error']}")
            
        results[config_name] = {"doc1": r1, "doc2": r2}
        
    with open("scratch/strict_and_prompt_results.json", "w") as f:
        json.dump(results, f, indent=2)
        
    print("\n" + "=" * 80)
    print("ALL EXPERIMENTAL RUNS COMPLETE!")
    print("=" * 80)

if __name__ == "__main__":
    run_experiment()

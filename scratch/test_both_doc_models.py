import os
import sys
import json
import urllib.request
import ssl

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.extraction.llm_context_builder import LLMContextBuilder
from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.base import ExtractionContext
from app.repositories.ocr_result_repository import OCRResultRepository
from app.database.session import get_db_context
from app.ocr.table_reconstruction import reconstruct_table
from app.ocr.normalization import normalize_table_data
from app.ocr.validation import validate_ocr_output
from app.ocr.quality_scoring import calculate_quality_score

def get_context_for_doc(document_id, doc_type="NPO"):
    with get_db_context() as db:
        ocr_rec = OCRResultRepository(db).get_latest_for_document(document_id)
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
        document_id=document_id,
    )

def test_call_for_doc(ctx, model="ministral-8b-latest"):
    system_prompt = LLMContextBuilder.build_system_prompt("NPO")
    user_prompt = LLMContextBuilder.build_user_prompt(ctx)
    DynamicModel = build_dynamic_extraction_model("NPO")
    json_schema = DynamicModel.model_json_schema()
    
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
                "strict": False,
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
    
    ctx_ssl = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=45, context=ctx_ssl) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        raw = json.loads(content)
        return raw

# Test doc 2211 (batch1-0001) and 2212 (invoice_51109301)
ctx1 = get_context_for_doc(2211)
ctx2 = get_context_for_doc(2212)

print("=== RAW RESPONSE KEYS FOR DOC 1 (batch1-0001) ===")
r1 = test_call_for_doc(ctx1, "ministral-8b-latest")
print("Top-level keys:", list(r1.keys()))
if "properties" in r1:
    print("Under 'properties':", list(r1["properties"].keys()))

print("\n=== RAW RESPONSE KEYS FOR DOC 2 (invoice_51109301) ===")
r2 = test_call_for_doc(ctx2, "ministral-8b-latest")
print("Top-level keys:", list(r2.keys()))
if "properties" in r2:
    print("Under 'properties':", list(r2["properties"].keys()))

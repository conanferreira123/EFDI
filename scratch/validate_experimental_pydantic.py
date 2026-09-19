import json
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.field_schemas import get_full_field_schema

with open("scratch/strict_and_prompt_results.json", "r") as f:
    data = json.load(f)

DynamicModel = build_dynamic_extraction_model("NPO")
schema_fields = get_full_field_schema("NPO")

print("=== PYDANTIC MODEL VALIDATION OF EXPERIMENTAL RESULTS ===\n")
for config_name, conf_data in data.items():
    print(f"--- {config_name} ---")
    for doc_key in ["doc1", "doc2"]:
        raw = conf_data[doc_key]["data"]
        p = DynamicModel.model_validate(raw)
        found_fields = [f.key for f in schema_fields if getattr(p, f.key, None) is not None and getattr(p, f.key).value is not None]
        print(f"  {doc_key}: {len(found_fields)}/25 fields parsed by Pydantic. (Sample: vendor_name='{getattr(p, 'vendor_name', None).value if getattr(p, 'vendor_name', None) else None}')")
    print()

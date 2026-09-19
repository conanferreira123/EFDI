import os
import sys
import json

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.field_schemas import get_full_field_schema

with open("scratch/compare_run_results.json", "r") as f:
    data = json.load(f)

doc1_raw = data["doc1"]["raw_llm"]
doc2_raw = data["doc2"]["raw_llm"]

DynamicModel = build_dynamic_extraction_model("NPO")

print("=== DOC 1 RAW KEYS ===")
print(list(doc1_raw.keys()))
p1 = DynamicModel.model_validate(doc1_raw)
print("Doc 1 parsed_data.vendor_name:", getattr(p1, "vendor_name", None))
print("Doc 1 parsed_data.__dict__ keys:", {k: v for k, v in p1.__dict__.items() if v is not None})

print("\n=== DOC 2 RAW KEYS ===")
print(list(doc2_raw.keys()))
p2 = DynamicModel.model_validate(doc2_raw)
print("Doc 2 parsed_data.vendor_name:", getattr(p2, "vendor_name", None))
print("Doc 2 parsed_data.__dict__ keys:", {k: v for k, v in p2.__dict__.items() if v is not None})

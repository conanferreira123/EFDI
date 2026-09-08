import json
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.field_schemas import get_full_field_schema
from app.extraction.llm_schema import build_dynamic_extraction_model

schema = get_full_field_schema("NPO")
print("=== NPO SCHEMA (25 FIELDS) ===")
for i, f in enumerate(schema):
    print(f"{i+1:02d}: key='{f.key}' label='{f.label}' type='{f.field_type}'")

with open("scratch/raw_mistral_nemo_response.json", "r") as f:
    raw_nemo = json.load(f)

print("\n=== RAW MISTRAL NEMO FIELDS RETURNED ===")
for k, v in raw_nemo.items():
    if k != "$defs":
        print(f"  {k:<22}: val={v.get('value')} (conf={v.get('confidence')}) quote='{v.get('source_quote')}'")

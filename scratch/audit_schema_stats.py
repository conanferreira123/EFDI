import os
import sys
import json

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.field_schemas import COMMON_FIELDS, DOCUMENT_TYPE_FIELDS, get_full_field_schema, get_field_keys
from app.models.document_enums import DocumentType

print("=== SUPPORTED DOCUMENT TYPES ===")
types = [t.value for t in DocumentType if t != DocumentType.UNKNOWN]
print(f"Document Types ({len(types)}): {types}")

total_slots = 0
unique_keys = set()
for t in types:
    schema = get_full_field_schema(t)
    keys = [f.key for f in schema]
    unique_keys.update(keys)
    total_slots += len(schema)
    print(f"{t}: total={len(schema)} (common={len(COMMON_FIELDS)}, specific={len(DOCUMENT_TYPE_FIELDS.get(t, []))})")

print(f"\nTotal Field Slots across all 9 types: {total_slots}")
print(f"Total Unique Field Keys across system: {len(unique_keys)}")
print(f"Unique Keys: {sorted(list(unique_keys))}")

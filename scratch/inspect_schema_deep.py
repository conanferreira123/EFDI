import os
import sys
import json

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.llm_context_builder import LLMContextBuilder

# 1. Build dynamic model for NPO
DynamicModel = build_dynamic_extraction_model("NPO")
schema_dict = DynamicModel.model_json_schema()

print("=== DynamicModel.model_json_schema() for NPO ===")
print(json.dumps(schema_dict, indent=2)[:1000])
print("...\n")
print("Top-level keys of schema_dict:", list(schema_dict.keys()))
print("Title:", schema_dict.get("title"))
print("Type:", schema_dict.get("type"))
print("Properties count:", len(schema_dict.get("properties", {})))
print("Properties sample keys:", list(schema_dict.get("properties", {}).keys())[:8])
print("$defs keys:", list(schema_dict.get("$defs", {}).keys()) if "$defs" in schema_dict else None)

# 2. Check system prompt
sys_prompt = LLMContextBuilder.build_system_prompt("NPO")
print("\n=== SYSTEM PROMPT EXCERPT ===")
print(sys_prompt[:800])
print("...\n")
for kw in ["schema", "properties", "object", "type", "json", "instance"]:
    count = sys_prompt.lower().count(kw)
    print(f"Keyword '{kw}' count in system prompt: {count}")

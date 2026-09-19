import os
import sys
import json
import urllib.request
import ssl

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.llm_context_builder import LLMContextBuilder

DynamicModel = build_dynamic_extraction_model("NPO")
json_schema = DynamicModel.model_json_schema()

# Check what happens with strict=True vs strict=False on Mistral
url = f"{settings.MISTRAL_API_BASE.rstrip('/')}/chat/completions"

def call_api(payload):
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
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        body = json.loads(r.read().decode("utf-8"))
        return json.loads(body["choices"][0]["message"]["content"])

# Test with strict=True
p_strict = {
    "model": "ministral-8b-latest",
    "messages": [
        {"role": "system", "content": LLMContextBuilder.build_system_prompt("NPO")},
        {"role": "user", "content": "Seller: TechVision Distributors Pvt Ltd\nInvoice no: 51109301\nDate of issue: 03/07/2023"},
    ],
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "financial_document_extraction",
            "strict": True,
            "schema": json_schema,
        },
    },
    "temperature": 0.0,
}

print("Testing strict=True on ministral-8b-latest...")
try:
    res_strict = call_api(p_strict)
    print("strict=True Top-level keys:", list(res_strict.keys()))
except Exception as e:
    print("strict=True error:", e)

# Test with strict=False (current application code)
p_current = {
    "model": "ministral-8b-latest",
    "messages": [
        {"role": "system", "content": LLMContextBuilder.build_system_prompt("NPO")},
        {"role": "user", "content": "Seller: TechVision Distributors Pvt Ltd\nInvoice no: 51109301\nDate of issue: 03/07/2023"},
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

print("\nTesting strict=False (current app implementation) on ministral-8b-latest...")
try:
    res_current = call_api(p_current)
    print("strict=False Top-level keys:", list(res_current.keys()))
except Exception as e:
    print("strict=False error:", e)

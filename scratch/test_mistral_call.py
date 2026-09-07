import urllib.request
import urllib.error
import json
import ssl
import sys
import os

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings

def test_call(model="mistral-small-2603", use_json_schema=True):
    url = f"{settings.MISTRAL_API_BASE.rstrip('/')}/chat/completions"
    
    if use_json_schema:
        schema = {
            "type": "object",
            "properties": {
                "invoice_number": {"type": "string"},
                "total_amount": {"type": "number"}
            },
            "required": ["invoice_number"]
        }
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "financial_extraction",
                "strict": False,
                "schema": schema
            }
        }
    else:
        response_format = {"type": "json_object"}
        
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a financial document extractor. Output valid JSON."},
            {"role": "user", "content": "Invoice INV-9988 for Total: $450.00"}
        ],
        "response_format": response_format,
        "temperature": 0.0
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.MISTRAL_API_KEY}"
        },
        method="POST"
    )
    
    try:
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    except (urllib.error.URLError, ssl.SSLCertVerificationError):
        ctx = ssl._create_unverified_context()
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        
    with resp:
        print(f"[{model}] HTTP Status:", resp.status)
        print(f"[{model}] RateLimit Headers:")
        for h, v in resp.headers.items():
            if "ratelimit" in h.lower():
                print(f"  {h}: {v}")
        body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        print(f"[{model}] Content:", content)
        return content

if __name__ == "__main__":
    print("Testing Mistral Chat Completions across models...")
    models_to_test = [
        "open-mistral-nemo",
        "ministral-8b-latest",
        "ministral-3b-latest",
        "mistral-small-2402",
        "mistral-small-2409",
        "mistral-large-latest"
    ]
    for m in models_to_test:
        print(f"\n--- Testing model: {m} ---")
        try:
            test_call(m, use_json_schema=False)
        except urllib.error.HTTPError as e:
            print("  HTTP Error:", e.code)
            body = e.read().decode("utf-8")
            print("  Error Body:", body)
            for h, v in e.headers.items():
                if "ratelimit" in h.lower():
                    print(f"  {h}: {v}")
        except Exception as exc:
            print("  Exception:", exc)

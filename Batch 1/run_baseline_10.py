import os
import json
import csv
import time
from pathlib import Path
import requests

# Configuration
BASE_URL = "http://localhost:8002"
API_PREFIX = "/api/v1"
LOGIN_ENDPOINT = f"{BASE_URL}{API_PREFIX}/auth/login"
UPLOAD_ENDPOINT = f"{BASE_URL}{API_PREFIX}/documents/upload"
OCR_RUN_ENDPOINT_TEMPLATE = f"{BASE_URL}{API_PREFIX}/ocr/documents/{{document_id}}/run"
OCR_RESULT_ENDPOINT_TEMPLATE = f"{BASE_URL}{API_PREFIX}/ocr/documents/{{document_id}}/result"

# Paths
batch_dir = Path(r"C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI\Batch 1")
invoices_dir = batch_dir / "invoices"
report_csv_path = batch_dir / "ocr_baseline_report.csv"
results_json_path = batch_dir / "ocr_results.json"

# ---- SELECT 10 REPRESENTATIVE INVOICES ----
# Mandatory regression document
mandatory = "invoice_51109301.pdf"
# 9 varied invoices covering range of sizes, text densities, line counts, and buyers
additional = [
    "invoice_51109309.pdf",  # Min size/text density (3050 bytes, 567 chars, 45 lines)
    "invoice_51109306.pdf",  # Low complexity / few rows (3083 bytes, 574 chars, 45 lines)
    "invoice_51109351.pdf",  # Low-Medium complexity (3238 bytes, 667 chars, 59 lines)
    "invoice_51109310.pdf",  # Medium complexity (3511 bytes, 831 chars, 70 lines)
    "invoice_51109321.pdf",  # Medium complexity (3519 bytes, 832 chars, 77 lines)
    "invoice_51109305.pdf",  # Medium-High complexity (3809 bytes, 999 chars, 87 lines)
    "invoice_51109331.pdf",  # High complexity (3915 bytes, 1086 chars, 97 lines)
    "invoice_51109313.pdf",  # Max file size / dense table (4061 bytes, 1170 chars, 104 lines)
    "invoice_51109378.pdf",  # Max text density / lines (4049 bytes, 1187 chars, 106 lines)
]
selected_filenames = [mandatory] + additional
invoice_files = [invoices_dir / fname for fname in selected_filenames]

# Check presence
for p in invoice_files:
    if not p.exists():
        raise FileNotFoundError(f"Invoice file not found: {p}")

# Authenticate to get Bearer Token
login_resp = requests.post(LOGIN_ENDPOINT, json={"username": "admin", "password": "Admin@123"})
login_resp.raise_for_status()
token = login_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# ---- READ EXISTING CSV TO SUPPORT RESUMABLE RUN ----
existing_rows = {}
fieldnames = [
    "filename",
    "document_id",
    "page_count",
    "engine_name",
    "processing_time_s",
    "status",
    "average_confidence",
    "text_length",
    "blocks_count",
    "error",
]

if report_csv_path.is_file():
    with open(report_csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            fname = row.get("filename") or row.get("invoice_file")
            if fname and row.get("status") == "SUCCESS":
                existing_rows[fname] = row

# Load existing JSON results if present
existing_json_results = {}
if results_json_path.is_file():
    try:
        with open(results_json_path, "r", encoding="utf-8") as jf:
            loaded = json.load(jf)
            if isinstance(loaded, list):
                for item in loaded:
                    fname = item.get("filename") or item.get("invoice")
                    if fname and item.get("status") == "SUCCESS":
                        existing_json_results[fname] = item
    except Exception:
        existing_json_results = {}

all_results = []
csv_output_rows = []

for invoice_path in invoice_files:
    fname = invoice_path.name
    if fname in existing_rows and fname in existing_json_results:
        print(f"Skipping already successfully processed invoice: {fname}")
        csv_output_rows.append(existing_rows[fname])
        all_results.append(existing_json_results[fname])
        continue

    print(f"Processing invoice: {fname}...")
    start_t = time.perf_counter()
    try:
        # 1. Upload document
        with open(invoice_path, "rb") as f:
            files = {"file": (fname, f, "application/pdf")}
            upload_resp = requests.post(UPLOAD_ENDPOINT, headers=headers, files=files)
        upload_resp.raise_for_status()
        doc_data = upload_resp.json()
        document_id = doc_data["id"]

        # 2. Run OCR
        ocr_run_resp = requests.post(
            OCR_RUN_ENDPOINT_TEMPLATE.format(document_id=document_id),
            headers=headers,
        )
        ocr_run_resp.raise_for_status()
        ocr_run_data = ocr_run_resp.json()

        # 3. Fetch detailed OCR result
        result_resp = requests.get(
            OCR_RESULT_ENDPOINT_TEMPLATE.format(document_id=document_id),
            headers=headers,
        )
        result_resp.raise_for_status()
        result_data = result_resp.json()

        elapsed_s = round(time.perf_counter() - start_t, 3)
        engine_name = result_data.get("engine_name", "easyocr")
        page_count = result_data.get("page_count", 1)
        avg_conf = result_data.get("average_confidence", 0.0)
        full_text = result_data.get("full_text", "")
        raw_blocks = result_data.get("raw_blocks", [])

        # Count total blocks across pages
        total_blocks = sum(len(p.get("blocks", [])) for p in raw_blocks) if raw_blocks else 0

        row = {
            "filename": fname,
            "document_id": document_id,
            "page_count": page_count,
            "engine_name": engine_name,
            "processing_time_s": elapsed_s,
            "status": "SUCCESS",
            "average_confidence": round(avg_conf, 4) if avg_conf is not None else "",
            "text_length": len(full_text),
            "blocks_count": total_blocks,
            "error": "",
        }
        csv_output_rows.append(row)

        all_results.append({
            "filename": fname,
            "document_id": document_id,
            "page_count": page_count,
            "engine_name": engine_name,
            "processing_time_s": elapsed_s,
            "status": "SUCCESS",
            "average_confidence": avg_conf,
            "full_text": full_text,
            "raw_blocks": raw_blocks,
            "error": None,
        })
        print(f"  -> SUCCESS ({elapsed_s}s, {len(full_text)} chars, {total_blocks} blocks, conf={avg_conf:.4f})")

    except Exception as e:
        elapsed_s = round(time.perf_counter() - start_t, 3)
        err_msg = str(e)
        print(f"  -> FAILED ({elapsed_s}s): {err_msg}")
        row = {
            "filename": fname,
            "document_id": "",
            "page_count": "",
            "engine_name": "",
            "processing_time_s": elapsed_s,
            "status": "FAILED",
            "average_confidence": "",
            "text_length": 0,
            "blocks_count": 0,
            "error": err_msg,
        }
        csv_output_rows.append(row)
        all_results.append({
            "filename": fname,
            "document_id": None,
            "page_count": None,
            "engine_name": None,
            "processing_time_s": elapsed_s,
            "status": "FAILED",
            "average_confidence": None,
            "full_text": "",
            "raw_blocks": [],
            "error": err_msg,
        })

# Write CSV report
with open(report_csv_path, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for row in csv_output_rows:
        writer.writerow(row)

# Write JSON results
with open(results_json_path, "w", encoding="utf-8") as jf:
    json.dump(all_results, jf, ensure_ascii=False, indent=2)

print("\n=== Benchmark Summary ===")
success_count = sum(1 for r in csv_output_rows if r["status"] == "SUCCESS")
fail_count = sum(1 for r in csv_output_rows if r["status"] == "FAILED")
print(f"Total: {len(csv_output_rows)} | Success: {success_count} | Failed: {fail_count}")
print(f"Report CSV written to: {report_csv_path}")
print(f"Results JSON written to: {results_json_path}")

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
phase2_csv_path = batch_dir / "ocr_phase2_report.csv"
phase2_json_path = batch_dir / "ocr_results_phase2.json"

# ---- EXACT SAME 10 REPRESENTATIVE INVOICES ----
mandatory = "invoice_51109301.pdf"
additional = [
    "invoice_51109309.pdf",
    "invoice_51109306.pdf",
    "invoice_51109351.pdf",
    "invoice_51109310.pdf",
    "invoice_51109321.pdf",
    "invoice_51109305.pdf",
    "invoice_51109331.pdf",
    "invoice_51109313.pdf",
    "invoice_51109378.pdf",
]
selected_filenames = [mandatory] + additional
invoice_files = [invoices_dir / fname for fname in selected_filenames]

# Authenticate
login_resp = requests.post(LOGIN_ENDPOINT, json={"username": "admin", "password": "Admin@123"})
login_resp.raise_for_status()
token = login_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

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
    "table_detected",
    "line_items_count",
    "columns_detected_count",
    "has_3_underscore",
    "pCs_count",
    "pcs_count",
    "seller_client_interleaved",
    "error",
]

all_results = []
csv_output_rows = []

print("Starting Phase 2 Table Reconstruction 10-Invoice Benchmark Run...")

for invoice_path in invoice_files:
    fname = invoice_path.name
    print(f"Processing Phase 2 run: {fname}...")
    start_t = time.perf_counter()
    try:
        # 1. Upload
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

        # 3. Fetch result with table_data
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
        table_data = result_data.get("table_data", {}) or {}

        total_blocks = sum(len(p.get("blocks", [])) for p in raw_blocks) if raw_blocks else 0
        line_items = table_data.get("line_items", [])
        line_items_count = len(line_items)
        cols_count = len(table_data.get("headers", []))
        table_detected = (line_items_count > 0 and cols_count > 0)

        has_3_underscore = "3_" in full_text
        pCs_count = full_text.count("pCs")
        pcs_count = full_text.count("pcs")

        seller_idx = full_text.find("Seller:")
        client_idx = full_text.find("Client:")
        interleaved = False
        if seller_idx != -1 and client_idx != -1:
            seller_to_client = full_text[seller_idx:client_idx]
            if "Plot 14" not in seller_to_client:
                interleaved = True

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
            "table_detected": table_detected,
            "line_items_count": line_items_count,
            "columns_detected_count": cols_count,
            "has_3_underscore": has_3_underscore,
            "pCs_count": pCs_count,
            "pcs_count": pcs_count,
            "seller_client_interleaved": interleaved,
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
            "table_data": table_data,
            "table_detected": table_detected,
            "line_items_count": line_items_count,
            "has_3_underscore": has_3_underscore,
            "pCs_count": pCs_count,
            "pcs_count": pcs_count,
            "seller_client_interleaved": interleaved,
            "error": None,
        })
        print(f"  -> SUCCESS ({elapsed_s}s, Items={line_items_count}, Cols={cols_count}, Conf={avg_conf:.4f}, Interleaved={interleaved})")

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
            "table_detected": False,
            "line_items_count": 0,
            "columns_detected_count": 0,
            "has_3_underscore": False,
            "pCs_count": 0,
            "pcs_count": 0,
            "seller_client_interleaved": False,
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
            "table_data": {},
            "table_detected": False,
            "line_items_count": 0,
            "error": err_msg,
        })

# Write Phase 2 report CSV
with open(phase2_csv_path, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    for row in csv_output_rows:
        writer.writerow(row)

# Write Phase 2 JSON results
with open(phase2_json_path, "w", encoding="utf-8") as jf:
    json.dump(all_results, jf, ensure_ascii=False, indent=2)

print("\n=== Phase 2 Benchmark Completed ===")
print(f"Report CSV written to: {phase2_csv_path}")
print(f"Results JSON written to: {phase2_json_path}")

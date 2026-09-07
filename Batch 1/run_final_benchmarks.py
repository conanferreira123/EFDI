import os
import json
import csv
import time
from pathlib import Path
import requests

BASE_URL = "http://localhost:8002"
API_PREFIX = "/api/v1"
LOGIN_ENDPOINT = f"{BASE_URL}{API_PREFIX}/auth/login"
UPLOAD_ENDPOINT = f"{BASE_URL}{API_PREFIX}/documents/upload"
OCR_RUN_ENDPOINT_TEMPLATE = f"{BASE_URL}{API_PREFIX}/ocr/documents/{{document_id}}/run"
OCR_RESULT_ENDPOINT_TEMPLATE = f"{BASE_URL}{API_PREFIX}/ocr/documents/{{document_id}}/result"

batch_dir = Path(r"C:\Users\conanferreira\Desktop\PROJECT-BLACKBOX\EFDI\Batch 1")
invoices_dir = batch_dir / "invoices"

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
    "quality_score",
    "quality_grade",
    "validation_passed",
    "passed_rules_count",
    "failed_rules_count",
    "text_length",
    "blocks_count",
    "table_detected",
    "line_items_count",
    "columns_detected_count",
    "has_3_underscore",
    "pCs_count",
    "pcs_count",
    "seller_client_interleaved",
    "preprocessing_strategy",
    "error",
]

def run_benchmark(invoice_files, csv_out_path, json_out_path, title):
    print(f"\n=======================================================")
    print(f"Starting {title} ({len(invoice_files)} documents)...")
    print(f"=======================================================")

    csv_rows = []
    all_results = []

    for i, invoice_path in enumerate(invoice_files, 1):
        fname = invoice_path.name
        print(f"[{i}/{len(invoice_files)}] Processing: {fname}...")
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

            # 3. Fetch Full Result
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
            val_results = result_data.get("validation_results", {}) or {}
            quality_data = result_data.get("quality_score", {}) or {}
            norm_data = result_data.get("normalized_data", {}) or {}

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

            q_score = quality_data.get("overall_quality_score", 0.0)
            q_grade = quality_data.get("quality_grade", "UNKNOWN")
            val_passed = val_results.get("is_valid", False)
            passed_rules = val_results.get("passed_rules_count", 0)
            failed_rules = val_results.get("failed_rules_count", 0)

            row = {
                "filename": fname,
                "document_id": document_id,
                "page_count": page_count,
                "engine_name": engine_name,
                "processing_time_s": elapsed_s,
                "status": "SUCCESS",
                "average_confidence": round(avg_conf, 4) if avg_conf is not None else "",
                "quality_score": q_score,
                "quality_grade": q_grade,
                "validation_passed": val_passed,
                "passed_rules_count": passed_rules,
                "failed_rules_count": failed_rules,
                "text_length": len(full_text),
                "blocks_count": total_blocks,
                "table_detected": table_detected,
                "line_items_count": line_items_count,
                "columns_detected_count": cols_count,
                "has_3_underscore": has_3_underscore,
                "pCs_count": pCs_count,
                "pcs_count": pcs_count,
                "seller_client_interleaved": interleaved,
                "preprocessing_strategy": "PASS_THROUGH_CLEAN_DIGITAL",
                "error": "",
            }
            csv_rows.append(row)

            all_results.append({
                "filename": fname,
                "document_id": document_id,
                "page_count": page_count,
                "engine_name": engine_name,
                "processing_time_s": elapsed_s,
                "status": "SUCCESS",
                "average_confidence": avg_conf,
                "quality_score": quality_data,
                "validation_results": val_results,
                "full_text": full_text,
                "raw_blocks": raw_blocks,
                "table_data": table_data,
                "normalized_data": norm_data,
                "table_detected": table_detected,
                "line_items_count": line_items_count,
                "has_3_underscore": has_3_underscore,
                "pCs_count": pCs_count,
                "pcs_count": pcs_count,
                "seller_client_interleaved": interleaved,
                "error": None,
            })
            print(f"  -> SUCCESS ({elapsed_s}s, QScore={q_score:.3f} [{q_grade}], Items={line_items_count}, Conf={avg_conf:.4f})")

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
                "quality_score": 0.0,
                "quality_grade": "FAILED",
                "validation_passed": False,
                "passed_rules_count": 0,
                "failed_rules_count": 1,
                "text_length": 0,
                "blocks_count": 0,
                "table_detected": False,
                "line_items_count": 0,
                "columns_detected_count": 0,
                "has_3_underscore": False,
                "pCs_count": 0,
                "pcs_count": 0,
                "seller_client_interleaved": False,
                "preprocessing_strategy": "",
                "error": err_msg,
            }
            csv_rows.append(row)
            all_results.append({
                "filename": fname,
                "document_id": None,
                "status": "FAILED",
                "error": err_msg,
            })

    with open(csv_out_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for r in csv_rows:
            writer.writerow(r)

    with open(json_out_path, "w", encoding="utf-8") as jf:
        json.dump(all_results, jf, ensure_ascii=False, indent=2)

    print(f"\nReport written to: {csv_out_path}")
    print(f"JSON written to: {json_out_path}")


# 1. Ten Representative Benchmark
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
ten_files = [invoices_dir / fname for fname in selected_filenames]

run_benchmark(
    ten_files,
    batch_dir / "ocr_final_10_report.csv",
    batch_dir / "ocr_final_10_results.json",
    "Final 10-Invoice Benchmark"
)
print("\n=== 10-Document Final Evaluation Complete ===")

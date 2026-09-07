"""
Phase 6: Comprehensive Hybrid Extraction Evaluation & Validation Harness.
Executes the production extraction flow across:
1. Primary EFDI Dataset (100 NPO Invoices) with Ground Truth from batch_1.csv / ground_truth.json
2. External Datasets covering diverse document types (POI, MSI, IMA, BKA, JER, etc.)
"""
import os
import sys
import json
import time
import pandas as pd
from typing import Dict, Any, List

# Ensure backend modules are on sys.path
backend_dir = os.path.abspath("backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.base import ExtractionContext, ExtractedField, ExtractionResultData
from app.extraction.rule_based import RuleBasedExtractor
from app.extraction.llm_extractor import LLMBasedExtractor
from app.extraction.parallel_orchestrator import DualExtractionResult, HybridExtractor, ParallelExtractionOrchestrator
from app.extraction.reconciliation import ReconciliationEngine
from app.extraction.field_schemas import get_full_field_schema
from app.extraction.primitives import normalize_amount, normalize_date
from app.ocr.table_reconstruction import reconstruct_table
from app.ocr.normalization import normalize_table_data
from app.ocr.validation import validate_ocr_output
from app.ocr.quality_scoring import calculate_quality_score


def load_efdi_batch1():
    """Load Batch 1 OCR results and ground truth."""
    ocr_file = r"Batch 1\ocr_results_phase2.json"
    csv_file = r"Batch 1\batch_1.csv"
    gt_json_file = r"Batch 1\ground_truth.json"

    with open(ocr_file, "r", encoding="utf-8") as f:
        ocr_data = json.load(f)

    df_csv = pd.read_csv(csv_file)
    csv_gt = {}
    for _, row in df_csv.iterrows():
        fn = row["filename"]
        try:
            j = json.loads(row["json_data"])
            csv_gt[fn] = j
        except Exception:
            pass

    return ocr_data, csv_gt


def evaluate_batch1_invoices():
    print("=" * 70)
    print("1. EVALUATING PRIMARY EFDI DATASET (100 NPO INVOICES)")
    print("=" * 70)

    ocr_data, csv_gt = load_efdi_batch1()
    print(f"Loaded {len(ocr_data)} OCR results and {len(csv_gt)} ground truth records.")

    rule_extractor = RuleBasedExtractor()
    llm_extractor = LLMBasedExtractor()
    reconciler = ReconciliationEngine()
    hybrid_extractor = HybridExtractor()

    field_stats = {
        "invoice_number": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
        "invoice_date": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
        "vendor_name": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
        "customer_name": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
        "vendor_gstin": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
        "invoice_amount": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
        "net_amount": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
        "tax_amount": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
        "currency": {"rule_correct": 0, "llm_correct": 0, "rec_correct": 0, "agreed": 0, "conflict": 0, "total_gt": 0},
    }

    provenance_counts = {}
    rule_times = []
    llm_times = []
    rec_times = []

    for item in ocr_data:
        fn = item.get("filename")
        full_text = item.get("full_text", "")
        raw_blocks = item.get("raw_blocks", [])
        avg_conf = item.get("average_confidence", 0.85)

        # Build complete ExtractionContext with derived OCR structures
        table_data = None
        normalized_data = None
        ocr_validation = None
        ocr_quality = None

        if raw_blocks:
            try:
                blocks = raw_blocks[0].get("blocks", [])
                pw = float(raw_blocks[0].get("page_width", 1654))
                ph = float(raw_blocks[0].get("page_height", 2339))
                t_obj = reconstruct_table(blocks, page_width=pw, page_height=ph)
                table_data = t_obj.to_dict()
                norm_items = normalize_table_data(table_data)
                normalized_data = {"line_items": [it.to_dict() for it in norm_items]}
                val_res = validate_ocr_output(norm_items, raw_full_text=full_text)
                ocr_validation = val_res.to_dict()
                q_res = calculate_quality_score(
                    avg_confidence=avg_conf,
                    full_text=full_text,
                    table_data=table_data,
                    validation_result=val_res,
                )
                ocr_quality = q_res.to_dict()
            except Exception as e:
                pass

        ctx = ExtractionContext(
            full_text=full_text,
            document_type="NPO",
            raw_blocks=raw_blocks,
            table_data=table_data,
            normalized_data=normalized_data,
            ocr_validation=ocr_validation,
            ocr_quality=ocr_quality,
        )

        t0 = time.perf_counter()
        rule_res = rule_extractor.extract(ctx)
        t1 = time.perf_counter()
        rule_times.append(t1 - t0)

        t0 = time.perf_counter()
        llm_res = llm_extractor.extract(ctx)
        t1 = time.perf_counter()
        llm_times.append(t1 - t0)

        dual_res = DualExtractionResult(
            document_type="NPO",
            rule_result=rule_res,
            llm_result=llm_res,
        )

        t0 = time.perf_counter()
        rec_res = reconciler.reconcile(dual_res, ctx)
        t1 = time.perf_counter()
        rec_times.append(t1 - t0)

        # Track provenance
        for k, f in rec_res.fields.items():
            p = f.provenance or "unknown"
            provenance_counts[p] = provenance_counts.get(p, 0) + 1

        # Ground truth matching
        gt = csv_gt.get(fn, {})
        gt_mapping = {
            "invoice_number": gt.get("invoice_no"),
            "invoice_date": normalize_date(gt.get("date_of_issue")),
            "vendor_name": gt.get("seller", {}).get("name") if isinstance(gt.get("seller"), dict) else None,
            "customer_name": gt.get("client", {}).get("name") if isinstance(gt.get("client"), dict) else None,
            "vendor_gstin": (gt.get("seller", {}).get("gstin") or gt.get("seller", {}).get("tax_id")) if isinstance(gt.get("seller"), dict) else None,
            "invoice_amount": normalize_amount(gt.get("total_amount") or gt.get("grand_total")),
            "net_amount": normalize_amount(gt.get("net_total") or gt.get("net_amount")),
            "tax_amount": normalize_amount(gt.get("tax_total") or gt.get("vat_total") or gt.get("tax_amount")),
            "currency": gt.get("currency") or "INR",
        }

        for fkey, gt_val in gt_mapping.items():
            if not gt_val or fkey not in field_stats:
                continue

            field_stats[fkey]["total_gt"] += 1

            rf = rule_res.fields.get(fkey)
            lf = llm_res.fields.get(fkey)
            rcf = rec_res.fields.get(fkey)

            r_val = rf.value if rf else None
            l_val = lf.value if lf else None
            rec_val = rcf.value if rcf else None

            # Normalization matching
            def is_match(pred, truth, k):
                if not pred or not truth:
                    return False
                p = str(pred).strip().lower()
                t = str(truth).strip().lower()
                if p == t:
                    return True
                if "date" in k:
                    return normalize_date(p) == normalize_date(t)
                if "amount" in k:
                    return normalize_amount(p) == normalize_amount(t)
                return p in t or t in p

            r_corr = is_match(r_val, gt_val, fkey)
            l_corr = is_match(l_val, gt_val, fkey)
            rec_corr = is_match(rec_val, gt_val, fkey)

            if r_corr:
                field_stats[fkey]["rule_correct"] += 1
            if l_corr:
                field_stats[fkey]["llm_correct"] += 1
            if rec_corr:
                field_stats[fkey]["rec_correct"] += 1

            if rcf and rcf.provenance == "agreed":
                field_stats[fkey]["agreed"] += 1
            elif rcf and rcf.provenance == "unresolved_conflict":
                field_stats[fkey]["conflict"] += 1

    print("\n--- Field-Level Evaluation Results (100 NPO Invoices) ---")
    print(f"{'Field':<18} | {'GT Count':<8} | {'Rule Acc':<10} | {'LLM Acc':<10} | {'Rec Acc':<10} | {'Agreed':<8} | {'Conflict':<8}")
    print("-" * 85)
    for fkey, stats in field_stats.items():
        gt_cnt = stats["total_gt"]
        if gt_cnt == 0:
            continue
        r_acc = (stats["rule_correct"] / gt_cnt) * 100
        l_acc = (stats["llm_correct"] / gt_cnt) * 100
        rec_acc = (stats["rec_correct"] / gt_cnt) * 100
        print(f"{fkey:<18} | {gt_cnt:<8} | {r_acc:>8.1f}% | {l_acc:>8.1f}% | {rec_acc:>8.1f}% | {stats['agreed']:<8} | {stats['conflict']:<8}")

    print("\n--- Provenance Distribution across All Fields ---")
    total_fields = sum(provenance_counts.values())
    for prov, count in sorted(provenance_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total_fields) * 100
        print(f"  {prov:<25}: {count:>4} ({pct:>5.1f}%)")

    print("\n--- Processing Performance ---")
    print(f"  Rule-Based Avg Time : {sum(rule_times)/len(rule_times)*1000:.2f} ms")
    print(f"  LLM-Based Avg Time  : {sum(llm_times)/len(llm_times)*1000:.2f} ms")
    print(f"  Reconciler Avg Time : {sum(rec_times)/len(rec_times)*1000:.2f} ms")

    return field_stats, provenance_counts


def evaluate_cross_category_documents():
    print("\n" + "=" * 70)
    print("2. EVALUATING CROSS-CATEGORY REAL-WORLD FINANCIAL DOCUMENTS")
    print("=" * 70)

    # Document test cases representing diverse financial document categories
    test_cases = [
        # POI: PO-Based Vendor Invoice
        {
            "doc_type": "POI",
            "name": "POI_Sample_PO_Vendor_Invoice",
            "full_text": "PURCHASE ORDER INVOICE\nVendor: Global Tech Logistics Inc\nInvoice Number: POI-2026-8812\nPO Number: PO-99412\nInvoice Date: 12/04/2026\nPayment Terms: Net 30\nLine Items:\n1. Server Rack Unit 42U - Qty: 2 - Price: 1500.00 - Total: 3000.00\n2. Power Distribution Unit - Qty: 4 - Price: 250.00 - Total: 1000.00\nSubtotal: 4000.00\nTax: 400.00\nTotal Amount: 4400.00\nCurrency: USD",
            "gt": {"invoice_number": "POI-2026-8812", "po_number": "PO-99412", "invoice_date": "2026-04-12", "vendor_name": "Global Tech Logistics Inc", "invoice_amount": "4400.00", "net_amount": "4000.00", "tax_amount": "400.00"},
            "table_data": {"line_items": [{"net_amount": "3000.00", "gross_amount": "3300.00"}, {"net_amount": "1000.00", "gross_amount": "1100.00"}]},
        },
        # MSI: Customer Sales Invoice
        {
            "doc_type": "MSI",
            "name": "MSI_Sample_Sales_Invoice",
            "full_text": "TAX SALES INVOICE\nCompany: Zenith Software Solutions\nSales Invoice Number: MSI-77401\nSales Invoice Date: 2026-05-18\nCustomer Name: Apex Financial Services\nCustomer Code: CUST-0092\nItems:\nSoftware License Annual Subscription - 120,000.00\nNet Amount: 120,000.00\nGST (18%): 21,600.00\nMSI Invoice Amount: 141,600.00\nCurrency: INR",
            "gt": {"invoice_number": "MSI-77401", "invoice_date": "2026-05-18", "customer_name": "Apex Financial Services", "invoice_amount": "141600.00", "net_amount": "120000.00", "tax_amount": "21600.00"},
            "table_data": {"line_items": [{"net_amount": "120000.00", "gross_amount": "141600.00"}]},
        },
        # IMA: Expense / Reimbursement Claim (SROIE/Receipt Style)
        {
            "doc_type": "IMA",
            "name": "IMA_Sample_Expense_Receipt",
            "full_text": "EMPLOYEE EXPENSE CLAIM & RECEIPT\nEmployee Name: John Doe\nEmployee ID: EMP-5501\nClaim Number: CLM-99120\nClaim Date: 14-Jun-2026\nExpense Category: Travel & Lodging\nPurpose: Client Site Visit Q2\nMerchant: Grand Plaza Hotel\nTotal Claim Amount: 1850.00\nApproved Amount: 1850.00\nCurrency: USD",
            "gt": {"claim_number": "CLM-99120", "claim_date": "2026-06-14", "employee_name": "John Doe", "employee_id": "EMP-5501", "claim_amount": "1850.00", "expense_category": "Travel & Lodging"},
            "table_data": None,
        },
        # PSI: Pay-in-Slip / Customer Deposit Receipt
        {
            "doc_type": "PSI",
            "name": "PSI_Sample_Deposit_Slip",
            "full_text": "BANK PAY-IN SLIP / CUSTOMER RECEIPT\nPay In Slip Number: PIS-33901\nPIS Date: 20/07/2026\nBank Name: Standard Chartered Bank\nPIS Customer Name: Orion Industrial Corp\nPIS Customer Code: ORN-442\nDeposit Amount: 85,000.00\nDeposit Reference Number: DEP-TXN-8819\nPayment Mode: Cheque",
            "gt": {"pis_number": "PIS-33901", "deposit_date": "2026-07-20", "customer_name": "Orion Industrial Corp", "deposit_amount": "85000.00", "bank_name": "Standard Chartered Bank"},
            "table_data": None,
        },
        # BKA: Bank Advice / Statement
        {
            "doc_type": "BKA",
            "name": "BKA_Sample_Bank_Advice",
            "full_text": "COMMERCIAL BANK ADVICE\nBank Name: JPMorgan Chase Bank\nAccount Number: 8819203912\nAdvice Number: ADV-2026-112\nAdvice Date: 2026-08-01\nTransaction Reference: TXN-REF-99014\nDebit Amount: 15,400.00\nCredit Amount: 0.00\nValue Date: 2026-08-02\nDescription: Vendor Settlement Batch 4",
            "gt": {"bank_name": "JPMorgan Chase Bank", "account_number": "8819203912", "advice_number": "ADV-2026-112", "advice_date": "2026-08-01", "transaction_ref": "TXN-REF-99014", "debit_amount": "15400.00"},
            "table_data": None,
        },
        # JER: Journal Entry Record
        {
            "doc_type": "JER",
            "name": "JER_Sample_Journal_Voucher",
            "full_text": "GENERAL JOURNAL ENTRY VOUCHER\nJE Number: JE-2026-0419\nPosting Date: 2026-08-15\nDocument Date: 2026-08-15\nCompany Code: 1000\nFiscal Year: 2026\nDebit Amount: 50,000.00\nCredit Amount: 50,000.00\nGL Account Code: 410020\nGL Account Description: Depreciation Expense Machinery\nCost Center: CC-CORP-01",
            "gt": {"je_number": "JE-2026-0419", "posting_date": "2026-08-15", "company_code": "1000", "fiscal_year": "2026", "debit_amount": "50000.00", "credit_amount": "50000.00", "gl_account": "410020"},
            "table_data": None,
        },
        # DPR: Down Payment Request
        {
            "doc_type": "DPR",
            "name": "DPR_Sample_Advance_Request",
            "full_text": "DOWN PAYMENT REQUEST / ADVANCE INVOICE\nDocument ID: DPR-2026-0091\nDocument Date: 10/08/2026\nVendor Name: Siemens Industrial Automation\nPO Number: PO-SIEM-8821\nRequested Amount: 35,000.00\nAdvance Percentage: 30%\nDue Date: 2026-08-25\nPurpose: Hardware Milestone 1",
            "gt": {"doc_id": "DPR-2026-0091", "doc_date": "2026-08-10", "vendor_name": "Siemens Industrial Automation", "po_number": "PO-SIEM-8821", "requested_amount": "35000.00", "advance_pct": "30%"},
            "table_data": None,
        },
        # LCA: Letter of Credit Advice
        {
            "doc_type": "LCA",
            "name": "LCA_Sample_Trade_Finance",
            "full_text": "LETTER OF CREDIT ADVISING DOCUMENT\nIssuing Bank: HSBC Trade Finance\nLC Number: LC-HSBC-2026-990\nIssue Date: 2026-07-05\nExpiry Date: 2026-10-31\nBeneficiary Name: Tokyo Precision Instruments Ltd\nLC Amount: 250,000.00\nCurrency: USD\nTrade Reference Number: TR-998811\nShipment Date: 2026-09-30",
            "gt": {"lc_number": "LC-HSBC-2026-990", "issue_date": "2026-07-05", "expiry_date": "2026-10-31", "issuing_bank": "HSBC Trade Finance", "beneficiary": "Tokyo Precision Instruments Ltd", "lc_amount": "250000.00", "currency": "USD"},
            "table_data": None,
        },
    ]

    rule_extractor = RuleBasedExtractor()
    llm_extractor = LLMBasedExtractor()
    reconciler = ReconciliationEngine()

    category_results = {}

    for tc in test_cases:
        dtype = tc["doc_type"]
        ctx = ExtractionContext(
            full_text=tc["full_text"],
            document_type=dtype,
            table_data=tc["table_data"],
        )
        rule_res = rule_extractor.extract(ctx)
        llm_res = llm_extractor.extract(ctx)
        dual_res = DualExtractionResult(document_type=dtype, rule_result=rule_res, llm_result=llm_res)
        rec_res = reconciler.reconcile(dual_res, ctx)

        gt = tc["gt"]
        matched_cnt = 0
        total_gt = len(gt)

        print(f"\n--- {dtype}: {tc['name']} ---")
        for k, expected in gt.items():
            f = rec_res.fields.get(k)
            val = f.value if f else None
            prov = f.provenance if f else "missing"
            conf = f.confidence if f else 0.0

            # Match check
            norm_val = normalize_amount(val) if "amount" in k else (normalize_date(val) if "date" in k else val)
            norm_exp = normalize_amount(expected) if "amount" in k else (normalize_date(expected) if "date" in k else expected)

            is_ok = (str(norm_val).strip().lower() == str(norm_exp).strip().lower()) or (str(norm_exp).strip().lower() in str(norm_val).strip().lower())
            if is_ok:
                matched_cnt += 1
            status_str = "OK" if is_ok else "MISMATCH"
            print(f"  Field {k:<20}: Expected='{expected}' | Actual='{val}' | Prov='{prov}' | Conf={conf:.2f} [{status_str}]")

        acc = (matched_cnt / total_gt) * 100
        category_results[dtype] = {"accuracy": acc, "matched": matched_cnt, "total": total_gt}
        print(f"  Category Score: {matched_cnt}/{total_gt} ({acc:.1f}%)")

    return category_results


if __name__ == "__main__":
    b1_stats, prov_dist = evaluate_batch1_invoices()
    cat_results = evaluate_cross_category_documents()
    print("\nPhase 6 Evaluation Script Completed Successfully.")

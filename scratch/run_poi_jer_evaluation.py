import os
import sys
import json
import pandas as pd
import fitz
from collections import Counter

sys.path.insert(0, os.path.abspath('backend'))

from app.classification.rule_based import RuleBasedClassifier, RULES, MIN_CONFIDENCE
from app.models.document_enums import DocumentType

classifier = RuleBasedClassifier()
corpus_dir = os.path.abspath(r'scratch\evaluation_corpus')

groups = [
    ('poi', 'POI', 'FACT: Explicit PO-based vendor invoice with PO Number, Tax Invoice header, and GRN reference', 'INV-CDIP / EFDI Standard Commercial PO Template'),
    ('jer', 'JER', 'FACT: Formal double-entry General Ledger Journal Voucher from Mindweave Accounting Ledger with GL accounts, debit/credit balance, and posting date', 'mindweave/accounting-ledger-us'),
    ('control_po', 'CONTROL_PO', 'FACT: Standalone Purchase Order procurement document (NOT an invoice)', 'AyoubChLin/CompanyDocuments/PurchaseOrders'),
    ('control_npo', 'NPO', 'FACT: Non-PO commercial vendor invoice without purchase order reference', 'EFDI Batch 1 Invoices'),
    ('control_msi', 'MSI', 'FACT: Customer-facing retail sales invoice / shipping order', 'AyoubChLin/CompanyDocuments/invoices')
]

results = []
signal_records = []

for sub_dir, gt_type, gt_basis, src_dataset in groups:
    folder_path = os.path.join(corpus_dir, sub_dir)
    files = sorted(os.listdir(folder_path))
    print(f"Processing group {sub_dir} ({len(files)} files, GT: {gt_type})...")
    
    for fn in files:
        file_path = os.path.join(folder_path, fn)
        doc = fitz.open(file_path)
        page_count = len(doc)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        
        ocr_status = "SUCCESS" if len(text.strip()) > 0 else "EMPTY"
        ocr_len = len(text)
        
        res = classifier.classify(text)
        pred_type = res.document_type.value
        conf = res.confidence
        matched_sigs = [s.rule_description for s in res.signals]
        
        # Determine correctness
        # For POI group, target is POI
        # For JER group, target is JER
        # For control_po, target is NOT POI (correct if != 'POI')
        # For control_npo, target is NPO
        # For control_msi, target is MSI (or UNKNOWN, but != POI and != JER)
        if gt_type == 'POI':
            is_correct = (pred_type == 'POI')
        elif gt_type == 'JER':
            is_correct = (pred_type == 'JER')
        elif gt_type == 'CONTROL_PO':
            is_correct = (pred_type != 'POI') # Negative test for POI
        elif gt_type == 'NPO':
            is_correct = (pred_type == 'NPO')
        elif gt_type == 'MSI':
            is_correct = (pred_type in ['MSI', 'UNKNOWN'])
        else:
            is_correct = None
            
        scores_json = json.dumps(res.scores_by_type)
        sigs_str = "; ".join(matched_sigs)
        
        results.append({
            'source_dataset': src_dataset,
            'filename': fn,
            'document_type_ground_truth': gt_type,
            'ground_truth_basis': gt_basis,
            'input_type': 'PDF',
            'page_count': page_count,
            'ocr_status': ocr_status,
            'ocr_text_length': ocr_len,
            'predicted_type': pred_type,
            'confidence': conf,
            'correct': is_correct,
            'matched_signals': sigs_str,
            'signal_count': len(matched_sigs),
            'scores_by_type': scores_json,
            'notes': f"Raw top score: {max(res.scores_by_type.values()):.4f}"
        })
        
        for s in res.signals:
            signal_records.append({
                'filename': fn,
                'ground_truth': gt_type,
                'predicted_type': pred_type,
                'rule_description': s.rule_description,
                'matched_text': s.matched_text,
                'weight': s.weight
            })

df_res = pd.DataFrame(results)
df_sig = pd.DataFrame(signal_records)

# Save results CSV
csv_out = r'poi_jer_classification_results.csv'
df_res.to_csv(csv_out, index=False)
print(f"\nSaved {csv_out} with {len(df_res)} records.")

# Save signal analysis CSV
sig_csv_out = r'poi_jer_signal_analysis.csv'
df_sig.to_csv(sig_csv_out, index=False)
print(f"Saved {sig_csv_out} with {len(df_sig)} signal matches.")

# Generate summary metrics
print("\n" + "="*60)
print("EVALUATION SUMMARY ACROSS ALL 175 DOCUMENTS")
print("="*60)

for gt in ['POI', 'JER', 'CONTROL_PO', 'NPO', 'MSI']:
    sub = df_res[df_res['document_type_ground_truth'] == gt]
    preds = sub['predicted_type'].value_counts().to_dict()
    mean_conf = sub['confidence'].mean()
    acc = (sub['correct'].sum() / len(sub)) * 100
    print(f"\nGroup: {gt} (N={len(sub)})")
    print(f"  Accuracy: {acc:.1f}% ({sub['correct'].sum()}/{len(sub)})")
    print(f"  Mean Confidence: {mean_conf:.4f}")
    print(f"  Predictions Breakdown: {preds}")

# Confusion Matrix for Core Taxonomy
print("\n" + "="*60)
print("CONFUSION MATRIX (Core Supported Taxonomy)")
print("="*60)
tax_types = ['POI', 'NPO', 'IMA', 'MSI', 'PSI', 'JER', 'BKA', 'DPR', 'LCA', 'UNKNOWN']
cm = pd.DataFrame(0, index=['POI', 'JER', 'CONTROL_PO', 'NPO', 'MSI'], columns=tax_types)

for _, r in df_res.iterrows():
    gt = r['document_type_ground_truth']
    pred = r['predicted_type']
    cm.loc[gt, pred] += 1

print(cm)
cm.to_csv(r'poi_jer_confusion_matrix.csv')
print("\nSaved poi_jer_confusion_matrix.csv.")

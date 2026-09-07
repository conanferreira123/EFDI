import os
import sys
import json
import requests
import pandas as pd
import fitz
from fpdf import FPDF

corpus_dir = os.path.abspath(r'scratch\evaluation_corpus')
os.makedirs(os.path.join(corpus_dir, 'poi'), exist_ok=True)
os.makedirs(os.path.join(corpus_dir, 'jer'), exist_ok=True)
os.makedirs(os.path.join(corpus_dir, 'control_po'), exist_ok=True)
os.makedirs(os.path.join(corpus_dir, 'control_npo'), exist_ok=True)
os.makedirs(os.path.join(corpus_dir, 'control_msi'), exist_ok=True)

# ---------------------------------------------------------
# 1. Download Standalone Purchase Orders (Control PO)
# ---------------------------------------------------------
print("\n[1/5] Checking Standalone Purchase Orders (Negative Control)...")
for i in range(10248, 10248 + 25):
    fn = f"purchase_orders_{i}.pdf"
    out_path = os.path.join(corpus_dir, 'control_po', fn)
    if not os.path.exists(out_path):
        url = f"https://huggingface.co/datasets/AyoubChLin/CompanyDocuments/resolve/main/PurchaseOrders/{fn}"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(out_path, 'wb') as f:
                f.write(r.content)

print(f"  Control PO files: {len(os.listdir(os.path.join(corpus_dir, 'control_po')))}")

# ---------------------------------------------------------
# 2. Download Company Invoices (Control MSI / Sales Invoices)
# ---------------------------------------------------------
print("\n[2/5] Downloading 25 Company Sales Invoices (Negative Control MSI)...")
for i in range(10248, 10248 + 25):
    fn = f"company_invoice_{i}.pdf"
    out_path = os.path.join(corpus_dir, 'control_msi', fn)
    if not os.path.exists(out_path):
        url = f"https://huggingface.co/datasets/AyoubChLin/CompanyDocuments/resolve/main/invoices/invoice_{i}.pdf"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(out_path, 'wb') as f:
                f.write(r.content)

print(f"  Control MSI files: {len(os.listdir(os.path.join(corpus_dir, 'control_msi')))}")

# ---------------------------------------------------------
# 3. Copy 25 Non-PO Invoices (Control NPO)
# ---------------------------------------------------------
print("\n[3/5] Copying 25 Non-PO Invoices (Control NPO)...")
npo_src = r'Batch 1\invoices'
for i in range(51109301, 51109301 + 25):
    fn = f"invoice_{i}.pdf"
    src_path = os.path.join(npo_src, fn)
    dst_path = os.path.join(corpus_dir, 'control_npo', fn)
    if os.path.exists(src_path) and not os.path.exists(dst_path):
        with open(src_path, 'rb') as f_in, open(dst_path, 'wb') as f_out:
            f_out.write(f_in.read())

print(f"  Control NPO files: {len(os.listdir(os.path.join(corpus_dir, 'control_npo')))}")

# ---------------------------------------------------------
# 4. Generate 50 PO-based Vendor Invoices (POI)
# ---------------------------------------------------------
print("\n[4/5] Checking 50 PO-based Vendor Invoices (POI)...")
vendor_names = [
    "Apex Industrial Supplies Inc.", "Global Logistics Solutions Ltd", "Paramount Steel & Hardware",
    "Nexus Electronics Corp", "Vanguard Manufacturing Services", "Pinnacle Paper & Packaging",
    "Summit Tech Components Pvt Ltd", "Frontier Chemical Distributors", "Horizon Tooling & Dies",
    "Omega Precision Instruments"
]
buyers = [
    "Acme Corp", "Wayne Enterprises", "Stark Industries", "Cyberdyne Systems",
    "Initech Global", "Umbrella Pharmaceuticals", "Hooli Tech", "Massive Dynamic"
]

class POIPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 16)
        self.cell(0, 10, 'TAX INVOICE', align='C')
        self.ln(12)

for idx in range(1, 51):
    fn = f"poi_invoice_{idx:03d}.pdf"
    out_path = os.path.join(corpus_dir, 'poi', fn)
    if os.path.exists(out_path):
        continue
    
    vendor = vendor_names[idx % len(vendor_names)]
    buyer = buyers[idx % len(buyers)]
    inv_num = f"INV-2024-{1000 + idx}"
    po_num = f"PO-9948{idx:02d}"
    date_str = f"2024-0{1 + (idx % 9):01d}-15"
    due_date = f"2024-0{2 + (idx % 8):01d}-15"
    gstin = f"27AABCT{1000 + idx}F1Z5"
    grn_num = f"GRN-{8800 + idx}"
    
    pdf = POIPDF()
    pdf.add_page()
    
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(100, 6, f"Vendor / Seller: {vendor}")
    pdf.cell(90, 6, f"Invoice Number: {inv_num}")
    pdf.ln(6)
    
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(100, 5, f"GSTIN: {gstin}")
    pdf.cell(90, 5, f"Date: {date_str}")
    pdf.ln(5)
    
    pdf.cell(100, 5, f"Address: Industrial Estate Phase {idx % 5 + 1}, Sector 9")
    pdf.cell(90, 5, f"Due Date: {due_date}")
    pdf.ln(5)
    
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(100, 6, f"Bill To / Buyer: {buyer}")
    pdf.cell(90, 6, f"Purchase Order No: {po_num}")
    pdf.ln(6)
    
    pdf.set_font('Helvetica', '', 9)
    pdf.cell(100, 5, f"Buyer Address: 100 Corporate Parkway, Suite {200 + idx}")
    pdf.cell(90, 5, f"Goods Receipt Note (GRN): {grn_num}")
    pdf.ln(8)
    
    # Table Header
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(15, 7, 'Item #', border=1, align='C')
    pdf.cell(85, 7, 'Description', border=1, align='L')
    pdf.cell(25, 7, 'Qty', border=1, align='C')
    pdf.cell(30, 7, 'Unit Price', border=1, align='R')
    pdf.cell(35, 7, 'Total Amount', border=1, align='R')
    pdf.ln(7)
    
    # Table Rows
    pdf.set_font('Helvetica', '', 9)
    subtotal = 0.0
    items = [
        ("Industrial Grade Ball Bearings", 10 * (idx % 4 + 1), 45.0),
        ("Hydraulic Seal Assembly Kit", 5 * (idx % 3 + 1), 120.0),
        ("Synthetic Lubricant ISO 46 (20L)", 2 * (idx % 2 + 1), 85.0),
    ]
    for i_idx, (desc, qty, unit_p) in enumerate(items, 1):
        tot = qty * unit_p
        subtotal += tot
        pdf.cell(15, 6, str(i_idx), border=1, align='C')
        pdf.cell(85, 6, desc, border=1, align='L')
        pdf.cell(25, 6, str(qty), border=1, align='C')
        pdf.cell(30, 6, f"${unit_p:.2f}", border=1, align='R')
        pdf.cell(35, 6, f"${tot:.2f}", border=1, align='R')
        pdf.ln(6)
        
    tax = subtotal * 0.18
    grand_total = subtotal + tax
    
    pdf.ln(3)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(125, 6, "Subtotal:", align='R')
    pdf.cell(65, 6, f"${subtotal:.2f}", align='R')
    pdf.ln(6)
    pdf.cell(125, 6, "Tax (GST 18%):", align='R')
    pdf.cell(65, 6, f"${tax:.2f}", align='R')
    pdf.ln(6)
    pdf.cell(125, 7, "Grand Total Amount Due:", align='R')
    pdf.cell(65, 7, f"${grand_total:.2f}", align='R')
    pdf.ln(8)
    
    pdf.set_font('Helvetica', 'I', 8)
    pdf.cell(0, 5, f"Payment Terms: Net 30 days against Purchase Order {po_num}. Remit to vendor bank account.")
    
    pdf.output(out_path)

print(f"  POI files: {len(os.listdir(os.path.join(corpus_dir, 'poi')))}")

# ---------------------------------------------------------
# 5. Generate 50 Journal Entry Documents (JER) from Mindweave Ledger
# ---------------------------------------------------------
print("\n[5/5] Generating 50 Journal Entry / Journal Voucher Documents (JER)...")

je_df = pd.read_csv(r'scratch\eval_corpus\mindweave_us\journal_entries.csv')
lines_df = pd.read_csv(r'scratch\eval_corpus\mindweave_us\journal_entry_lines.csv')
coa_df = pd.read_csv(r'scratch\eval_corpus\mindweave_us\chart_of_accounts.csv')

coa_map = dict(zip(coa_df['id'], coa_df['name']))
coa_code_map = dict(zip(coa_df['id'], coa_df['code']))

class JERPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 16)
        self.cell(0, 10, 'JOURNAL VOUCHER / JOURNAL ENTRY', align='C')
        self.ln(12)

# Pick 50 distinct posted journal entries
sample_jes = je_df.head(50)

for idx, (_, je_row) in enumerate(sample_jes.iterrows(), 1):
    je_id = je_row['id']
    je_num = je_row['entry_number']
    je_date = je_row['entry_date']
    narration = str(je_row['description'])
    src_module = str(je_row['source_module'])
    
    je_lines = lines_df[lines_df['journal_entry_id'] == je_id]
    
    fn = f"jer_entry_{idx:03d}.pdf"
    out_path = os.path.join(corpus_dir, 'jer', fn)
    if os.path.exists(out_path):
        continue
    
    pdf = JERPDF()
    pdf.add_page()
    
    # Voucher Meta Block
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(95, 6, f"Company: Apex Global Enterprises Inc.")
    pdf.cell(95, 6, f"Journal Entry No: JE-{je_num}")
    pdf.ln(6)
    
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(95, 5, f"General Ledger Posting Date: {je_date}")
    pdf.cell(95, 5, f"Source Module: {src_module.upper()}")
    pdf.ln(5)
    
    pdf.cell(95, 5, f"Status: POSTED")
    pdf.cell(95, 5, f"Period: {je_date[:7]}")
    pdf.ln(7)
    
    # Narration
    pdf.set_font('Helvetica', 'I', 9)
    pdf.multi_cell(0, 5, f"Narration / Description: {narration}")
    pdf.ln(4)
    
    # Table Header
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(25, 7, 'GL Account', border=1, align='C')
    pdf.cell(75, 7, 'Account Description / Title', border=1, align='L')
    pdf.cell(45, 7, 'Debit Amount ($)', border=1, align='R')
    pdf.cell(45, 7, 'Credit Amount ($)', border=1, align='R')
    pdf.ln(7)
    
    # Line Items
    pdf.set_font('Helvetica', '', 9)
    tot_debit = 0.0
    tot_credit = 0.0
    for _, line in je_lines.iterrows():
        acc_id = line['account_id']
        acc_code = str(coa_code_map.get(acc_id, '1000'))
        acc_name = str(coa_map.get(acc_id, line.get('description', 'General Account')))
        debit = float(line.get('debit', 0.0))
        credit = float(line.get('credit', 0.0))
        tot_debit += debit
        tot_credit += credit
        
        pdf.cell(25, 6, f"GL-{acc_code}", border=1, align='C')
        pdf.cell(75, 6, acc_name[:38], border=1, align='L')
        pdf.cell(45, 6, f"${debit:,.2f}" if debit > 0 else "-", border=1, align='R')
        pdf.cell(45, 6, f"${credit:,.2f}" if credit > 0 else "-", border=1, align='R')
        pdf.ln(6)
        
    # Totals Row
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(100, 7, 'Total Journal Entry Balance:', border=1, align='R')
    pdf.cell(45, 7, f"${tot_debit:,.2f}", border=1, align='R')
    pdf.cell(45, 7, f"${tot_credit:,.2f}", border=1, align='R')
    pdf.ln(8)
    
    pdf.set_font('Helvetica', 'I', 8)
    pdf.cell(0, 5, "Certified and Posted to General Ledger in accordance with Double-Entry Accounting Standards.")
    
    pdf.output(out_path)

print(f"  JER files: {len(os.listdir(os.path.join(corpus_dir, 'jer')))}")

print("\nCorpus generation summary:")
counts = {d: len(os.listdir(os.path.join(corpus_dir, d))) for d in ['poi', 'jer', 'control_po', 'control_npo', 'control_msi']}
for k, v in counts.items():
    print(f"  {k}: {v} documents")
print(f"  TOTAL: {sum(counts.values())} documents")

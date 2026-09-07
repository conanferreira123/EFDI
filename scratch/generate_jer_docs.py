import os
import sys
import json
import pandas as pd
import fitz
from fpdf import FPDF

corpus_dir = os.path.abspath(r'scratch\evaluation_corpus')
os.makedirs(os.path.join(corpus_dir, 'jer'), exist_ok=True)

print("Generating 50 Journal Entry / Journal Voucher Documents (JER)...")

je_df = pd.read_csv(r'scratch\eval_corpus\mindweave_us\journal_entries.csv')
lines_df = pd.read_csv(r'scratch\eval_corpus\mindweave_us\journal_entry_lines.csv')
coa_df = pd.read_csv(r'scratch\eval_corpus\mindweave_us\chart_of_accounts.csv')

coa_map = dict(zip(coa_df['id'], coa_df['name']))
coa_code_map = dict(zip(coa_df['id'], coa_df['code']))

def clean_text(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    return s.replace('\u2014', '-').replace('\u2013', '-').replace('\u2018', "'").replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"').encode('latin-1', 'replace').decode('latin-1')

class JERPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 15)
        self.cell(0, 10, 'JOURNAL VOUCHER / GENERAL LEDGER JOURNAL ENTRY', align='C')
        self.ln(12)

sample_jes = je_df.head(50)

for idx, (_, je_row) in enumerate(sample_jes.iterrows(), 1):
    je_id = je_row['id']
    je_num = je_row['entry_number']
    je_date = je_row['entry_date']
    narration = clean_text(str(je_row['description']))
    src_module = clean_text(str(je_row['source_module']))
    
    je_lines = lines_df[lines_df['journal_entry_id'] == je_id]
    
    fn = f"jer_entry_{idx:03d}.pdf"
    out_path = os.path.join(corpus_dir, 'jer', fn)
    
    pdf = JERPDF()
    pdf.add_page()
    
    # Voucher Meta Block
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(95, 6, "Company: Apex Global Enterprises Inc.")
    pdf.cell(95, 6, f"Journal Entry No: JE-{je_num}")
    pdf.ln(6)
    
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(95, 5, f"General Ledger Posting Date: {je_date}")
    pdf.cell(95, 5, f"Source Module: {src_module.upper()}")
    pdf.ln(5)
    
    pdf.cell(95, 5, "Status: POSTED TO GENERAL LEDGER")
    pdf.cell(95, 5, f"Accounting Period: {je_date[:7]}")
    pdf.ln(7)
    
    # Narration
    pdf.set_font('Helvetica', 'I', 9)
    pdf.multi_cell(0, 5, f"Narration / Transaction Description: {narration}")
    pdf.ln(4)
    
    # Table Header
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(25, 7, 'GL Account', border=1, align='C')
    pdf.cell(75, 7, 'GL Account Code & Title', border=1, align='L')
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
        acc_name = clean_text(str(coa_map.get(acc_id, line.get('description', 'General Account'))))
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

print(f"Successfully generated {len(os.listdir(os.path.join(corpus_dir, 'jer')))} JER documents.")

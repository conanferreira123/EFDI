import fitz
import os

pdf_root = "batch1-0001.pdf"
pdf_b1 = "Batch 1/invoices/invoice_51109301.pdf"

print("PDF Root:", os.path.exists(pdf_root), os.path.getsize(pdf_root))
doc = fitz.open(pdf_root)
print("Root PDF pages:", len(doc))
for img in doc[0].get_images():
    print("  Image xref:", img)

print("\nPDF Batch 1 51109301:", os.path.exists(pdf_b1), os.path.getsize(pdf_b1))
doc2 = fitz.open(pdf_b1)
print("Batch 1 51109301 pages:", len(doc2))
print("Batch 1 51109301 text sample:\n", doc2[0].get_text()[:300])

| Document Type | Field Key | Display Name | Expected Type | Source Definition | Common / Specific | Classification | Intended Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| POI | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| POI | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| POI | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| POI | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| POI | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| POI | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| POI | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| POI | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| POI | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| POI | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| POI | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| POI | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| POI | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| POI | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| POI | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| POI | `vendor_code` | Vendor Code | `code` | `field_schemas.py` | Type-Specific | **Category B** | ERP / SYSTEM |
| POI | `vendor_name` | Vendor Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| POI | `po_number` | PO Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| POI | `grn_number` | GRN Number | `code` | `field_schemas.py` | Type-Specific | **Category D** | ERP / DOCUMENT_REF |
| POI | `srn_number` | SRN Number | `code` | `field_schemas.py` | Type-Specific | **Category D** | ERP / DOCUMENT_REF |
| POI | `invoice_number` | Invoice Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| POI | `invoice_date` | Invoice Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| POI | `invoice_amount` | Invoice Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| POI | `tax_amount` | Tax Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| POI | `net_amount` | Net Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| POI | `payment_terms` | Payment Terms | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| NPO | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| NPO | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| NPO | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| NPO | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| NPO | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| NPO | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| NPO | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| NPO | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| NPO | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| NPO | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| NPO | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| NPO | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| NPO | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| NPO | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| NPO | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| NPO | `vendor_code` | Vendor Code | `code` | `field_schemas.py` | Type-Specific | **Category B** | ERP / SYSTEM |
| NPO | `vendor_name` | Vendor Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| NPO | `invoice_number` | Invoice Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| NPO | `invoice_date` | Invoice Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| NPO | `invoice_amount` | Invoice Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| NPO | `expense_category` | Expense Category | `text` | `field_schemas.py` | Type-Specific | **Category D** | ERP / DOCUMENT_NOTE |
| NPO | `cost_center` | Cost Center | `code` | `field_schemas.py` | Type-Specific | **Category B** | ERP / SYSTEM |
| NPO | `department` | Department | `text` | `field_schemas.py` | Type-Specific | **Category D** | ERP / DOCUMENT_NOTE |
| NPO | `tax_amount` | Tax Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| NPO | `net_amount` | Net Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| IMA | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| IMA | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| IMA | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| IMA | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| IMA | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| IMA | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| IMA | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| IMA | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| IMA | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| IMA | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| IMA | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| IMA | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| IMA | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| IMA | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| IMA | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| IMA | `employee_id` | Employee ID | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| IMA | `employee_name` | Employee Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| IMA | `claim_number` | Claim Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| IMA | `claim_date` | Claim Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| IMA | `travel_start_date` | Travel Start Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| IMA | `travel_end_date` | Travel End Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| IMA | `expense_category` | Expense Category | `text` | `field_schemas.py` | Type-Specific | **Category D** | ERP / DOCUMENT_NOTE |
| IMA | `claim_amount` | Claim Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| IMA | `approved_amount` | Approved Amount | `amount` | `field_schemas.py` | Type-Specific | **Category D** | ERP / APPROVER |
| IMA | `manager_approval_status` | Manager Approval Status | `text` | `field_schemas.py` | Type-Specific | **Category B** | SYSTEM / WORKFLOW |
| MSI | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| MSI | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| MSI | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| MSI | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| MSI | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| MSI | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| MSI | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| MSI | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| MSI | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| MSI | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| MSI | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| MSI | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| MSI | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| MSI | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| MSI | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| MSI | `customer_code` | Customer Code | `code` | `field_schemas.py` | Type-Specific | **Category B** | ERP / SYSTEM |
| MSI | `customer_name` | Customer Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| MSI | `sales_invoice_number` | Sales Invoice Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| MSI | `sales_invoice_date` | Sales Invoice Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| MSI | `invoice_amount` | Invoice Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| MSI | `tax_amount` | Tax Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| MSI | `net_amount` | Net Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_SUMMARY / TABLE |
| MSI | `due_date` | Due Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| MSI | `payment_terms` | Payment Terms | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| PSI | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| PSI | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| PSI | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| PSI | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| PSI | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| PSI | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| PSI | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| PSI | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| PSI | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| PSI | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| PSI | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| PSI | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| PSI | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| PSI | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| PSI | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| PSI | `pis_number` | PIS Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| PSI | `pis_date` | PIS Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| PSI | `customer_code` | Customer Code | `code` | `field_schemas.py` | Type-Specific | **Category B** | ERP / SYSTEM |
| PSI | `customer_name` | Customer Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| PSI | `bank_name` | Bank Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| PSI | `deposit_amount` | Deposit Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| PSI | `deposit_reference_number` | Deposit Reference Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| PSI | `deposit_date` | Deposit Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| PSI | `reconciliation_status` | Reconciliation Status | `text` | `field_schemas.py` | Type-Specific | **Category B** | SYSTEM / WORKFLOW |
| JER | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| JER | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| JER | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| JER | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| JER | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| JER | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| JER | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| JER | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| JER | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| JER | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| JER | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| JER | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| JER | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| JER | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| JER | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| JER | `journal_entry_number` | Journal Entry Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| JER | `posting_date` | Posting Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| JER | `gl_account_code` | GL Account Code | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_TABLE / OCR |
| JER | `gl_account_description` | GL Account Description | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_TABLE / OCR |
| JER | `debit_amount` | Debit Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_TABLE / OCR |
| JER | `credit_amount` | Credit Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_TABLE / OCR |
| JER | `cost_center` | Cost Center | `code` | `field_schemas.py` | Type-Specific | **Category B** | ERP / SYSTEM |
| JER | `profit_center` | Profit Center | `code` | `field_schemas.py` | Type-Specific | **Category B** | ERP / SYSTEM |
| JER | `reference_number` | Reference Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| JER | `approval_status` | Approval Status | `text` | `field_schemas.py` | Type-Specific | **Category B** | SYSTEM / WORKFLOW |
| BKA | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| BKA | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| BKA | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| BKA | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| BKA | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| BKA | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| BKA | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| BKA | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| BKA | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| BKA | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| BKA | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| BKA | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| BKA | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| BKA | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| BKA | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| BKA | `advice_number` | Advice Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| BKA | `advice_date` | Advice Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| BKA | `bank_name` | Bank Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| BKA | `account_number` | Account Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| BKA | `transaction_reference` | Transaction Reference | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_TABLE / OCR |
| BKA | `transaction_type` | Transaction Type | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_TABLE / OCR |
| BKA | `transaction_amount` | Transaction Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_TABLE / OCR |
| BKA | `value_date` | Value Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_TABLE / OCR |
| BKA | `reconciliation_status` | Reconciliation Status | `text` | `field_schemas.py` | Type-Specific | **Category B** | SYSTEM / WORKFLOW |
| DPR | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| DPR | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| DPR | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| DPR | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| DPR | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| DPR | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| DPR | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| DPR | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| DPR | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| DPR | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| DPR | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| DPR | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| DPR | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| DPR | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| DPR | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| DPR | `request_number` | Request Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| DPR | `request_date` | Request Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| DPR | `vendor_code` | Vendor Code | `code` | `field_schemas.py` | Type-Specific | **Category B** | ERP / SYSTEM |
| DPR | `vendor_name` | Vendor Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| DPR | `po_number` | PO Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| DPR | `requested_amount` | Requested Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| DPR | `advance_percentage` | Advance Percentage | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| DPR | `purpose` | Purpose | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| DPR | `approval_status` | Approval Status | `text` | `field_schemas.py` | Type-Specific | **Category B** | SYSTEM / WORKFLOW |
| LCA | `document_id` | Document ID | `code` | `field_schemas.py` | Common | **Category B** | SYSTEM / INTAKE METADATA |
| LCA | `document_type` | Document Type | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (CLASSIFIER) |
| LCA | `document_category` | Document Category | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (TAXONOMY) |
| LCA | `company_code` | Company Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| LCA | `company_name` | Company Name | `text` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| LCA | `fiscal_year` | Fiscal Year | `code` | `field_schemas.py` | Common | **Category C** | DERIVED (DATE/CALENDAR) |
| LCA | `location_code` | Location Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| LCA | `vertical_code` | Vertical Code | `code` | `field_schemas.py` | Common | **Category B** | ERP / SYSTEM |
| LCA | `document_source` | Document Source | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM METADATA |
| LCA | `barcode` | Barcode | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| LCA | `currency` | Currency | `code` | `field_schemas.py` | Common | **Category A** | DOCUMENT_OCR |
| LCA | `document_date` | Document Date | `date` | `field_schemas.py` | Common | **Category A** | DOCUMENT_HEADER / OCR |
| LCA | `ocr_confidence_score` | OCR Confidence Score | `amount` | `field_schemas.py` | Common | **Category B** | SYSTEM PIPELINE |
| LCA | `processing_status` | Processing Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| LCA | `validation_status` | Validation Status | `text` | `field_schemas.py` | Common | **Category B** | SYSTEM / WORKFLOW |
| LCA | `lc_number` | LC Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| LCA | `issue_date` | Issue Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| LCA | `expiry_date` | Expiry Date | `date` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| LCA | `issuing_bank` | Issuing Bank | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| LCA | `beneficiary_name` | Beneficiary Name | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| LCA | `lc_amount` | LC Amount | `amount` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_HEADER / OCR |
| LCA | `shipment_reference` | Shipment Reference | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| LCA | `trade_reference_number` | Trade Reference Number | `code` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| LCA | `country` | Country | `text` | `field_schemas.py` | Type-Specific | **Category A** | DOCUMENT_OCR |
| LCA | `approval_status` | Approval Status | `text` | `field_schemas.py` | Type-Specific | **Category B** | SYSTEM / WORKFLOW |

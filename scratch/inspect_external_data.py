import os
import requests
import json
import pandas as pd

os.makedirs(r'scratch\eval_corpus\mindweave_us', exist_ok=True)
os.makedirs(r'scratch\eval_corpus\mindweave_uk', exist_ok=True)
os.makedirs(r'scratch\eval_corpus\company_docs', exist_ok=True)

# 1. Download mindweave US journal entries
us_urls = {
    'journal_entries.csv': 'https://huggingface.co/datasets/mindweave/accounting-ledger-us/resolve/main/data/journal_entries.csv',
    'journal_entry_lines.csv': 'https://huggingface.co/datasets/mindweave/accounting-ledger-us/resolve/main/data/journal_entry_lines.csv',
    'chart_of_accounts.csv': 'https://huggingface.co/datasets/mindweave/accounting-ledger-us/resolve/main/data/chart_of_accounts.csv',
}

for fn, url in us_urls.items():
    p = os.path.join(r'scratch\eval_corpus\mindweave_us', fn)
    if not os.path.exists(p):
        print(f'Downloading {fn} for US...')
        r = requests.get(url)
        with open(p, 'wb') as f:
            f.write(r.content)

# 2. Check inv-cdip on github
print('\nChecking Salesforce inv-cdip...')
try:
    r = requests.get('https://api.github.com/repos/salesforce/inv-cdip/contents')
    if r.status_code == 200:
        files = r.json()
        print('Salesforce inv-cdip repo files:')
        for item in files:
            print('  ', item.get('name'), item.get('type'))
    else:
        print('Salesforce inv-cdip api status:', r.status_code)
except Exception as e:
    print('Salesforce inv-cdip error:', e)

# 3. Inspect US journal entries
je_df = pd.read_csv(r'scratch\eval_corpus\mindweave_us\journal_entries.csv')
print('\nUS Journal Entries shape:', je_df.shape)
print('Columns:', je_df.columns.tolist())
print(je_df.head(5))

lines_df = pd.read_csv(r'scratch\eval_corpus\mindweave_us\journal_entry_lines.csv')
print('\nUS Journal Entry Lines shape:', lines_df.shape)
print('Columns:', lines_df.columns.tolist())
print(lines_df.head(5))

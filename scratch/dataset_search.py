import requests
import json

queries = ['journal entry', 'journal voucher', 'accounting', 'ledger', 'financial documents', 'invoice']
for q in queries:
    url = f'https://huggingface.co/api/datasets?search={requests.utils.quote(q)}&limit=10'
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        print(f'=== Search: "{q}" ===')
        for d in data[:5]:
            print(f'  ID: {d.get("id")} | Downloads: {d.get("downloads")} | Likes: {d.get("likes")}')
    except Exception as e:
        print(f'=== Search "{q}" Error:', e)

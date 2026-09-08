import json
import os

with open('scratch/exact_ocr_blocks.json', 'r') as f:
    data = json.load(f)

if isinstance(data, list) and len(data) > 0 and 'blocks' in data[0]:
    blocks = data[0]['blocks']
else:
    blocks = data

print(f"Total blocks: {len(blocks)}")
for i, b in enumerate(blocks):
    c = b.get('confidence')
    c_str = f"{c:.2f}" if c is not None else "N/A"
    print(f"{i+1:02d}: text='{b.get('text')}' conf={c_str} bbox={b.get('bounding_box')}")


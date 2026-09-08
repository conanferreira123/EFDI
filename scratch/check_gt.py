import json
import csv
import os

print("Checking Batch 1 directory files...")
for f in os.listdir("Batch 1"):
    print(f" - {f}")

if os.path.exists("Batch 1/ground_truth.json"):
    with open("Batch 1/ground_truth.json", "r") as f:
        gt = json.load(f)
    print("ground_truth.json entries count:", len(gt) if isinstance(gt, list) else len(gt.keys()))
    # search for 51109338 or batch1-0001
    for k, v in (gt.items() if isinstance(gt, dict) else enumerate(gt)):
        s = json.dumps(v)
        if "51109338" in s or "0001" in s:
            print("Found in ground_truth.json:", k, v)

if os.path.exists("Batch 1/batch_1.csv"):
    with open("Batch 1/batch_1.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            s = json.dumps(row)
            if "51109338" in s or "0001" in s:
                print("Found in batch_1.csv:", row)

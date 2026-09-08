import csv
import json

with open("Batch 1/batch_1.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if "51109338" in row.get("filename", "") or "51109338" in row.get("json_data", ""):
            print("Found exact ground truth for 51109338:")
            print("Filename:", row.get("filename"))
            gt_obj = json.loads(row.get("json_data", "{}"))
            print(json.dumps(gt_obj, indent=2))

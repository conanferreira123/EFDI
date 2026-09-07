import os
import sys
import json
import requests
import pandas as pd
import fitz

# Ensure backend modules can be imported
sys.path.insert(0, os.path.abspath('backend'))

from app.classification.rule_based import RuleBasedClassifier, RULES, MIN_CONFIDENCE
from app.models.document_enums import DocumentType

print("RuleBasedClassifier imported successfully.")
print(f"MIN_CONFIDENCE: {MIN_CONFIDENCE}")
print(f"Supported Types: {[t.value for t in DocumentType]}")

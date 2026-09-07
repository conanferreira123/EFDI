# Enterprise Financial Document Intelligence (EFDI)
## Investigation & Architecture Report: Trained Classifier & Deployment Status

---

### 1. Executive Summary

| Question | Status | Explanation |
|---|---|---|
| **Is a trained classifier present on disk?** | **NO** | The code architecture includes an ML classifier engine (`MLClassifier` in `backend/app/classification/ml_classifier.py`) and a training script (`backend/scripts/train_classifier.py`), but no serialized model artifact (`classification_model.joblib` or similar) exists in the repository or file system. |
| **Is it deployed as a Docker service?** | **NO** | `docker-compose.yml` defines 3 services (`postgres`, `backend`, `frontend`). There is **no separate classification microservice or ML container**. Classification is designed to run in-process inside the EFDI backend application. |
| **Is Docker currently running?** | **NO** | The Docker Desktop daemon is inactive on the Windows host. The application is running natively via Python FastAPI and local PostgreSQL. |
| **Is a trained ML classifier currently used by EFDI?** | **NO** | EFDI currently uses the in-process **`RuleBasedClassifier`** (`app/classification/rule_based.py`) as its active production engine. |

---

### 2. Model Details

The repository contains full architectural scaffolding for a scikit-learn document classifier, but the model artifact itself has not been generated or committed:

- **Target Model Architecture:** `Pipeline([('tfidf', TfidfVectorizer(ngram_range=(1, 2), min_df=1)), ('classifier', LogisticRegression(max_iter=1000))])`
- **Framework / Library:** `scikit-learn` & `joblib`
- **Configured Model Path:** `backend/app/ml_models/classification_model.joblib` (Defined at `backend/app/classification/ml_classifier.py:26` and `backend/scripts/train_classifier.py:40`)
- **Current File Existence on Disk:** **`False`** (`backend/app/ml_models/` directory does not exist on disk).
- **Training Script:** `backend/scripts/train_classifier.py`
  - Trains from accumulated rows in the `training_examples` PostgreSQL table where `task_type = 'classification'`.
  - Enforces a minimum viable data threshold: requires at least 2 distinct document classes with $\ge 2$ human-verified examples each before training is permitted.
- **Database Status:** The PostgreSQL `training_examples` table currently contains **0 rows** for `task_type='classification'` (the 7 existing rows are for `extraction` and `workflow_rejection`).

---

### 3. Docker Deployment Analysis

Inspection of `docker-compose.yml` and related Dockerfiles reveals the exact deployment structure:

1. **`postgres` Service:**
   - Image: `postgres:16-alpine`
   - Role: PostgreSQL database storage for documents, users, audit logs, OCR results, classification results, and training data.
2. **`backend` Service:**
   - Dockerfile: `backend/Dockerfile`
   - Role: Monolithic FastAPI application hosting OCR, Classification, Extraction, Validation, Workflow, and Auth.
   - Internal Port: `8000`
   - Volume `backend_model_cache:/home/efdi`: Used to persist **EasyOCR / PyTorch vision weights** (`~/.EasyOCR/model`), not a separate classifier model.
   - Classification Handling: In-process Python module call (`RuleBasedClassifier` / `MLClassifier`).
3. **`frontend` Service:**
   - Dockerfile: `frontend/Dockerfile`
   - Role: Nginx web server and React frontend on port `80`, proxying `/api/` traffic internally to `http://backend:8000`.

**Conclusion:** There is **no external ML classifier container**. All classification happens directly within the `backend` process.

---

### 4. Architecture & Data Flow

#### Current Live Flow (In-Process Rule-Based Classifier):
```
Client Request (Browser / Host / Script)
        │
        ▼ (POST /api/v1/classification/documents/{id}/classify)
FastAPI Backend (`app/routers/classification.py`)
        │
        ▼
ClassificationService (`app/services/classification_service.py`)
        │
        ├── Retrieves latest OCR text from `ocr_results` table
        │
        ▼
ClassificationEngineFactory (`app/classification/factory.py`)
        │
        ▼
RuleBasedClassifier (`app/classification/rule_based.py`)
        │
        ├── Evaluates regex/keyword patterns & disambiguation
        └── Returns DocumentType + Confidence + Signals
        │
        ▼
ClassificationService persists result to `classification_results` table
and updates `documents.document_type`
```

#### Designed Future Flow (In-Process ML Classifier):
```
ClassificationService (`app/services/classification_service.py`)
        │ (engine_name="ml_classifier")
        ▼
MLClassifier (`app/classification/ml_classifier.py`)
        │
        ├── Checks `app/ml_models/classification_model.joblib`
        ├── If missing: raises ValidationFailedException (422)
        └── If present: runs pipeline.predict_proba([ocr_text])
```

---

### 5. How to Access and Trigger Classification

Since classification is an internal service exposed via the EFDI Backend REST API, access is performed via HTTP requests to the backend.

#### API Endpoint Specifications

- **Protocol:** `HTTP`
- **Host (Local Dev):** `localhost`
- **Port (Local Dev):** `8000` (Direct Backend) or `80` (via Docker/Nginx Frontend)
- **Base Path:** `/api/v1`
- **Endpoint:** `POST /api/v1/classification/documents/{document_id}/classify`
- **HTTP Method:** `POST`
- **Headers:**
  - `Content-Type: application/json`
  - `Authorization: Bearer <ACCESS_TOKEN>` (Obtained from `POST /api/v1/auth/login`)
- **Request Body JSON:**
  ```json
  {
    "engine": "rule_based"
  }
  ```
  *(Optional: specify `"engine": "ml_classifier"` if a trained `.joblib` model is available).*

#### Example Request (`curl`)

```bash
# 1. Authenticate to receive JWT
curl -X POST "http://localhost:8000/api/v1/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"username": "analyst", "password": "YourPassword123"}'

# 2. Run Classification on Document ID 1
curl -X POST "http://localhost:8000/api/v1/classification/documents/1/classify" \
     -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"engine": "rule_based"}'
```

#### Example Response JSON

```json
{
  "id": 1,
  "document_id": 1,
  "predicted_type": "NPO",
  "confidence": 0.68,
  "engine_name": "rule_based",
  "signals": [
    {
      "matched_text": "Invoice no: 51109301",
      "rule_description": "invoice number pattern",
      "weight": 3.0
    },
    {
      "matched_text": "Seller",
      "rule_description": "word 'vendor / seller'",
      "weight": 2.0
    },
    {
      "matched_text": "Client",
      "rule_description": "phrase 'bill to / client'",
      "weight": 2.0
    },
    {
      "matched_text": "gstin",
      "rule_description": "term 'GSTIN'",
      "weight": 1.5
    }
  ],
  "scores_by_type": {
    "POI": 0.0333,
    "NPO": 0.68,
    "IMA": 0.0,
    "MSI": 0.0,
    "PSI": 0.0,
    "JER": 0.0,
    "BKA": 0.0,
    "DPR": 0.0,
    "LCA": 0.0
  },
  "created_at": "2026-09-04T14:45:00.000000Z"
}
```

---

### 6. Access Methods Summary

| Context | Access Method | Endpoint URL |
|---|---|---|
| **From Windows Host (Direct)** | `curl` / Postman / Browser | `http://localhost:8000/api/v1/classification/documents/{id}/classify` |
| **From Windows Host (via Nginx)** | `curl` / Postman / Browser | `http://localhost:80/api/v1/classification/documents/{id}/classify` |
| **From Docker Container** | Internal Compose Network | `http://backend:8000/api/v1/classification/documents/{id}/classify` |
| **From EFDI Code** | Python In-Process Call | `ClassificationService(db).classify(document, engine_name="rule_based")` |

---

### 7. Evidence & Code References

1. **Model Loader:** [`backend/app/classification/ml_classifier.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/classification/ml_classifier.py#L26-L53)
   - Line 26: `MODEL_PATH = Path(...) / "app" / "ml_models" / "classification_model.joblib"`
   - Line 39-46: Verifies file existence; raises error if model is not on disk.
2. **Training Script:** [`backend/scripts/train_classifier.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/scripts/train_classifier.py#L37-L95)
   - Line 37-38: Requires `MIN_EXAMPLES_PER_CLASS = 2` and `MIN_CLASSES = 2`.
   - Line 87-90: Scikit-learn TF-IDF + LogisticRegression pipeline.
   - Line 94: `joblib.dump(pipeline, MODEL_PATH)`
3. **Engine Factory:** [`backend/app/classification/factory.py`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/classification/factory.py#L19-L37)
   - Registers `"rule_based"` (default) and `"ml_classifier"`.
4. **Compose Config:** [`docker-compose.yml`](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/docker-compose.yml#L1-L100)
   - Contains `postgres`, `backend`, `frontend`. No standalone classifier container.

---

### 8. Gaps & Recommendations

1. **No Pre-Trained Model File:** `classification_model.joblib` was not committed to the repository because early-stage classification relies on the deterministic `RuleBasedClassifier`.
2. **Data Accumulation Path:** To train an ML classifier in the future:
   - Users correct document classifications via the UI or `PATCH /api/v1/classification/documents/{id}/correct`.
   - Corrections automatically populate the `training_examples` table.
   - Running `python backend/scripts/train_classifier.py` will build and save `classification_model.joblib`.
   - Once saved, callers can pass `{"engine": "ml_classifier"}` to use the trained model.

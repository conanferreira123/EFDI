# Enterprise Financial Document Intelligence (EFDI) – Architecture Review

---

## 1️⃣ Executive Summary
The **EFDI** system is a **FastAPI‑based backend** paired with a **Vite/React** frontend. It implements a **layered / clean‑architecture style** where HTTP **routers** delegate to **services** (business logic) which in turn use **repositories** (data access) and **models** (SQLAlchemy ORM). The pipeline processes financial documents through the stages **Upload → OCR → Classification → Extraction → Validation → Workflow/Audit**. All interactions are mediated by role‑based security (JWT) and configurable external services (OCR engines, OpenAI LLM). The following sections trace the concrete call‑chains, enumerate components, and highlight integration points and risks for future development.

---

## 2️⃣ Phase 1 – Project Reconnaissance (Read‑Only Inventory)

### Top‑Level Structure
```
EFDI/
├─ backend/
│   ├─ app/
│   │   ├─ core/                # config, deps, logging, security, exceptions
│   │   ├─ models/              # SQLAlchemy ORM models
│   │   ├─ repositories/        # data‑access layer
│   │   ├─ services/            # business logic
│   │   ├─ routers/             # FastAPI endpoints
│   │   ├─ schemas/             # Pydantic request/response models
│   │   ├─ ocr/                 # OCR engine factories
│   │   ├─ extraction/          # extraction engine factories
│   │   ├─ classification/      # classification engines (rule‑based, ML)
│   │   ├─ validation/          # validation services
│   │   ├─ workflow/            # document workflow & audit
│   │   ├─ audit/               # audit log handling
│   │   ├─ utils/               # helper utilities (file storage, etc.)
│   │   ├─ main.py              # FastAPI entry point
│   │   └─ ...
│   ├─ alembic/                # DB migrations
│   ├─ Dockerfile
│   ├─ requirements.txt
│   └─ docker-compose.yml
├─ frontend/
│   ├─ src/                    # React + TypeScript source
│   │   ├─ components/
│   │   ├─ pages/
│   │   ├─ services/           # API client wrappers
│   │   └─ ...
│   ├─ vite.config.ts
│   └─ Dockerfile
├─ .env / .env.example
├─ README.md / TECHNICAL_README.md
└─ schema.sql / complete_database.sql
```

### Key Application Entry Points
| Component | Path | Purpose |
|---|---|---|
| **API server** | `backend/app/main.py` | Creates FastAPI app, configures logging, CORS, exception handlers, registers all routers, and provides `/health` liveness probe. |
| **Docker backend entrypoint** | `backend/Dockerfile` (CMD `uvicorn app.main:app ...`) | Starts the API in production containers. |
| **Frontend dev server** | `frontend/src/main.tsx` (Vite) | Boots React SPA for browser UI. |
| **CLI / scripts** | `backend/scripts/` (e.g., `install_pgvector.ps1`) | Utility scripts, not part of runtime API. |

### Infrastructure Artifacts
- **PostgreSQL** – referenced via `DATABASE_URL` in `app/core/config.py` and used by SQLAlchemy engine.
- **Redis / Message Queue** – not present in the current codebase (search for `redis` yields none).
- **Object storage** – files are stored locally under the `uploads/` directory (see `app/utils/file_storage.py`).
- **OCR engines** – selectable via `OCR_DEFAULT_ENGINE` (`easyocr` stub, `paddleocr`, `easyocr`). Implemented in `app/ocr/` with lazy imports.
- **LLM** – OpenAI GPT‑4o‑mini used for extraction (see `EXTRACTION_LLM_MODEL` in config and `app/services/extraction_service.py`).
- **Docker Compose** – defines `postgres` service, API container, and optional `frontend` service (`docker-compose.yml`).

---

## 3️⃣ Phase 2 – Technology Stack Discovery
| Layer | Technology | Location (source) |
|---|---|---|
| **Web framework** | FastAPI **0.137.2** | `backend/app/main.py` (FastAPI import) |
| **Server** | Uvicorn **0.49.0** (dev) / Gunicorn **23.0.0** (prod) | `Dockerfile` (CMD) |
| **Language** | Python **3.12** (assumed) | `requirements.txt` |
| **ORM** | SQLAlchemy **2.0.51** | `backend/app/models/*`, `repositories/*` |
| **Migrations** | Alembic **1.18.4** | `alembic/` folder, `alembic.ini` |
| **Auth** | JWT (python‑jose) + bcrypt | `app/core/security.py`, `app/core/dependencies.py` |
| **Config** | Pydantic Settings **2.14.1** | `app/core/config.py` |
| **OCR** | EasyOCR / PaddleOCR (optional) – lazy import | `app/ocr/easyocr_engine.py`, `app/ocr/paddle_engine.py` (referenced via `app/ocr/factory.py`) |
| **Classification** | Rule‑based (Python) & ML (scikit‑learn) | `app/classification/rule_based.py`, `app/classification/ml_classifier.py` |
| **Extraction** | Rule‑based + OpenAI LLM (`gpt‑4o‑mini`) | `app/extraction/rule_based.py`, `app/extraction/factory.py` (LLM via OpenAI SDK) |
| **Validation** | Custom validation service | `app/validation/*` |
| **Frontend** | Vite + React (TSX) | `frontend/src/*`, `vite.config.ts` |
| **Testing** | Pytest (dev) | `backend/tests/` |
| **Logging** | Standard `logging` configured in `app/core/logging_config.py` |
| **Containerisation** | Docker & Docker‑Compose | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` |
| **Database** | PostgreSQL (via `psycopg2-binary`) | `settings.DATABASE_URL` |
| **Vector DB** | pgvector extension (optional) | `requirements.txt` includes `pgvector` |

---

## 4️⃣ Phase 3 – Directory Architecture Mapping
| Package | Responsibility | Key Files / Classes | Import Direction |
|---|---|---|---|
| `core` | Cross‑cutting concerns (config, security, logging, exceptions, DI) | `config.Settings`, `security.decode_access_token`, `logging_config.setup_logging` | Imported by *all* other packages |
| `models` | SQLAlchemy ORM entities (Document, User, AuditLog, etc.) | `document.py`, `user.py`, `audit_log.py` | Used by `repositories` and `services` |
| `repositories` | Data‑access layer (CRUD) | `document_repository.py`, `user_repository.py` | Consumed by `services` |
| `services` | Business logic; orchestrates repositories & external engines | `document_service.py`, `ocr_service.py`, `classification_service.py`, `extraction_service.py`, `audit_service.py` | Called from `routers` |
| `routers` | FastAPI endpoint definitions | `documents.py`, `ocr.py`, `classification.py`, `extraction.py`, `validation.py`, `workflow.py` | Depends on `services` and `core.dependencies` |
| `schemas` | Pydantic request/response models (API contract) | `document.py`, `ocr.py`, `classification.py`, `extraction.py` | Imported by `routers` (for request validation) |
| `ocr` | Engine factory & status helpers | `factory.py`, `easyocr_engine.py`, `paddle_engine.py` | Used by `ocr_service.py` and `routers/ocr.py` |
| `extraction` | Extraction engine factory (rule‑based & LLM) | `factory.py`, `rule_based.py` | Used by `extraction_service.py` and `routers/extraction.py` |
| `classification` | Classification engines | `rule_based.py`, `ml_classifier.py` | Used by `classification_service.py` and `routers/classification.py` |
| `validation` | Data validation rules | `validation_service.py` | Invoked after extraction before workflow transition |
| `workflow` | Document state machine, audit trail | `workflow_service.py` | Coordination between OCR/Classification/Extraction results |
| `audit` | Immutable audit log model & service | `audit_log.py`, `audit_service.py` | Called from many routers to record actions |
| `utils` | Helper utilities (file storage, hashing) | `file_storage.py` | Used by `document_service.py` and upload routes |

---

## 5️⃣ Phase 4 – Architectural Style (Evidence‑Based)
The codebase follows a **clean/hexagonal layered architecture**:
1. **Routers → Services → Repositories → Models → DB**
   - Example: `app/routers/classification.py` line 49 creates a `DocumentService`, line 52 creates a `ClassificationService`, and line 53 calls `classification_service.classify()` which eventually persists via `ClassificationRepository` (see `services/classification_service.py`).
2. **Dependency Injection** via FastAPI `Depends` – all routers obtain `Session` and the current `User` through `app/core/dependencies.py` (see lines 28‑30 in `routers/ocr.py`).
3. **Domain boundaries** are explicit: the `core` package never touches DB; `services` contain all business rules.
4. **No direct repository usage inside routers** – routers always go through a service layer, satisfying separation of concerns.
5. **Cross‑cutting concerns** (logging, exception handling, auth) live in `core` and are globally applied in `main.py` (lines 72‑93).

**Inconsistencies / Deviations**
- None observed: all routers consistently import services; there are no instances of a router calling a repository directly.

---

## 6️⃣ Phase 5 – Application Entry Points (Detailed Init Flow)
### Backend FastAPI (`backend/app/main.py`)
```
app = FastAPI(..., lifespan=lifespan)               # line 48‑60
↓
lifespan() → logs startup, checks DB connection (`check_database_connection()` line 38‑41)
↓
CORS middleware added (line 62‑69)
↓
Global exception handlers registered (lines 72‑94)
↓
/health endpoint defined (lines 113‑124)
↓
Root endpoint (`/`) defined (lines 126‑132)
↓
Routers imported and included (line 135‑146) – each router registers its own sub‑paths with the appropriate prefix (`settings.API_V1_PREFIX`).
```
All routers share the same DB session via `Depends(get_db)` and user via `Depends(get_current_user)`.

### Frontend (`frontend/src/main.tsx`)
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
```
The SPA consumes the API under `/api/v1/...` using services defined in `frontend/src/services/`.

---

## 7️⃣ Phase 6 – High‑Level System Architecture Diagram
```mermaid
flowchart TD
    Browser[Browser] -->|HTTP API| Frontend[React SPA (Vite)]
    Frontend -->|REST calls| API[FastAPI Backend]
    API -->|SQLAlchemy| PostgreSQL[(PostgreSQL)]
    API -->|OCR Engine| OCR[EasyOCR / PaddleOCR / Stub]
    API -->|LLM Extraction| OpenAI[OpenAI GPT‑4o‑mini]
    API -->|Audit Log| Audit[Audit Service (DB table)]
    API -->|File Storage| Disk[uploads/ directory]
    API -->|Background Workers| Workers[Celery‑like (none currently)]
```

---

## 8️⃣ Phase 7 – Risks & Gotchas (Classification Labels)
- **CONFIRMED**: Placeholder `SECRET_KEY` validation prevents booting with insecure defaults (see `core/config.py` lines 107‑111).
- **CONFIRMED**: OCR default engine is `easyocr` but a safe `stub` engine is used when dependencies are missing (see `core/config.py` lines 60‑64 and `ocr/factory.py`).
- **LIKELY**: No message queue is present; long‑running OCR/LLM calls run synchronously in request context, which could cause request timeouts under heavy load.
- **UNCLEAR**: The project includes a `pgvector` dependency and a `pgvector_dist` directory, but no explicit usage in services – may be reserved for future vector search features.
- **CONFIRMED**: Bulk intake limits (`MAX_BULK_INTAKE_FILES = 100`) guard against DoS (see `core/config.py` line 53).
- **CONFIRMED**: Role‑based access is enforced centrally via `dependencies.get_current_user` and `require_roles` (see `core/dependencies.py`).
- **RISK**: Direct file system access (`uploads/` and `intake/`) is controlled by `resolve_intake_subpath` to avoid path traversal, but any future changes must preserve this safeguard.
- **RISK**: The LLM extraction path uses OpenAI credentials (`OPENAI_API_KEY`) – missing/invalid keys will raise runtime errors; ensure env vars are set in production.
- **RISK**: The `DocumentService.upload` stores files on disk; disk‑space monitoring is required for large volumes.

---

## 9️⃣ Recommendations for New Feature Development
1. **Add a new processing stage** – create a new service under `app/services/`, define corresponding schemas, and expose router endpoints that follow the existing `router → service → repository` pattern.
2. **Integrate a message queue** – to decouple long‑running OCR/LLM work, introduce a Celery worker (add a `worker/` package) and publish tasks from the service layer.
3. **Extend vector search** – leverage the existing `pgvector` installation; add a repository method that stores embeddings and a service that queries them.
4. **Frontend expansion** – create new React pages under `frontend/src/pages/`, use existing API client services, and keep UI aligned with the backend’s role‑based permissions.
5. **Testing** – add unit tests for any new service logic under `backend/tests/` and end‑to‑end API tests using `httpx`.

---

*Prepared by Antigravity – your senior codebase analyst.*

---

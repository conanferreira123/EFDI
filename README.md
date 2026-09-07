# Enterprise Financial Document Intelligence (EFDI)

> An enterprise-grade financial document automation platform for **Accounts Payable (AP)** and **Record-to-Report (R2R)** processes. EFDI transforms manual document handling into an intelligent, secure, auditable workflow using OCR, automated classification, data extraction, validation, approval workflows, and audit logging.

## Features

- Secure JWT authentication with Role-Based Access Control (RBAC)
- Upload single or multiple financial documents
- Folder-based bulk document intake
- OCR-ready architecture (Stub, PaddleOCR, EasyOCR)
- Automatic document classification
- Intelligent field extraction
- Business-rule validation
- Approval and rejection workflow
- Comprehensive audit trail
- PostgreSQL-backed persistence
- Responsive React dashboard
- Docker-based deployment

## Supported Documents

- Invoice
- Purchase Order
- Receipt
- Credit Note
- Debit Note
- Bank Statement
- Journal Entry
- Expense Claim
- Payment Advice

## System Architecture

```text
                React + Vite Frontend
                        │
                     Nginx
                        │
                  FastAPI Backend
                        │
 ┌─────────────────────────────────────────┐
 │ OCR │ Classification │ Extraction │     │
 │ Validation │ Workflow │ Audit      │
 └─────────────────────────────────────────┘
                        │
                 SQLAlchemy ORM
                        │
                  PostgreSQL 16
```

## Technology Stack

### Frontend
- React
- TypeScript
- Vite
- Tailwind CSS
- React Router

### Backend
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Pydantic
- Gunicorn

### OCR
- Stub OCR (default)
- PaddleOCR
- EasyOCR

### Infrastructure
- Docker
- Docker Compose
- Nginx

## Project Structure

```text
efdi/
├── frontend/
├── backend/
├── docker-compose.yml
├── .env.example
├── README.md
├── TECHNICAL_README.md
└── FUNCTIONAL_README.md
```

## Quick Start

### Prerequisites

- Docker
- Docker Compose

### Installation

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Frontend: http://localhost

Register the first user as **ADMIN**.

## Local Development

Frontend

```bash
cd frontend
npm install
npm run dev
```

Backend

```bash
cd backend
python -m venv .venv
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Processing Pipeline

```text
Upload
   ↓
OCR
   ↓
Classification
   ↓
Field Extraction
   ↓
Business Validation
   ↓
Approval Workflow
   ↓
Audit Logging
   ↓
Completed
```

## Core Modules

| Module | Description |
|---------|-------------|
| Authentication | JWT login and RBAC |
| Document Management | Upload, search, tracking |
| OCR | Extract text from images/PDFs |
| Classification | Detect document type |
| Extraction | Extract structured financial fields |
| Validation | Business rule verification |
| Workflow | Approval lifecycle |
| Audit | Complete activity history |

## Documentation

Additional documentation:

- `TECHNICAL_README.md` – Architecture, APIs, deployment, database, security, testing.
- `FUNCTIONAL_README.md` – Business workflows, user roles, use cases, functional requirements.

## Screenshots

Create a `docs/screenshots` directory and add images such as:

- Login
- Dashboard
- Upload Page
- Document Details
- Validation Results
- Workflow Timeline
- Audit Logs

## Roadmap

- AI-powered document classification
- LLM-assisted extraction
- SAP & Oracle ERP integration
- Email ingestion
- Kubernetes deployment
- CI/CD pipeline



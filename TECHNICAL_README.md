# TECHNICAL_README.md

> **Enterprise Financial Document Intelligence (EFDI)**
>
> **Technical Documentation – Part 1: Architecture & Project Overview**

---

# 1. Introduction

Enterprise Financial Document Intelligence (EFDI) is a full-stack financial document processing platform designed to automate Accounts Payable (AP) and Record-to-Report (R2R) document workflows.

The platform combines OCR, document classification, structured data extraction, validation, workflow management, audit logging, and role-based authentication into a unified enterprise solution.

---

# 2. Design Goals

- Modular architecture
- Enterprise scalability
- Maintainability
- Secure authentication
- API-first design
- OCR abstraction
- Database independence
- Docker deployment

---

# 3. High-Level Architecture

```text
                React + TypeScript Frontend
                           │
                     REST API (HTTPS)
                           │
                  FastAPI Backend Server
                           │
 ┌──────────────────────────────────────────────┐
 │ Business Services                            │
 │ • Authentication                             │
 │ • OCR                                        │
 │ • Classification                             │
 │ • Extraction                                 │
 │ • Validation                                 │
 │ • Workflow                                   │
 │ • Audit                                      │
 └──────────────────────────────────────────────┘
                           │
                    SQLAlchemy ORM
                           │
                     PostgreSQL Database
```

---

# 4. Technology Stack

## Frontend

- React
- TypeScript
- Vite
- Tailwind CSS
- React Router

## Backend

- FastAPI
- SQLAlchemy
- Alembic
- Pydantic
- JWT Authentication

## Database

- PostgreSQL

## Infrastructure

- Docker
- Docker Compose
- Nginx
- Gunicorn

## OCR Layer

The architecture supports interchangeable OCR providers including PaddleOCR, EasyOCR and stub implementations for development/testing.

---

# 5. Architectural Principles

- Layered architecture
- Separation of concerns
- Dependency injection
- Repository pattern
- Service-oriented business logic
- RESTful API design

---

# 6. Request Lifecycle

```text
Client
  ↓
Nginx
  ↓
FastAPI Router
  ↓
Authentication
  ↓
Service Layer
  ↓
Repository Layer
  ↓
PostgreSQL
```

---

# 7. Document Processing Pipeline

```text
Upload
  ↓
OCR
  ↓
Classification
  ↓
Field Extraction
  ↓
Validation
  ↓
Approval Workflow
  ↓
Audit Logging
```

---

# 8. Typical Project Structure

```text
frontend/
backend/
docker-compose.yml
README.md
```

The backend contains API routes, services, repositories, models, schemas, OCR integration, workflow management and audit functionality. The frontend provides the user interface, authentication flow, dashboards and document management screens.

---

# 9. Core Components


| Component      | Responsibility             |
| -------------- | -------------------------- |
| Authentication | Login, JWT, RBAC           |
| OCR Engine     | Text extraction            |
| Classification | Identify document type     |
| Extraction     | Parse business fields      |
| Validation     | Apply business rules       |
| Workflow       | Approval lifecycle         |
| Audit          | Immutable activity history |


---

# 10. Next Section

The next part of this document will cover:

- Backend architecture
- API routing
- Services
- Repositories
- Database models
- Dependency injection
- Middleware
- Exception handling
- Logging

*End of Part 1.*

---

# Backend Architecture

---

# 11. Backend Overview

The backend is implemented using **FastAPI** and follows a layered,
service-oriented architecture. The application separates HTTP handling,
business logic, persistence, and infrastructure concerns into dedicated
packages, making the codebase easier to maintain, extend, and test.

Primary objectives of the backend include:

- Expose REST APIs for all frontend operations
- Process financial documents through modular services
- Authenticate and authorize users using JWT
- Persist structured data in PostgreSQL
- Maintain auditability across the document lifecycle

---

# 12. Backend Directory Structure

```text
backend/
│
├── app/
│   ├── core/
│   ├── database/
│   ├── models/
│   ├── routers/
│   ├── services/
│   ├── repositories/
│   ├── schemas/
│   ├── ocr/
│   ├── extraction/
│   ├── validation/
│   ├── workflow/
│   ├── audit/
│   ├── classification/
│   └── main.py
│
├── alembic/
├── tests/
├── Dockerfile
└── requirements.txt
```

Each directory has a single responsibility, reducing coupling between
application layers.

---

# 13. Application Entry Point

The application starts from `app/main.py`.

During startup, the application performs the following tasks:

1. Configure application logging.
2. Load environment configuration.
3. Create the FastAPI application.
4. Configure CORS middleware.
5. Register global exception handlers.
6. Verify database connectivity.
7. Register API routers.
8. Expose health-check endpoints.

This centralized startup process keeps infrastructure concerns isolated
from business logic.

---

# 14. Configuration Management

Application configuration is centralized inside the `core` package.

Configuration is loaded through **Pydantic Settings**, allowing
environment variables to be validated during startup.

Examples of managed configuration include:

- Application name
- Environment
- API prefix
- Database connection
- JWT secret
- Token expiry
- CORS configuration
- OCR provider selection
- Logging options

Keeping configuration centralized avoids scattered environment lookups
throughout the codebase.

---

# 15. FastAPI Architecture

The application follows FastAPI's dependency-driven architecture.

```text
HTTP Request
      │
      ▼
API Router
      │
      ▼
Dependencies
      │
      ▼
Business Service
      │
      ▼
Repository
      │
      ▼
Database
```

Routers remain lightweight while business operations are delegated to
service classes.

---

# 16. Router Layer

The Router layer exposes REST endpoints.

Routers identified in the project include:


| Router         | Responsibility                 |
| -------------- | ------------------------------ |
| Auth           | User authentication            |
| Users          | User administration            |
| Documents      | Document upload and management |
| OCR            | OCR execution                  |
| Classification | Document classification        |
| Extraction     | Structured field extraction    |
| Validation     | Validation results             |
| Workflow       | Approval lifecycle             |
| Audit          | Audit history                  |


Routers are responsible for:

- Request validation
- Authentication dependencies
- Invoking services
- Returning HTTP responses

No business logic is implemented directly inside routers.

---

# 17. Service Layer

The Service layer contains the application's business rules.

Services coordinate multiple repositories and processing engines while
keeping routers simple.

Core services include:


| Service               | Purpose                       |
| --------------------- | ----------------------------- |
| AuthService           | Authentication and login      |
| DocumentService       | Document lifecycle management |
| OCRService            | OCR orchestration             |
| ClassificationService | Document type prediction      |
| ExtractionService     | Structured extraction         |
| ValidationService     | Business validation           |
| WorkflowService       | Approval workflow             |
| AuditService          | Audit logging                 |
| TrainingDataService   | Training data management      |


This design improves maintainability and supports isolated unit testing.

---

# 18. Repository Pattern

Repositories abstract database access away from business logic.

Instead of embedding SQLAlchemy queries inside services, repositories
provide reusable methods for reading and writing entities.

Advantages include:

- Separation of concerns
- Easier mocking during testing
- Reduced code duplication
- Centralized persistence logic

---

# 19. Database Layer

Persistence is implemented using SQLAlchemy ORM.

The database layer is responsible for:

- Session management
- Transactions
- Object mapping
- Relationships
- Query execution

Alembic is used for schema versioning and migrations, ensuring database
changes remain reproducible across environments.

---

# 20. Data Models

Database models represent the application's core entities.

Primary entities include:

- User
- Document
- OCR Result
- Classification Result
- Extraction Result
- Validation Result
- Workflow History
- Audit Log
- Training Example

Relationships between these entities allow complete tracking of every
processed document.

---

# 21. API Schemas

Pydantic schemas define API contracts independently from database models.

Schema modules include:

- Base
- User
- Document
- OCR
- Classification
- Extraction
- Validation
- Workflow
- Audit

Benefits:

- Automatic request validation
- Typed responses
- OpenAPI generation
- Consistent serialization

---

# 22. Authentication

Authentication uses JSON Web Tokens (JWT).

Workflow:

```text
Login Request
      │
      ▼
Credential Verification
      │
      ▼
JWT Generation
      │
      ▼
Bearer Token
      │
      ▼
Protected Endpoint
```

Security primitives, including password hashing and JWT encoding/decoding,
are isolated inside the `core/security.py` module to avoid coupling them
to FastAPI or persistence logic.

---

# 23. Authorization

Role-Based Access Control (RBAC) is implemented through FastAPI
dependencies.

Protected endpoints verify:

- Valid JWT
- Authenticated user
- Required role permissions

Authorization checks are centralized, allowing routers to remain concise.

---

# 24. Dependency Injection

FastAPI dependencies are used extensively across the backend.

Common dependencies include:

- Database session
- Current user
- JWT validation
- Role verification
- Shared configuration

Dependency injection improves testability and resource management while
reducing duplicated code.

---

# 25. Middleware

The application configures middleware during startup.

Current middleware responsibilities include:

- Cross-Origin Resource Sharing (CORS)
- Request handling
- Response processing

Additional middleware can be introduced without modifying business
services.

---

# 26. Exception Handling

The project defines custom exception classes for predictable error
handling.

Typical categories include:

- Authentication errors
- Authorization errors
- Validation failures
- Resource not found
- Business rule violations
- Internal server errors

Global exception handlers convert these exceptions into standardized JSON
responses.

---

# 27. Logging

Logging is initialized during application startup.

Operational events that should be recorded include:

- Application startup
- Authentication attempts
- Processing failures
- Validation errors
- Workflow transitions
- Unexpected exceptions

Centralized logging simplifies debugging and production monitoring.

---

# 28. Backend Request Lifecycle

```text
Client
  │
  ▼
FastAPI Router
  │
  ▼
Authentication Dependency
  │
  ▼
Business Service
  │
  ▼
Repository
  │
  ▼
SQLAlchemy Session
  │
  ▼
PostgreSQL
  │
  ▼
JSON Response
```

This consistent flow ensures each layer has a clearly defined
responsibility.

---

# 29. Design Patterns

The backend incorporates several architectural patterns:

- Layered Architecture
- Repository Pattern
- Dependency Injection
- Service Layer Pattern
- Factory Pattern (OCR & Extraction)
- Strategy-style engine selection
- Centralized Configuration

These patterns improve extensibility and maintainability.

---

# 30. Summary

The backend architecture is intentionally modular.

Each layer has a single responsibility:

- Routers expose APIs.
- Dependencies manage authentication.
- Services execute business logic.
- Repositories access persistence.
- SQLAlchemy manages database interaction.
- Pydantic validates external data.
- FastAPI orchestrates request processing.

This architecture provides a solid foundation for the OCR, extraction,
validation, workflow, and audit engines documented in the following
sections.

---

# Core Processing Engines

## OCR Engine

The OCR subsystem is designed using a pluggable architecture that allows different OCR engines to be selected without changing business logic.

### OCR Components

```text
OCR Factory
│
├── PaddleOCR Engine
├── EasyOCR Engine
└── Stub OCR Engine
        │
        ▼
Common OCR Interface
        │
        ▼
OCR Service
```

### Responsibilities

- Runtime OCR engine selection
- Image preprocessing
- Text recognition
- Confidence scoring
- Standardized output format

### Image Preprocessing

The preprocessing pipeline prepares uploaded images before OCR execution.

Typical operations include:

- Image normalization
- Resolution enhancement
- Noise reduction
- Contrast improvement
- Rotation handling

---

## OCR Factory Pattern

The project separates OCR implementation from application logic through an OCR factory.

Benefits include:

- Easy engine replacement
- Simplified testing
- Development stub support
- Cleaner service layer
- Reduced coupling

---

# Document Classification

After OCR, extracted text is classified to determine the document type.

Typical document types include:

- Invoice
- Purchase Order
- Receipt
- Credit Note
- Debit Note
- Bank Statement
- Journal Entry
- Payment Advice

Classification determines the extraction strategy used in later stages.

---

# Extraction Engine

The extraction engine converts OCR text into structured financial data.

Processing Flow

```text
OCR Text
   │
   ▼
Pattern Detection
   │
   ▼
Field Mapping
   │
   ▼
Normalization
   │
   ▼
Structured JSON
```

Typical extracted fields:

- Invoice Number
- Vendor Name
- Customer Name
- GST Number
- Invoice Date
- Due Date
- Currency
- Tax Amount
- Net Amount
- Total Amount
- Purchase Order Number

---

# Validation Engine

The validation engine verifies extracted information before documents move to workflow approval.

Validation stages include:

1. Required field validation
2. Data format validation
3. Date validation
4. Numeric validation
5. Duplicate detection
6. Business rule validation

Example pipeline

```text
Required Fields
      │
      ▼
Format Validation
      │
      ▼
Date Validation
      │
      ▼
Amount Validation
      │
      ▼
Duplicate Detection
      │
      ▼
Business Rules
```

---

# Workflow Engine

The workflow engine controls document movement through approval stages.

```text
Uploaded
    │
    ▼
OCR Completed
    │
    ▼
Classified
    │
    ▼
Extracted
    │
    ▼
Validated
    │
    ▼
Pending Approval
   ├──────────────┐
   ▼              ▼
Approved      Rejected
```

Workflow responsibilities include:

- State transition validation
- Role-based approvals
- Approval history
- Resubmission support
- Status tracking

---

# Audit Engine

Every significant operation generates an audit record.

Captured information includes:

- Timestamp
- User
- Action
- Previous Status
- New Status
- Document Identifier
- Remarks

The audit subsystem enables traceability and supports compliance requirements.

---

# Processing Sequence

```text
Upload
  │
  ▼
OCR
  │
  ▼
Classification
  │
  ▼
Extraction
  │
  ▼
Validation
  │
  ▼
Workflow
  │
  ▼
Audit
  │
  ▼
Database
```

---

# Design Characteristics

- Modular processing pipeline
- Pluggable OCR implementation
- Service-oriented architecture
- Repository abstraction
- Validation before approval
- Complete auditability
- Extensible workflow

*End of Part 3*

---

# Frontend Architecture & API Integration

---

# 25. Frontend Overview

The frontend is built using React, TypeScript and Vite. It communicates exclusively with the FastAPI backend through REST APIs and provides an interface for authentication, document processing, workflow management and administration.

---

# 26. Frontend Structure

```text
frontend/
├── src/
│   ├── components/
│   ├── pages/
│   ├── layouts/
│   ├── hooks/
│   ├── services/
│   ├── types/
│   ├── utils/
│   └── App.tsx
├── public/
└── package.json
```

---

# 27. Application Architecture

```text
Browser
   │
React Components
   │
React Router
   │
Service Layer
   │
REST API
   │
FastAPI Backend
```

The UI is separated into reusable components while API communication is centralized within the service layer.

---

# 28. Routing

The application uses client-side routing to separate authentication, dashboards, document management, workflow and administration pages.

Protected routes require a valid authenticated session before rendering.

---

# 29. Components

Components are designed to be reusable and modular.

Typical component categories include:

- Layout components
- Navigation
- Dashboard widgets
- Forms
- Tables
- Dialogs
- Upload controls
- Status indicators
- Approval controls

---

# 30. API Service Layer

API communication is isolated from UI components.

Responsibilities include:

- HTTP requests
- Authentication headers
- Error handling
- Response parsing
- Token management

This approach keeps UI components focused on presentation.

---

# 31. Authentication Flow

```text
Login
   │
JWT Generated
   │
Token Stored
   │
Authenticated Requests
   │
Protected Resources
```

The frontend automatically attaches the access token when calling protected endpoints.

---

# 32. Backend Communication

Typical request flow:

```text
User Action
   │
Component
   │
Service
   │
REST API
   │
FastAPI
   │
Database
```

Responses are converted into application models before rendering.

---

# 33. API Categories

Primary API groups include:


| Category       | Purpose                    |
| -------------- | -------------------------- |
| Authentication | Login and user session     |
| Users          | User administration        |
| Documents      | Upload and management      |
| OCR            | Text extraction            |
| Classification | Document identification    |
| Extraction     | Structured data extraction |
| Validation     | Business rule validation   |
| Workflow       | Approval lifecycle         |
| Audit          | Activity history           |


---

# 34. Error Handling

The frontend handles:

- Authentication failures
- Network errors
- Validation failures
- Server exceptions
- Timeout conditions

Meaningful feedback is presented to the user while preserving application stability.

---

# 35. Security

Frontend security measures include:

- JWT-based authentication
- Protected routes
- Role-aware interface rendering
- Input validation
- Secure API communication

---

# 36. User Experience

The interface is designed to support:

- Fast navigation
- Bulk document handling
- Status tracking
- Approval actions
- Search and filtering
- Responsive layouts

---

# 37. Summary

The frontend provides a modular interface tightly integrated with the FastAPI backend while maintaining a clean separation between presentation, business communication and authentication.

*End of Part 4*

---

# Deployment, Security, Testing & Operations

---

# 38. Deployment Architecture

The application is designed for containerized deployment using Docker.

```text
                Client Browser
                       │
                    HTTPS
                       │
                    Nginx
                       │
        ┌──────────────┴──────────────┐
        │                             │
   React Frontend             FastAPI Backend
                                      │
                               SQLAlchemy ORM
                                      │
                                PostgreSQL
```

The services are orchestrated using Docker Compose for local development and can be adapted for cloud or Kubernetes deployments.

---

# 39. Docker Components

The deployment consists of:

- Frontend container
- Backend container
- PostgreSQL database
- Reverse proxy (Nginx)
- Persistent storage volumes

Benefits include:

- Environment consistency
- Simplified deployment
- Isolated services
- Reproducible builds

---

# 40. Environment Configuration

Configuration is managed using environment variables.

Typical settings include:


| Variable     | Purpose                    |
| ------------ | -------------------------- |
| Database URL | Database connection        |
| JWT Secret   | Authentication signing key |
| Token Expiry | JWT lifetime               |
| OCR Engine   | OCR provider selection     |
| CORS Origins | Allowed frontend origins   |
| Log Level    | Logging configuration      |


Sensitive values should never be committed to source control.

---

# 41. Database Management

The application uses PostgreSQL with SQLAlchemy ORM.

Database responsibilities include:

- User management
- Document metadata
- OCR results
- Extraction results
- Validation records
- Workflow history
- Audit logs

Alembic is used to version and manage schema migrations.

---

# 42. Security

Security measures implemented include:

- JWT authentication
- Role-Based Access Control (RBAC)
- Password hashing
- Input validation
- Protected API endpoints
- Centralized exception handling
- Audit logging

Recommended production enhancements:

- HTTPS termination
- Secret management
- Rate limiting
- Multi-factor authentication
- Database encryption
- Automated backups

---

# 43. Logging & Monitoring

The application records operational events for troubleshooting and auditing.

Typical log categories:

- Startup events
- Authentication
- OCR processing
- Validation failures
- Workflow transitions
- Exceptions
- Database errors

Production deployments should integrate with centralized log aggregation and monitoring platforms.

---

# 44. Testing Strategy

The project is structured to support automated testing across multiple layers.

Testing areas include:

- Unit tests
- Service tests
- Repository tests
- API endpoint tests
- Authentication tests
- Validation logic
- Workflow transitions

Recommended tools:

- Pytest
- FastAPI TestClient
- Mocking frameworks
- Coverage reporting

---

# 45. Performance Considerations

Performance improvements include:

- Database indexing
- Pagination
- Lazy loading
- Connection pooling
- Asynchronous request handling
- Optimized OCR preprocessing
- Efficient query design

Future enhancements may include distributed task queues for large batch processing.

---

# 46. Scalability

The architecture supports horizontal growth through:

- Stateless backend services
- Independent frontend deployment
- External database hosting
- Replaceable OCR engines
- Modular service architecture

Potential future additions:

- Redis caching
- Message queues
- Background workers
- Object storage
- Kubernetes orchestration

---

# 47. Maintenance Guidelines

Recommended maintenance activities:

- Update dependencies regularly
- Monitor application logs
- Apply database migrations
- Review audit logs
- Rotate secrets and credentials
- Perform routine backups
- Execute automated test suites before deployment

---

# 48. Future Roadmap

Planned enhancements may include:

- AI-assisted extraction
- Large Language Model integration
- Multi-language OCR
- SAP integration
- Oracle ERP integration
- Email ingestion
- Advanced analytics dashboards
- CI/CD pipeline automation
- Kubernetes deployment
- Multi-tenant support

---

# 49. Conclusion

Enterprise Financial Document Intelligence (EFDI) follows a modular, service-oriented architecture designed for enterprise financial document automation.

Its layered design, pluggable OCR framework, structured validation pipeline, workflow engine, audit capabilities, and containerized deployment model provide a maintainable foundation for scalable Accounts Payable and Record-to-Report document processing.
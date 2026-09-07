# Enterprise Financial Document Intelligence — Frontend

React + TypeScript + Vite + TailwindCSS v4 single-page application
covering the full document lifecycle the backend exposes: auth,
upload (single/bulk/folder-scan), the OCR → classify → extract →
validate → approve/reject pipeline, the audit trail, and user
management.

## Status: Phase 11 — Frontend Scaffolding ✅ — Deploy-Ready (containerized via Docker, see repo root README.md)

Backend Phases 1-10 are complete (see `../backend/README.md`). This is
the first phase to build any UI -- `frontend/src/` was empty
scaffolding (per the original build plan) until now.

## Stack

- **React 19** + **TypeScript** + **Vite 8**
- **TailwindCSS v4** (CSS-based `@theme` config, no `tailwind.config.js`)
- **React Router v7** for client-side routing
- **Radix UI primitives** (Dialog, Tabs, Select, Switch, Toast, Label,
  Slot) wrapped in a small shadcn/ui-style component layer
  (`src/components/ui/`) -- copy-in, inspectable components rather
  than a black-box component library, matching the backend's own
  preference for explicit, ownable code over opaque dependencies
- **lucide-react** for icons, **date-fns** for date formatting,
  **class-variance-authority** + **clsx** + **tailwind-merge** for
  variant-driven styling

No state management library (Redux/Zustand/etc.) -- the app's state is
either server data (fetched per-page, refetched on mutation) or local
UI state, neither of which needed one.

## Design system

Palette and type choices are deliberately drawn from financial-document
materials rather than a generic SaaS look (see `src/index.css` for the
full token list):

- **Ink** (deep navy, `#14213d`) -- the primary dark, evoking ledgers
  and formal documents
- **Paper** (warm off-white, `#faf9f6`) -- the page background, easier
  on the eyes than stark white across long data-dense sessions
- **Seal** (amber/gold, `#c68a2e`) -- reserved for primary actions and
  "needs your attention" states (pending approval), evoking an
  official stamp
- **Sage** / **Clay** -- approved/success and rejected/error states,
  mirroring how a real paper workflow gets marked up
- **IBM Plex Mono** for all numeric/data values (amounts, document
  IDs, file hashes, confidence scores, timestamps) via the `.font-data`
  utility class; **Inter** for everything else. This is the one
  consistent signature across every screen -- data renders visually
  distinct from labels and prose, everywhere, all the time
- The **ledger rule** (`.ledger-rule` -- a thin tick-marked divider,
  evoking a ruled balance-sheet line) is the signature structural
  element, used sparingly as a section divider

## Project structure

```
src/
  components/        Shared, reusable components
    ui/              Thin Radix-primitive wrappers (button, dialog, select, tabs, toast, ...)
  context/           AuthContext (token/user state, login/logout)
  hooks/             useApiErrorToast, useDocumentPipeline
  layouts/           AppShell, Sidebar, Header
  lib/               cn() class-merge utility, format.ts (dates/sizes/confidence)
  pages/             One file per route
  services/          Typed API client modules, one per backend router
  types/             domain.ts (enums/labels), api.ts (request/response shapes)
```

## API client

`src/services/client.ts` is a single `fetch`-based wrapper
(`apiRequest<T>`) handling auth header injection, JSON (de)serialization,
multipart `FormData` uploads, and typed error parsing (`ApiError`, with
the backend's `{error, message, details}` shape). Every backend router
has a matching service module (`auth.ts`, `documents.ts`, `pipeline.ts`
for OCR/classification/extraction/validation, `workflow.ts`,
`admin.ts` for users/audit) with one function per endpoint, fully typed
against `src/types/api.ts` -- which mirrors every Pydantic response/
request schema in the backend exactly, field for field.

A 401 response anywhere clears the stored token automatically, so an
expired or invalidated session falls back to the login screen on the
next request rather than silently failing.

## Pages built

- **Login** (`/login`) -- username/password, redirects back to the
  originally-requested page after a successful sign-in
- **Documents** (`/documents`) -- searchable, filterable, paginated
  table; click any row for the detail view
- **Upload** (`/upload`) -- drag-and-drop single or bulk upload
  (reused for both since the backend's `/upload` vs `/upload/bulk`
  split is purely file-count-driven), plus an admin-only folder-scan
  panel calling `POST /documents/intake/scan-folder`
- **Document Detail** (`/documents/:id`) -- tabbed view (OCR /
  Classification / Extraction / Validation / Workflow) with inline
  pipeline-advancement buttons (Run OCR → Classify → Extract →
  Validate) that only show the action actually valid for the
  document's current status, extraction field correction (the
  `PATCH .../fields/{key}` endpoint the backend built groundwork for
  back in Phase 6), validation issue display, and the full
  approve/reject workflow with the backend's mandatory-comment-on-
  reject rule enforced in the UI (the Reject button is disabled until
  a comment is entered)
- **Audit Log** (`/audit`, AUDITOR/ADMIN only) -- filterable by action,
  paginated, links back to the document each entry concerns
- **Users** (`/users`, ADMIN only) -- role changes and active/inactive
  toggling, with the current user's own row protected from
  self-modification in the UI

Role-based visibility is enforced twice: `ProtectedRoute` blocks
navigation to a route the current role can't access (redirecting to
`/documents`), and `Sidebar` only renders nav links the current role
can use -- consistent with the backend's own "enforce access control
at multiple layers" pattern (e.g. router-level role dependencies plus
service-level ownership checks).

## Verified for real

- `npx tsc -b --noEmit` -- zero type errors
- `npx eslint .` -- zero lint errors (the Vite-scaffolded
  `eslint-plugin-react-hooks` "recommended" ruleset, including its
  newer `set-state-in-effect` rule, which caught several data-fetching
  effects that called `setState` synchronously at the top of the
  effect body -- a common but technically-flagged React pattern. Fixed
  by deriving loading state from data identity where possible
  (`useDocumentPipeline`) or moving the `setState(true)` call to the
  user-triggered handler that changes the effect's dependencies
  (search/filter/pagination), rather than the effect itself)
- `npm run build` -- production build succeeds (430KB JS / 24KB CSS,
  137KB / 5KB gzipped)
- **Full live end-to-end test** against the real backend (not just
  type-checked in isolation): started the actual FastAPI server and
  the Vite dev server together, registered a user, logged in, and
  fetched the document list -- all three requests went through Vite's
  `/api` proxy exactly as the browser app does, and all three
  succeeded against live PostgreSQL

## Local development

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, proxies /api to http://localhost:8000
```

Requires the backend running separately (`cd ../backend && uvicorn
app.main:app --reload`) with a real PostgreSQL database -- see
`../backend/README.md` for setup.

## Not yet built

- Real-time updates (the app polls/refetches on action, not via
  WebSocket/SSE -- the backend doesn't expose either yet)
- No automated frontend test suite (component/integration tests) --
  verification so far is type-checking, linting, building, and manual
  end-to-end smoke tests against the live backend

### Closed since initial Phase 11 build
Both originally-noted display gaps are now built:
- **Classification score breakdown** (`ClassificationScoresBreakdown`)
  -- a horizontal bar per document type, sorted descending, with the
  predicted type highlighted. Verified against a real classification
  response's exact `scores_by_type` shape (9 real document-type keys,
  `UNKNOWN` correctly excluded since the backend doesn't score it)
  before building against it, not assumed from the type definition
  alone.
- **OCR bounding-box visualization** (`OCRBoundingBoxes`) -- this
  required a small backend addition first: `OCRResultResponse` stored
  per-block bounding boxes (`raw_blocks` on the model) but never
  exposed them in the API response, and pixel coordinates are
  meaningless without also knowing the source image's resolution
  (which also wasn't exposed). Both gaps were closed on the backend
  side (see `../backend/README.md`'s "Deploy-Readiness Hardening"
  section) before this component could be built correctly. Rendered
  as a schematic page-layout diagram (an outlined rectangle with
  proportionally-positioned block overlays), not a true image overlay
  -- the backend doesn't serve a rendered page preview image, only the
  original uploaded file, and the component says so directly in the UI
  rather than implying more fidelity than actually exists.

## Deployment

See the repository root `README.md` for running this via Docker
Compose alongside the backend and a real PostgreSQL instance --
`Dockerfile`, `nginx.conf.template`, and `docker-entrypoint.sh` in this
directory build the production image (nginx serving the built static
files, proxying `/api/*` to the backend container over Docker's
internal network so the browser only ever talks to one origin).

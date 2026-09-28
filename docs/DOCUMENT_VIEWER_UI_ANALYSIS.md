# Document Viewer UI Analysis

## 1. Executive Summary

This report presents an architectural investigation and UI/UX design blueprint for adding a document/PDF viewing capability to the Enterprise Financial Document Intelligence (EFDI) platform. The primary objective is to enable financial analysts and managers to view original uploaded documents (invoices, receipts, tax returns, contracts) side-by-side or simultaneously with EFDI's processing tabs (OCR, Classification, Extraction, Validation, Workflow) and the newly rebranded **EFDI Bot** ("Analyze with AI").

> [!IMPORTANT]
> **Plan & Analysis Only**: Per instructions, this feature is strictly analyzed in this document and is **NOT** implemented in the codebase at this time.

### Key Findings
1. **Existing Document Access Flow**: The backend serves document bytes exclusively via an authenticated route (`GET /api/v1/documents/{document_id}/download`), which enforces role-based access control (RBAC). The frontend consumes this via `documentsApi.download(id)` in `frontend/src/services/documents.ts`, yielding a binary `Blob`. Modern browsers cannot attach custom `Authorization: Bearer <token>` headers to standard `<iframe>` or `<embed>` source requests; therefore, client-side blob retrieval and `URL.createObjectURL(blob)` is already the proven, secure mechanism.
2. **Current Component Architecture**: `frontend/src/pages/DocumentDetailPage.tsx` orchestrates all document stages via Radix-based `<Tabs>` (`ocr`, `classification`, `extraction`, `validation`, `workflow`, `chat`). Currently, there is no document preview or PDF rendering component; `OCRBoundingBoxes` renders an SVG wireframe rather than overlaying a real document image.
3. **Chatbot Coexistence**: EFDI Bot (`DocumentChatAssistant` in `frontend/src/components/document-chat.tsx`) already tracks grounded source citations (`Chunk {id} · Page {page_number}`). Introducing an inline or split document viewer creates immediate architectural synergy: clicking a citation can navigate the viewer directly to that page while conversation state remains active.
4. **Architectural Recommendation**: A **Collapsible Dual-Pane Split Layout** (toggled via a "View Document" control in the document header) is the most compatible approach. It preserves full-width tabs for standard single-screen workflows while unlocking side-by-side verification and AI interaction on enterprise desktops without requiring external libraries or breaking existing layouts.

---

## 2. Current Document Detail Architecture

### Exact File Paths & Component Responsibilities

| Responsibility | File Path | Key Component / Primitive |
| :--- | :--- | :--- |
| **Main Page** | [DocumentDetailPage.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/DocumentDetailPage.tsx) | `DocumentDetailPage` |
| **App Shell** | [AppShell.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/layouts/AppShell.tsx) | `AppShell` (fixed `w-60` sidebar + `overflow-y-auto p-8` main canvas) |
| **Tab System** | [tabs.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ui/tabs.tsx) | `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent` (Radix UI `@radix-ui/react-tabs`) |
| **Pipeline Hook** | [useDocumentPipeline.ts](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/hooks/useDocumentPipeline.ts) | `useDocumentPipeline(id)` (loads document, OCR, classification, extraction, validation, workflow) |
| **Document Info** | [DocumentDetailPage.tsx:86-108](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/DocumentDetailPage.tsx#L86-L108) | Header displaying filename, ID, file size, upload timestamp, `<StatusBadge>` |
| **OCR Tab** | [ocr-bounding-boxes.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ocr-bounding-boxes.tsx) | `OCRBoundingBoxes`, text `<pre>` block |
| **Classification Tab** | [classification-scores.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/classification-scores.tsx), [classification-correction.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/classification-correction.tsx) | `ClassificationScoresBreakdown`, `ClassificationCorrection` |
| **Extraction Tab** | [extraction-fields.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/extraction-fields.tsx), [npo-invoice-review.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/npo-invoice-review.tsx) | `ExtractionFields`, `NPOInvoiceReview` |
| **Validation Tab** | [validation-issues.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/validation-issues.tsx) | `ValidationIssuesList` |
| **Workflow Tab** | [workflow-timeline.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/workflow-timeline.tsx) | `WorkflowTimeline`, `WorkflowActions` |
| **Analyze with AI** | [document-chat.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/document-chat.tsx) | `DocumentChatAssistant` (EFDI Bot) |

### Existing Document Viewer Status
There is **no** existing document or PDF viewer component in the frontend.
In [ocr-bounding-boxes.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ocr-bounding-boxes.tsx#L5-L14), this architectural gap is explicitly documented:
```typescript
/**
 * Schematic page-layout visualization, not a true image overlay -- the
 * backend stores bounding boxes (app/models/ocr_result.py's raw_blocks)
 * but doesn't serve a rendered page preview image, only the original
 * uploaded file. Rather than overstate what's available (e.g. faking an
 * overlay against a placeholder image), this draws the page as a plain
 * outlined rectangle at the correct aspect ratio and positions each
 * text block proportionally within it...
 */
```

### Existing Modal / Overlay Components
- **Radix Dialog**: Wrapped in [frontend/src/components/ui/dialog.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ui/dialog.tsx) (`Dialog`, `DialogTrigger`, `DialogContent`, `DialogHeader`, `DialogTitle`, `DialogDescription`, `DialogFooter`).
- **Drawers / Sheets / Resizable Panels**: Not currently installed or configured.

---

## 3. Current Document Access Flow

### Backend Endpoint
In [backend/app/routers/documents.py:224-242](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/backend/app/routers/documents.py#L224-L242):
```python
@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Download the original file bytes for a document."""
    service = DocumentService(db)
    document = service.get_for_user(document_id, current_user)

    file_path = get_file_path(document.stored_filename)
    if not file_path.exists():
        raise NotFoundException("Document file on disk", document.stored_filename)

    return FileResponse(
        path=file_path,
        filename=document.original_filename,
        media_type=document.mime_type,
    )
```

### Frontend Invocation
In [frontend/src/services/documents.ts:46](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/services/documents.ts#L46):
```typescript
download: (documentId: number) => apiDownload(`/documents/${documentId}/download`)
```
In [frontend/src/services/client.ts:94-104](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/services/client.ts#L94-L104):
```typescript
export async function apiDownload(path: string): Promise<Blob> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (!response.ok) {
      throw new ApiError(response.status, null, `Download failed with status ${response.status}`);
  }
  return response.blob();
}
```

### How the Frontend Currently Handles Download
In [DocumentDetailPage.tsx:37-50](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/pages/DocumentDetailPage.tsx#L37-L50):
```typescript
async function handleDownload() {
  if (!document) return;
  try {
    const blob = await documentsApi.download(id);
    const url = URL.createObjectURL(blob);
    const a = window.document.createElement("a");
    a.href = url;
    a.download = document.original_filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    showError(err, "Could not download file");
  }
}
```

### Critical Observations for Inline Viewing:
1. **Format Payload**: The frontend receives a raw binary `Blob` with the file's MIME type (e.g., `application/pdf`, `image/png`, `image/jpeg`).
2. **Authentication Constraint**: The backend endpoint strictly requires a `Bearer <token>` HTTP header. An HTML `<iframe src="/api/v1/documents/1/download">` will fail with `401 Unauthorized` because native iframe requests do not send custom authorization headers.
3. **Object URL Feasibility**: The existing `documentsApi.download(id)` already retrieves the authenticated blob. Calling `URL.createObjectURL(blob)` yields a local `blob:http://...` URL that **can** be directly embedded in an `<iframe>`, `<object>`, or `<img>` element with zero backend modifications.

---

## 4. Existing Reusable UI Components & Dependencies

### Available in Codebase
- **Modal / Dialog**: [frontend/src/components/ui/dialog.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ui/dialog.tsx) (`@radix-ui/react-dialog`)
- **Card System**: [frontend/src/components/ui/card.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ui/card.tsx)
- **Button System**: [frontend/src/components/ui/button.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ui/button.tsx) (variants: `primary`, `seal`, `outline`, `ghost`, `secondary`)
- **Icons**: `lucide-react` (has `Eye`, `EyeOff`, `FileText`, `Maximize2`, `Minimize2`, `Columns`, `ExternalLink`, `Download`)
- **Theme Variables**: Defined in [index.css](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/index.css) (`var(--gradient-primary)`, `--color-seal-500`, `--color-paper-50`, `--color-ink-*`)

### NOT Available (Dependencies Not Installed)
- `react-pdf` / `pdfjs-dist`: **Not installed**.
- Resizable panel libraries (e.g., `react-resizable-panels`): **Not installed**.
- Drawer / sheet libraries (e.g., `vaul`): **Not installed**.

---

## 5. Candidate UI Approaches

### Approach A: "View Document" Modal Dialog
- **Description**: Add a "View Document" button next to the Download and Delete buttons in the header. Clicking opens a full-viewport modal dialog containing the rendered document.
- **Components Reused**: [dialog.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ui/dialog.tsx), [button.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ui/button.tsx), `documentsApi.download(id)`.
- **UX Considerations**:
  - *Pros*: Quick to preview document details without changing page layout. Zero risk of breaking existing tabs or layout widths.
  - *Cons*: **Modal blocks background interaction**. A user *cannot* interact with EFDI Bot or inspect Extraction/Validation tabs while the modal is open.
- **Implementation Complexity**: Low.
- **Impact on Existing Page**: Minimal.

---

### Approach B: Collapsible Right-Side or Left-Side Drawer
- **Description**: A slide-over panel that opens from the right (or left) edge of the viewport when triggered, either overlaying content or pushing the main canvas.
- **Components Reused**: Custom Tailwind fixed-position drawer or `@radix-ui/react-dialog` modified with sliding transitions.
- **UX Considerations**:
  - *Pros*: Keeps context open while viewing the document.
  - *Cons*: An overlay drawer covers tabs and chat. A push drawer requires re-layout of `AppShell` and risks horizontal cramping unless the screen is very wide.
- **Implementation Complexity**: Medium.
- **Impact on Existing Page**: Medium.

---

### Approach C: Permanent Split-Screen Layout
- **Description**: Permanently split the Document Detail page into two fixed vertical columns: Document viewer on the left (40-50% width), EFDI working tabs on the right (50-60% width).
- **Components Reused**: `DocumentDetailPage.tsx` grid layout, existing tabs.
- **UX Considerations**:
  - *Pros*: The original document is always visible during OCR review, field extraction verification, and AI chatting.
  - *Cons*: Aggressively reduces horizontal space for wide tables (e.g. `NPOInvoiceReview` table, OCR raw text block, Workflow timeline). Users who only want to review validation issues or run pipeline stages are forced into half-width.
- **Implementation Complexity**: Medium.
- **Impact on Existing Page**: High (permanently alters default experience).

---

### Approach D: Integrated "Document" Tab
- **Description**: Add a new tab called "Original Document" alongside `[OCR | Classification | Extraction | Validation | Workflow | Analyze with AI]`.
- **Components Reused**: [tabs.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ui/tabs.tsx).
- **UX Considerations**:
  - *Pros*: Fits standard tab navigation naturally.
  - *Cons*: **Completely fails the primary requirement** of viewing the original document *simultaneously* with the working interface or EFDI Bot. Switching tabs unmounts or hides the other interfaces.
- **Implementation Complexity**: Very low.
- **Impact on Existing Page**: Low.

---

### Approach E: Collapsible / Dockable Dual-Pane Split Layout (Recommended Architectural Direction)
- **Description**: Default to the current single-pane view, but provide a prominent "Split View" toggle button (e.g., `<Button variant="outline"><Columns className="h-4 w-4 mr-1.5" /> Split Document View</Button>`) in the document header. When toggled on:
  - The page smoothly splits into a 2-column responsive layout (`grid grid-cols-1 xl:grid-cols-2 gap-6`).
  - **Left Pane**: Sticky, full-height Document/PDF viewer with page navigation, zoom, and open-in-new-tab controls.
  - **Right Pane**: The existing EFDI working interface with all tabs (`OCR`, `Extraction`, `Validation`, `Analyze with AI`).
  - When toggled off, the document pane closes and the EFDI interface returns to its full-width single-pane layout.
- **Components Reused**: `DocumentDetailPage.tsx`, `button.tsx`, `card.tsx`, `documentsApi.download(id)`.
- **UX Considerations**:
  - *Pros*: Gives users the best of both worlds. Financial analysts who need side-by-side data verification or want to converse with EFDI Bot while referencing page 3 can toggle split view on. Users reviewing complex multi-column extraction tables or audit logs can toggle it off for full width.
  - *Cons*: Requires clean responsive breakpoints for screens narrower than 1280px.
- **Implementation Complexity**: Moderate.
- **Impact on Existing Page**: Zero regression to default state; fully additive.

---

## 6. Recommended Architectural Direction

Based on concrete architectural evidence in the repository, **Approach E (Collapsible Dual-Pane Split Layout with Native Blob URL Iframe)** is the recommended path.

### Architectural Justification:
1. **Preservation of Existing Layouts**: EFDI contains data-dense components such as `NPOInvoiceReview` ([npo-invoice-review.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/npo-invoice-review.tsx)) with complex line-item tables and `OCRBoundingBoxes` ([ocr-bounding-boxes.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/ocr-bounding-boxes.tsx)) with fixed coordinate SVGs. Forcing a permanent 50% split would degrade these components on standard displays. A toggleable split preserves full width whenever desired.
2. **Zero New Dependency Overhead**: Modern web browsers include high-performance, feature-complete PDF viewing engines (supporting page jumps, text search, zoom, and printing). By fetching the document as a `Blob` via the existing `documentsApi.download(id)` and rendering it inside an `<iframe>` or `<object>` with `URL.createObjectURL(blob)`, EFDI avoids adding heavy dependencies like `pdfjs-dist` or `react-pdf` (which can add over 1MB to client bundles and require complex worker script setup in Vite).
3. **Full RBAC Security Compliance**: Utilizes the existing authenticated `apiDownload` pipeline. No unauthenticated endpoints, query-string token leaks, or backend router changes are required.

---

## 7. Integration With "Analyze with AI" / EFDI Bot

Coexistence between the document viewer and EFDI Bot is one of the highest-value capabilities of this architecture:

### 1. Persistent Conversational Context
In `DocumentChatAssistant` ([document-chat.tsx](file:///c:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/frontend/src/components/document-chat.tsx)), the chat session is linked to `documentId` via `/api/v1/chat/sessions/document/{documentId}`.
In the dual-pane layout:
- The user can select the **"Analyze with AI"** tab in the right pane.
- The left pane renders the original document.
- The user can ask questions (e.g., *"What are the penalty interest rates in clause 4?"*) while actively scrolling through page 2 and reading the original contract text.

### 2. Deep-Linking from Citations (Grounded Sources)
EFDI Bot already renders citation buttons:
```typescript
<button className="...">
  <span>Chunk {citation.chunk_id} · Page {citation.page_number} · {citation.chunk_type}</span>
</button>
```
With the document viewer open, clicking any citation badge can trigger a page navigation callback:
- Standard browser PDF viewers support page fragments: `<iframe src="${blobUrl}#page=${pageNumber}">`.
- Clicking `Page 2` in EFDI Bot's grounded source list will immediately jump the document viewer to page 2, providing instant auditability.

### 3. Independent Scroll Containers
The document viewer pane and the EFDI working tabs should each possess independent `overflow-y-auto` scroll contexts. Scrolling through a 20-page PDF document on the left will not disrupt the user's position in the AI chat message feed or extraction fields on the right.

---

## 8. Responsive Behavior

| Screen Size | Breakpoint | Behavior in Split View |
| :--- | :--- | :--- |
| **Enterprise Monitors / Large Desktops** | `>= 1536px` (`2xl`) | Side-by-side 50/50 split. Both document and EFDI tabs have generous horizontal breathing room. |
| **Standard Desktops / Large Laptops** | `1280px - 1535px` (`xl`) | Side-by-side 45/55 split (45% document, 55% working interface). |
| **Standard Laptops** | `1024px - 1279px` (`lg`) | Side-by-side 40/60 or automatically collapsible into a floating side drawer / modal preview to prevent table truncation. |
| **Tablets & Mobile Screens** | `< 1024px` | Split view automatically collapses into a full-screen preview overlay or modal with a "Close Preview" button, returning to the working tabs seamlessly. |

---

## 9. Security and Authorization Considerations

1. **Bearer Token Authentication**:
   - The original file must never be exposed via an unauthenticated static URL.
   - All document fetching must continue through `documentsApi.download(documentId)`, which sends the JWT stored in `localStorage.getItem("efdi_token")`.
2. **Blob URL Lifecycle & Revocation**:
   - Generating `URL.createObjectURL(blob)` stores file bytes in browser memory.
   - To prevent memory leaks, `URL.revokeObjectURL(url)` must be called in a `useEffect` cleanup return when the viewer unmounts or the document ID changes.
   - Blob URLs are scoped strictly to the current browser origin (`http://localhost:5173`) and cannot be accessed across domains or tabs without authorization.
3. **Iframe Sandboxing**:
   - For PDFs and images, if rendered within an iframe, standard sandboxing attributes (`sandbox="allow-scripts allow-same-origin"`) ensure the rendered document cannot execute arbitrary parent-window scripts.
4. **Role-Based Document Access**:
   - The backend `DocumentService.get_for_user(document_id, current_user)` enforces whether the requesting user is allowed to access the document (verifying company ownership or roles like `ADMIN`, `FINANCE_MANAGER`, `AUDITOR`). An inline viewer inherits this identical authorization check.

---

## 10. Performance Considerations

1. **Lazy Loading**:
   - The document blob should **not** be fetched eagerly on initial page load of `DocumentDetailPage`.
   - The blob should be fetched on demand only when the user toggles Split View or opens the preview.
2. **Large Documents & Multi-Page PDFs**:
   - For multi-megabyte PDFs (e.g., 50-100 pages), browser native PDF engines stream and render pages on-demand without hanging the main React thread.
   - Keeping the blob URL isolated in component state prevents unnecessary re-rendering of the heavy iframe when the user types in the AI chat or modifies extracted form fields.
3. **Component Re-rendering Isolation**:
   - The document viewer should be an isolated React component with memoized props (`React.memo`) so that streaming token updates from EFDI Bot do not trigger DOM reloads on the iframe.

---

## 11. Proposed Future Implementation Structure (Plan Only)

### Likely Files to Create
1. `frontend/src/components/document-viewer/DocumentViewer.tsx`:
   - Handles the authenticated blob fetching, loading skeleton, error fallback, and zoom/page controls.
2. `frontend/src/components/document-viewer/PdfFrameViewer.tsx`:
   - Embeds native PDF iframe with `#page=N` fragment support.
3. `frontend/src/components/document-viewer/ImageViewer.tsx`:
   - For image-based uploads (`image/png`, `image/jpeg`, `image/tiff`) with pan/zoom.

### Likely Files to Modify
1. `frontend/src/pages/DocumentDetailPage.tsx`:
   - Add split-view state (`isSplitViewOpen: boolean`, `activePage: number | null`).
   - Add "View Document" / "Split View" toggle button to header actions.
   - Wrap the main content in a 2-column responsive layout when `isSplitViewOpen` is true.
2. `frontend/src/components/document-chat.tsx`:
   - Accept an optional prop: `onCitationClick?: (pageNumber: number) => void`.
   - When present, clicking a citation badge calls `onCitationClick`, navigating the viewer.

### Expected Data Flow
```
User clicks "Split View"
  │
  ├──> DocumentDetailPage sets isSplitViewOpen = true
  │
  ├──> DocumentViewer mounts with documentId & mimeType
  │      │
  │      └──> Calls documentsApi.download(documentId) [authenticated]
  │      └──> Receives Blob -> calls URL.createObjectURL(blob)
  │      └──> Renders <iframe src={objectUrl} />
  │
  └──> EFDI Working Interface remains in adjacent pane
         │
         ├──> User queries EFDI Bot in "Analyze with AI"
         │
         └──> EFDI Bot returns answer with citations
                │
                └──> User clicks "Page 2" citation
                       │
                       └──> DocumentViewer navigates to page 2
```

---

## 12. Future Implementation Phases

### Phase 1: Core Document Viewer Component
- Implement `DocumentViewer` component with authenticated blob fetching and object URL lifecycle management.
- Test rendering with PDF documents and image formats.
- Add zoom, download, and external-window controls.

### Phase 2: Dual-Pane Split Layout in DocumentDetailPage
- Add split-screen toggle button to `DocumentDetailPage` header.
- Implement responsive grid transition (`grid-cols-1` <-> `grid-cols-2`).
- Ensure independent scrolling for document pane and tabs pane.

### Phase 3: Citation Navigation & AI Synergy
- Connect citation buttons in `DocumentChatAssistant` to `DocumentViewer` active page.
- Test deep-linking from grounded sources directly to cited document pages.

### Phase 4: Polish & Edge Cases
- Handle multi-page edge cases, unsupported MIME types, and mobile fallback sheets.
- Performance verification on large PDFs.

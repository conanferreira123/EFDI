import { useParams, useNavigate } from "react-router-dom";
import { Trash2, Download, FileText, Sparkles } from "lucide-react";
import { useDocumentPipeline } from "@/hooks/useDocumentPipeline";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ClassificationScoresBreakdown } from "@/components/classification-scores";
import { ClassificationCorrection } from "@/components/classification-correction";
import { ConfidenceBar } from "@/components/confidence-bar";
import { PipelineActions } from "@/components/pipeline-actions";
import { WorkflowActions } from "@/components/workflow-actions";
import { ExtractionFields } from "@/components/extraction-fields";
import { OCRBoundingBoxes } from "@/components/ocr-bounding-boxes";
import { ValidationIssuesList } from "@/components/validation-issues";
import { WorkflowTimeline } from "@/components/workflow-timeline";
import { DocumentChatAssistant } from "@/components/document-chat";
import { documentsApi } from "@/services/documents";
import {extractionApi} from "@/services/pipeline";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/context/AuthContext";
import { formatFileSize, formatDateTime } from "@/lib/format";
import { DOCUMENT_TYPE_LABELS, type DocumentType } from "@/types/domain";

export function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const id = Number(documentId);
  const navigate = useNavigate();
  const { user } = useAuth();
  const showError = useApiErrorToast();
  const { push } = useToast();

  const { document, ocr, classification, extraction, validation, history, isLoading, refresh } =
    useDocumentPipeline(id);

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
  async function handleExportExtraction(format: "json" | "csv" | "excel") {
    try {
      const blob = await extractionApi.export(id, format);
      const extension = format === "excel" ? "xlsx" : format;
      const url = URL.createObjectURL(blob);
      const a = window.document.createElement("a");
      a.href = url;
      a.download = `extraction_${id}.${extension}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showError(err, "Could not export extracted fields");
    }
  }

  async function handleDelete() {
    if (!window.confirm("Delete this document? This can't be undone from the UI.")) return;
    try {
      await documentsApi.delete(id);
      push({ tone: "success", title: "Document deleted" });
      navigate("/documents");
    } catch (err) {
      showError(err, "Could not delete document");
    }
  }

  if (isLoading || !document) {
    return <p className="text-sm text-ink-400">Loading document…</p>;
  }

  const canDelete =
    user?.role === "ADMIN" || user?.role === "FINANCE_MANAGER" || user?.id === document.uploaded_by;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <FileText className="h-6 w-6 text-ink-400" />
          <div>
            <h2 className="text-xl font-semibold text-ink-900">{document.original_filename}</h2>
            <p className="font-data text-xs text-ink-400">
              #{document.id} · {formatFileSize(document.file_size_bytes)} · uploaded{" "}
              {formatDateTime(document.created_at)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={document.status} />
          <Button variant="outline" size="icon" onClick={handleDownload} title="Download">
            <Download className="h-4 w-4" />
          </Button>
          {canDelete && (
            <Button variant="outline" size="icon" onClick={handleDelete} title="Delete">
              <Trash2 className="h-4 w-4 text-clay-500" />
            </Button>
          )}
        </div>
      </div>

      <div className="ledger-rule" />

      <Card>
        <CardContent className="flex items-center justify-between py-4">
          <div className="flex items-center gap-6 text-sm">
            <div>
              <span className="text-ink-400">Type: </span>
              <span className="font-medium text-ink-900">
                {DOCUMENT_TYPE_LABELS[document.document_type as DocumentType]}
              </span>
            </div>
            {classification && (
              <ConfidenceBar value={classification.confidence} />
            )}
          </div>
          <div className="flex gap-2">
            <PipelineActions documentId={id} status={document.status} onComplete={refresh} />
            <WorkflowActions documentId={id} status={document.status} onComplete={refresh} />
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="extraction">
        <TabsList>
          <TabsTrigger value="ocr">OCR</TabsTrigger>
          <TabsTrigger value="classification">Classification</TabsTrigger>
          <TabsTrigger value="extraction">Extraction</TabsTrigger>
          <TabsTrigger value="validation">Validation</TabsTrigger>
          <TabsTrigger value="workflow">Workflow</TabsTrigger>
          <TabsTrigger value="chat" className="flex items-center gap-1.5 font-medium text-primary">
            <Sparkles className="h-3.5 w-3.5" />
            Ask AI
          </TabsTrigger>
        </TabsList>

        <TabsContent value="ocr">
          {ocr ? (
            <Card>
              <CardHeader>
                <CardTitle>OCR result</CardTitle>
                <CardDescription>
                  Engine: {ocr.engine_name}
                  {ocr.is_stub_result && " (placeholder — no real OCR engine configured)"} ·{" "}
                  {ocr.page_count} page{ocr.page_count !== 1 ? "s" : ""}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div>
                  <ConfidenceBar value={ocr.average_confidence} className="mb-4" />
                  <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md bg-ink-50 p-4 font-data text-xs text-ink-700">
                    {ocr.full_text}
                  </pre>
                </div>

                {ocr.raw_blocks.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-400">
                      Detected text blocks
                    </p>
                    <OCRBoundingBoxes pages={ocr.raw_blocks} />
                  </div>
                )}
              </CardContent>
            </Card>
          ) : (
            <EmptyStep label="OCR hasn't been run on this document yet." />
          )}
        </TabsContent>

        <TabsContent value="classification">
          {classification ? (
            <Card>
              <CardHeader>
                <CardTitle>Classification result</CardTitle>
                <CardDescription>Engine: {classification.engine_name}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-ink-500">Predicted type:</span>
                  <span className="font-medium text-ink-900">
                    {DOCUMENT_TYPE_LABELS[classification.predicted_type]}
                  </span>
                  <ConfidenceBar value={classification.confidence} />
                </div>
                <ClassificationCorrection
                  documentId={document!.id}
                  predictedType={classification.predicted_type}
                  onCorrected={refresh}
                />
                {classification.signals.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium uppercase tracking-wide text-ink-400">
                      Matched signals
                    </p>
                    {classification.signals.map((signal, i) => (
                      <div key={i} className="rounded-md bg-ink-50 px-3 py-2 text-xs text-ink-600">
                        <span className="font-data">"{signal.matched_text}"</span> — {signal.rule_description}
                      </div>
                    ))}
                  </div>
                )}

                {Object.keys(classification.scores_by_type).length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-400">
                      Score by document type
                    </p>
                    <ClassificationScoresBreakdown
                      scores={classification.scores_by_type}
                      predictedType={classification.predicted_type}
                    />
                  </div>
                )}
              </CardContent>
            </Card>
          ) : (
            <EmptyStep label="Classification hasn't been run on this document yet." />
          )}
        </TabsContent>

        <TabsContent value="extraction">
          {extraction ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm text-ink-500">
                  {extraction.fields_found_count} of {extraction.fields_total_count} fields found ·
                  overall confidence{" "}
                  <span className="font-data">{Math.round(extraction.overall_confidence * 100)}%</span>
                </p>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => handleExportExtraction("json")}>
                    Export JSON
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => handleExportExtraction("csv")}>
                    Export CSV
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => handleExportExtraction("excel")}>
                    Export Excel
                  </Button>
                </div>
              </div>
              <ExtractionFields
                documentId={id}
                documentType={document?.document_type || extraction.document_type}
                fields={extraction.fields}
                canonical={extraction.canonical}
                onFieldUpdated={refresh}
              />
            </div>
          ) : (
            <EmptyStep label="Field extraction hasn't been run on this document yet." />
          )}
        </TabsContent>

        <TabsContent value="validation">
          {validation ? (
            <ValidationIssuesList issues={validation.issues} isValid={validation.is_valid} />
          ) : (
            <EmptyStep label="Validation hasn't been run on this document yet." />
          )}
        </TabsContent>

        <TabsContent value="workflow">
          <WorkflowTimeline history={history} />
        </TabsContent>

        <TabsContent value="chat">
          <DocumentChatAssistant documentId={id} originalFilename={document.original_filename} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function EmptyStep({ label }: { label: string }) {
  return (
    <div className="rounded-lg border border-dashed border-ink-200 px-6 py-10 text-center text-sm text-ink-400">
      {label}
    </div>
  );
}

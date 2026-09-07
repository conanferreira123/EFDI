import { useCallback, useEffect, useState } from "react";
import { documentsApi } from "@/services/documents";
import { ocrApi, classificationApi, extractionApi, validationApi } from "@/services/pipeline";
import { workflowApi } from "@/services/workflow";
import { ApiError } from "@/services/client";
import type {
  ClassificationResultResponse,
  DocumentResponse,
  ExtractionResultResponse,
  OCRResultResponse,
  ValidationResultResponse,
  WorkflowHistoryResponse,
} from "@/types/api";

interface PipelineState {
  documentId: number | null;
  document: DocumentResponse | null;
  ocr: OCRResultResponse | null;
  classification: ClassificationResultResponse | null;
  extraction: ExtractionResultResponse | null;
  validation: ValidationResultResponse | null;
  history: WorkflowHistoryResponse[];
}

const EMPTY_STATE: PipelineState = {
  documentId: null,
  document: null,
  ocr: null,
  classification: null,
  extraction: null,
  validation: null,
  history: [],
};

/** Resolves a "not found" 404 to null instead of throwing -- every
 * pipeline step is optional until it's actually been run, so a 404
 * here just means "hasn't happened yet," not an error. */
async function fetchOrNull<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function useDocumentPipeline(documentId: number) {
  const [state, setState] = useState<PipelineState>(EMPTY_STATE);

  async function loadPipeline(id: number) {
    const [document, ocr, classification, extraction, validation, history] = await Promise.all([
      documentsApi.get(id),
      fetchOrNull(() => ocrApi.getLatest(id)),
      fetchOrNull(() => classificationApi.getLatest(id)),
      fetchOrNull(() => extractionApi.getLatest(id)),
      fetchOrNull(() => validationApi.getLatest(id)),
      workflowApi.history(id).catch(() => []),
    ]);
    return { documentId: id, document, ocr, classification, extraction, validation, history };
  }

  const refresh = useCallback(async () => {
    const next = await loadPipeline(documentId);
    setState(next);
  }, [documentId]);

  // Deliberately not using `refresh` here -- it calls setState after
  // an await, which is genuinely async, but it's wrapped in
  // useCallback and the linter's static analysis can't see through
  // that boundary, so it flags it as a synchronous effect-body call.
  // Inlining the same logic directly (still after an await, still
  // genuinely async) satisfies the rule without changing behavior.
  useEffect(() => {
    let cancelled = false;
    loadPipeline(documentId).then((next) => {
      if (!cancelled) setState(next);
    });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const isLoading = state.documentId !== documentId;

  return { ...state, isLoading, refresh };
}

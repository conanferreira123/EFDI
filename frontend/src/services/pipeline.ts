import { apiDownload, apiRequest } from "./client";
import type {
  ClassificationResultResponse,
  ExtractionResultResponse,
  OCREngineStatusResponse,
  OCRResultResponse,
  ValidationResultResponse,
} from "@/types/api";

export const ocrApi = {
  engines: () => apiRequest<OCREngineStatusResponse>("/ocr/engines"),

  run: (documentId: number, engine?: string) =>
    apiRequest<OCRResultResponse>(`/ocr/documents/${documentId}/run`, {
      method: "POST",
      body: { engine: engine || null },
    }),

  getLatest: (documentId: number) =>
    apiRequest<OCRResultResponse>(`/ocr/documents/${documentId}/result`),

  list: (documentId: number) =>
    apiRequest<OCRResultResponse[]>(`/ocr/documents/${documentId}/results`),
};

export const classificationApi = {
  run: (documentId: number, engine?: string) =>
    apiRequest<ClassificationResultResponse>(`/classification/documents/${documentId}/classify`, {
      method: "POST",
      body: { engine: engine || null },
    }),

  getLatest: (documentId: number) =>
    apiRequest<ClassificationResultResponse>(`/classification/documents/${documentId}/result`),

  list: (documentId: number) =>
    apiRequest<ClassificationResultResponse[]>(`/classification/documents/${documentId}/results`),

  correct: (documentId: number, correctedType: string) =>
    apiRequest<ClassificationResultResponse>(`/classification/documents/${documentId}/correct`, {
      method: "PATCH",
      body: { corrected_type: correctedType },
    }),
};

export const extractionApi = {
  run: (documentId: number, engine?: string) =>
    apiRequest<ExtractionResultResponse>(`/extraction/documents/${documentId}/extract`, {
      method: "POST",
      body: { engine: engine || null },
    }),

  getLatest: (documentId: number) =>
    apiRequest<ExtractionResultResponse>(`/extraction/documents/${documentId}/result`),

  list: (documentId: number) =>
    apiRequest<ExtractionResultResponse[]>(`/extraction/documents/${documentId}/results`),

  updateField: (documentId: number, fieldKey: string, value: string) =>
    apiRequest<ExtractionResultResponse>(
      `/extraction/documents/${documentId}/fields/${encodeURIComponent(fieldKey)}`,
      { method: "PATCH", body: { value } }
    ),
  export: (documentId: number, format: "json" | "csv" | "excel") =>
    apiDownload(`/extraction/documents/${documentId}/export?format=${format}`),
};

export const validationApi = {
  run: (documentId: number) =>
    apiRequest<ValidationResultResponse>(`/validation/documents/${documentId}/validate`, {
      method: "POST",
      body: {},
    }),

  getLatest: (documentId: number) =>
    apiRequest<ValidationResultResponse>(`/validation/documents/${documentId}/result`),

  list: (documentId: number) =>
    apiRequest<ValidationResultResponse[]>(`/validation/documents/${documentId}/results`),
};

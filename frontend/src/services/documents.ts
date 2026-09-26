import { apiDownload, apiRequest } from "./client";
import type {
  BulkIntakeResponse,
  DocumentFilterParams,
  DocumentListItem,
  DocumentListResponse,
  DocumentResponse,
  DocumentUploadResponse,
  MessageResponse,
} from "@/types/api";

export const documentsApi = {
  upload: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return apiRequest<DocumentUploadResponse>("/documents/upload", {
      method: "POST",
      body: formData,
      isFormData: true,
    });
  },

  bulkUpload: (files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    return apiRequest<BulkIntakeResponse>("/documents/upload/bulk", {
      method: "POST",
      body: formData,
      isFormData: true,
    });
  },

  scanIntakeFolder: (subpath?: string) =>
    apiRequest<BulkIntakeResponse>("/documents/intake/scan-folder", {
      method: "POST",
      body: { subpath: subpath || null },
    }),

  list: (filters: DocumentFilterParams = {}) =>
    apiRequest<DocumentListResponse>("/documents", { query: filters }),

  getRecentlyViewed: () => apiRequest<DocumentListItem[]>("/documents/recently-viewed"),

  get: (documentId: number) => apiRequest<DocumentResponse>(`/documents/${documentId}`),

  download: (documentId: number) => apiDownload(`/documents/${documentId}/download`),

  delete: (documentId: number) =>
    apiRequest<MessageResponse>(`/documents/${documentId}`, { method: "DELETE" }),
};

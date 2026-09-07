import { apiRequest } from "./client";
import type { DocumentResponse, WorkflowHistoryResponse } from "@/types/api";

export const workflowApi = {
  requestApproval: (documentId: number, comment?: string) =>
    apiRequest<DocumentResponse>(`/workflow/documents/${documentId}/request-approval`, {
      method: "POST",
      body: { comment: comment || null },
    }),

  approve: (documentId: number, comment?: string) =>
    apiRequest<DocumentResponse>(`/workflow/documents/${documentId}/approve`, {
      method: "POST",
      body: { comment: comment || null },
    }),

  reject: (documentId: number, comment: string) =>
    apiRequest<DocumentResponse>(`/workflow/documents/${documentId}/reject`, {
      method: "POST",
      body: { comment },
    }),

  history: (documentId: number) =>
    apiRequest<WorkflowHistoryResponse[]>(`/workflow/documents/${documentId}/history`),
};

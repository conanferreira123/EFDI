import { apiRequest } from "./client";
import type {
  AuditLogFilterParams,
  AuditLogListResponse,
  AuditLogResponse,
  UserResponse,
} from "@/types/api";
import type { UserRole } from "@/types/domain";

export const auditApi = {
  list: (filters: AuditLogFilterParams = {}) =>
    apiRequest<AuditLogListResponse>("/audit/logs", { query: filters }),

  forDocument: (documentId: number) =>
    apiRequest<AuditLogResponse[]>(`/audit/documents/${documentId}/logs`),
};

export const usersApi = {
  list: (skip = 0, limit = 100) =>
    apiRequest<UserResponse[]>("/users", { query: { skip, limit } }),

  get: (userId: number) => apiRequest<UserResponse>(`/users/${userId}`),

  updateRole: (userId: number, role: UserRole) =>
    apiRequest<UserResponse>(`/users/${userId}/role`, { method: "PATCH", body: { role } }),

  updateStatus: (userId: number, isActive: boolean) =>
    apiRequest<UserResponse>(`/users/${userId}/status`, {
      method: "PATCH",
      body: { is_active: isActive },
    }),
};

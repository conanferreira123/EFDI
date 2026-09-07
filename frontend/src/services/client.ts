import type { ApiErrorBody } from "@/types/api";

const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null, fallbackMessage: string) {
    super(body?.message ?? fallbackMessage);
    this.status = status;
    this.body = body;
  }
}

function getToken(): string | null {
  return localStorage.getItem("efdi_token");
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  isFormData?: boolean;
  query?: object;
}

function buildQueryString(query?: object): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, isFormData = false, query } = options;

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let requestBody: BodyInit | undefined;
  if (body !== undefined) {
    if (isFormData) {
      requestBody = body as FormData;
      // Deliberately no Content-Type header for FormData -- the
      // browser sets the multipart boundary itself, and overriding it
      // manually is a classic way to silently corrupt uploads.
    } else {
      headers["Content-Type"] = "application/json";
      requestBody = JSON.stringify(body);
    }
  }

  const response = await fetch(`${API_BASE}${path}${buildQueryString(query)}`, {
    method,
    headers,
    body: requestBody,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");

  if (!response.ok) {
    const errorBody = isJson ? ((await response.json()) as ApiErrorBody) : null;
    if (response.status === 401) {
      // Session is no longer valid (expired/invalid token, or the
      // account was deactivated) -- clear it so the app falls back to
      // the login screen instead of repeatedly hitting 401s.
      localStorage.removeItem("efdi_token");
      localStorage.removeItem("efdi_user");
    }
    throw new ApiError(response.status, errorBody, `Request failed with status ${response.status}`);
  }

  if (!isJson) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** For downloads, where the response is a raw file blob, not JSON. */
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

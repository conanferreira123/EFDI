import { apiRequest } from "./client";

export interface CitationItem {
  chunk_id: number;
  document_id?: number;
  page_number: number;
  chunk_type: string;
  snippet: string;
  bounding_box_refs: Array<{ text?: string; bounding_box?: number[] }>;
  rerank_score?: number;
}

export interface ChatMessageResponse {
  session_id: number;
  message_id: number;
  role: "assistant" | "user";
  content: string;
  citations: CitationItem[];
  created_at: string;
}

export interface ToolCallItem {
  tool: string;
  sql?: string;
  row_count?: number;
  summary?: string;
  result?: any;
  retrieved_count?: number;
  scoped_documents?: number[];
  error?: string;
}

export interface GlobalChatMessageResponse {
  session_id: number;
  message_id: number;
  role: "assistant" | "user";
  content: string;
  tool_calls: ToolCallItem[];
  citations: CitationItem[];
  created_at: string;
  execution_time_ms: number;
}

export interface ChatHistoryItem {
  id: number;
  session_id: number;
  role: "assistant" | "user";
  content: string;
  tool_calls?: ToolCallItem[];
  citations: CitationItem[];
  created_at?: string;
}

export const chatApi = {
  sendDocumentMessage(documentId: number, message: string): Promise<ChatMessageResponse> {
    return apiRequest<ChatMessageResponse>(`/chat/documents/${documentId}/messages`, {
      method: "POST",
      body: { message },
    });
  },

  getDocumentHistory(documentId: number): Promise<ChatHistoryItem[]> {
    return apiRequest<ChatHistoryItem[]>(`/chat/documents/${documentId}/history`, {
      method: "GET",
    });
  },

  clearDocumentHistory(documentId: number): Promise<{ status: string; deleted_messages: number }> {
    return apiRequest(`/chat/documents/${documentId}/history`, {
      method: "DELETE",
    });
  },

  sendGlobalMessage(message: string): Promise<GlobalChatMessageResponse> {
    return apiRequest<GlobalChatMessageResponse>(`/chat/corpus/messages`, {
      method: "POST",
      body: { message },
    });
  },

  getGlobalHistory(): Promise<ChatHistoryItem[]> {
    return apiRequest<ChatHistoryItem[]>(`/chat/corpus/history`, {
      method: "GET",
    });
  },

  clearGlobalHistory(): Promise<{ status: string; deleted_messages: number }> {
    return apiRequest(`/chat/corpus/history`, {
      method: "DELETE",
    });
  },
};


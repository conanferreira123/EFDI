import { useEffect, useRef, useState } from "react";
import { Sparkles, Send, Trash2, Bot, User, BookOpen, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { chatApi, type ChatHistoryItem } from "@/services/chat";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useAuth } from "@/context/AuthContext";
import { MarkdownRenderer } from "@/components/markdown-renderer";

interface DocumentChatProps {
  documentId: number;
  originalFilename: string;
}

export function DocumentChatAssistant({ documentId, originalFilename }: DocumentChatProps) {
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatHistoryItem[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isFetchingHistory, setIsFetchingHistory] = useState(true);
  const [expandedCitationId, setExpandedCitationId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const showError = useApiErrorToast();

  useEffect(() => {
    loadHistory();
  }, [documentId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  async function loadHistory() {
    setIsFetchingHistory(true);
    try {
      const history = await chatApi.getDocumentHistory(documentId);
      setMessages(history);
    } catch (err) {
      showError(err, "Could not load chat history");
    } finally {
      setIsFetchingHistory(false);
    }
  }

  async function handleSendMessage(textToSend?: string) {
    const text = (textToSend || inputMessage).trim();
    if (!text || isLoading) return;

    setInputMessage("");
    const tempUserMsg: ChatHistoryItem = {
      id: Date.now(),
      session_id: 0,
      role: "user",
      content: text,
      citations: [],
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, tempUserMsg]);
    setIsLoading(true);

    try {
      const response = await chatApi.sendDocumentMessage(documentId, text);
      const assistantMsg: ChatHistoryItem = {
        id: response.message_id,
        session_id: response.session_id,
        role: "assistant",
        content: response.content,
        citations: response.citations,
        created_at: response.created_at,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      showError(err, "Failed to send message to AI Assistant");
      // Remove temporary user message if failed
      setMessages((prev) => prev.filter((m) => m.id !== tempUserMsg.id));
    } finally {
      setIsLoading(false);
    }
  }

  async function handleClearHistory() {
    if (!window.confirm("Clear this document's conversation history?")) return;
    try {
      await chatApi.clearDocumentHistory(documentId);
      setMessages([]);
    } catch (err) {
      showError(err, "Could not clear chat history");
    }
  }

  const promptSuggestions = [
    "What are the payment terms & early discounts?",
    "Are there late payment penalty interest rates?",
    "What Incoterms or delivery conditions apply?",
    "Summarize the parties, dispute, and freight clauses",
  ];

  return (
    <Card className="flex flex-col overflow-hidden border border-ink-200 shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between border-b border-ink-100 bg-ink-50/50 py-3 px-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <CardTitle className="text-sm font-semibold text-ink-900">
              Document Intelligence Assistant
            </CardTitle>
            <CardDescription className="text-xs text-ink-500">
              AI-powered analysis of this financial document
            </CardDescription>
          </div>
        </div>
        {messages.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClearHistory}
            className="text-xs text-ink-500 hover:text-red-600"
            title="Clear conversation history"
          >
            <Trash2 className="h-3.5 w-3.5 mr-1" />
            Clear
          </Button>
        )}
      </CardHeader>

      {/* Messages area */}
      <CardContent className={`bg-white ${messages.length > 0 ? "p-4 space-y-4" : "px-4 py-6"}`}>
        {isFetchingHistory ? (
          <div className="flex items-center justify-center py-12 text-xs text-ink-400">
            Loading conversation history…
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center text-center max-w-lg mx-auto">
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/5 text-primary mb-2.5">
              <Bot className="h-5 w-5" />
            </div>
            <h4 className="text-sm font-medium text-ink-900 mb-1">
              Ask questions about this document
            </h4>
            <p className="text-xs text-ink-400 max-w-sm mb-4">
              Ask about payment terms, early payment discounts, Incoterms, freight clauses, or penalty details.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full">
              {promptSuggestions.map((prompt, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSendMessage(prompt)}
                  className="rounded-lg border border-ink-200 bg-ink-50/40 p-2.5 text-left text-xs text-ink-700 hover:bg-ink-100/60 hover:border-ink-300 transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, index) => {
            const isUser = msg.role === "user";
            return (
              <div
                key={msg.id || index}
                className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}
              >
                {!isUser && (
                  <div className="flex h-7 w-7 shrink-0 select-none items-center justify-center rounded-full bg-seal-100 text-seal-600 text-xs font-semibold">
                    <Bot className="h-4 w-4" />
                  </div>
                )}
                <div className={`flex flex-col max-w-[82%] ${isUser ? "items-end" : "items-start"}`}>
                  <div className="flex items-center gap-1.5 mb-1 px-1 text-[11px] text-ink-400 font-medium">
                    {isUser ? (
                      <span>{user?.full_name || "You"}</span>
                    ) : (
                      <span>Document Intelligence Assistant</span>
                    )}
                  </div>
                  <div
                    className={`rounded-xl px-4 py-3 text-sm shadow-sm ${
                      isUser
                        ? "bg-seal-600 text-white"
                        : "bg-ink-50/80 text-ink-900 border border-ink-100"
                    }`}
                  >
                    {isUser ? (
                      <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    ) : (
                      <MarkdownRenderer content={msg.content} />
                    )}

                  {/* Citations section */}
                  {!isUser && msg.citations && msg.citations.length > 0 && (() => {
                    const uniqueCitations = msg.citations.filter(
                      (citation, idx, arr) =>
                        arr.findIndex((c) =>
                          c.chunk_id
                            ? c.chunk_id === citation.chunk_id
                            : c.page_number === citation.page_number && c.chunk_type === citation.chunk_type
                        ) === idx
                    );
                    if (uniqueCitations.length === 0) return null;

                    const activeCitation = uniqueCitations.find((c, citIdx) => {
                      const citationKey = `${msg.id || index}-${c.chunk_id || citIdx}`;
                      return expandedCitationId === citationKey;
                    });

                    return (
                      <div className="mt-2.5 pt-2 border-t border-ink-200/60">
                        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                          <span className="flex items-center gap-1 font-medium text-ink-500 shrink-0">
                            <BookOpen className="h-3 w-3" />
                            Grounded Sources:
                          </span>
                          {uniqueCitations.map((citation, citIdx) => {
                            const citationKey = `${msg.id || index}-${citation.chunk_id || citIdx}`;
                            const isExpanded = expandedCitationId === citationKey;
                            return (
                              <button
                                type="button"
                                key={citationKey}
                                onClick={() =>
                                  setExpandedCitationId(isExpanded ? null : citationKey)
                                }
                                className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium transition-all cursor-pointer ${
                                  isExpanded
                                    ? "border-seal-400 bg-seal-50 text-seal-700 shadow-xs"
                                    : "border-ink-200/80 bg-white/90 text-ink-700 hover:border-ink-300 hover:bg-ink-100/60"
                                }`}
                                title="Click to view citation snippet"
                              >
                                <span>
                                  Chunk {citation.chunk_id} · Page {citation.page_number} · {citation.chunk_type}
                                </span>
                                {isExpanded ? (
                                  <ChevronUp className="h-3 w-3 shrink-0 opacity-70" />
                                ) : (
                                  <ChevronDown className="h-3 w-3 shrink-0 opacity-70" />
                                )}
                              </button>
                            );
                          })}
                        </div>

                        {activeCitation && (
                          <div className="mt-2 rounded-lg border border-ink-200/80 bg-white/95 p-2.5 text-[11px] text-ink-700 shadow-xs">
                            <div className="flex items-center justify-between pb-1.5 mb-1.5 border-b border-ink-100 text-[10px] uppercase font-semibold tracking-wider text-ink-500 font-data">
                              <span>
                                Source Text — Chunk {activeCitation.chunk_id} (Page {activeCitation.page_number} · {activeCitation.chunk_type})
                              </span>
                              <button
                                type="button"
                                onClick={() => setExpandedCitationId(null)}
                                className="text-ink-400 hover:text-ink-700 px-1 py-0.5"
                                title="Close"
                              >
                                ✕
                              </button>
                            </div>
                            <div className="font-data text-ink-600 max-h-36 overflow-y-auto whitespace-pre-wrap leading-relaxed">
                              {activeCitation.snippet}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              </div>
                {isUser && (
                  <div className="flex h-7 w-7 shrink-0 select-none items-center justify-center rounded-full bg-ink-200 text-ink-700 text-xs font-semibold">
                    <User className="h-4 w-4" />
                  </div>
                )}
              </div>
            );
          })
        )}

        {isLoading && (
          <div className="flex gap-3 justify-start">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Bot className="h-4 w-4 animate-pulse" />
            </div>
            <div className="rounded-xl bg-ink-50/80 border border-ink-100 px-4 py-3 text-xs text-ink-500">
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-primary animate-ping" />
                Searching document OCR and synthesizing grounded answer…
              </span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </CardContent>

      {/* Input bar */}
      <div className="border-t border-ink-200 bg-ink-50/30 p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            placeholder={`Ask about ${originalFilename}…`}
            disabled={isLoading}
            className="flex-1 rounded-lg border border-ink-200 bg-white px-3.5 py-2 text-sm text-ink-900 placeholder:text-ink-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
          />
          <Button
            type="submit"
            disabled={!inputMessage.trim() || isLoading}
            size="sm"
            className="px-4"
          >
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </Card>
  );
}

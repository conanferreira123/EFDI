import { useState, useEffect, useRef } from "react";
import {
  Send,
  Sparkles,
  RotateCcw,
  Database,
  Calculator,
  FileText,
  AlertCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
} from "lucide-react";
import { chatApi, type ChatHistoryItem, type ToolCallItem, type CitationItem } from "@/services/chat";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/components/ui/toast";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { Button } from "@/components/ui/button";
import { MarkdownRenderer } from "@/components/markdown-renderer";

const PROMPT_CHIPS = [
  {
    label: "Validated Invoices Count",
    query: "How many invoices are currently in VALIDATED status?",
    icon: Database,
  },
  {
    label: "Early Payment Discount",
    query: "Calculate a 2% discount on $1320 within 10 days",
    icon: Calculator,
  },
  {
    label: "Portfolio Payment Terms",
    query: "What Incoterms and discount payment terms are documented in our portfolio?",
    icon: FileText,
  },
  {
    label: "Compound Spend & Terms",
    query: "List all invoices in status VALIDATED and check what payment discount terms apply",
    icon: Sparkles,
  },
];

export function GlobalChatPage() {
  const { user } = useAuth();
  const { push } = useToast();
  const showError = useApiErrorToast();


  const [messages, setMessages] = useState<ChatHistoryItem[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [expandedTools, setExpandedTools] = useState<Record<number, boolean>>({});
  const [expandedCitations, setExpandedCitations] = useState<Record<number, boolean>>({});

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const loadHistory = async () => {
    try {
      setInitialLoading(true);
      const history = await chatApi.getGlobalHistory();
      setMessages(history);
    } catch (err: any) {
      console.error("Failed to load global chat history", err);
    } finally {
      setInitialLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const handleSend = async (textToSend?: string) => {
    const q = (textToSend || input).trim();
    if (!q || loading) return;

    setInput("");

    // Optimistic user message
    const tempUserMsg: ChatHistoryItem = {
      id: Date.now(),
      session_id: 0,
      role: "user",
      content: q,
      citations: [],
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    setLoading(true);

    try {
      const res = await chatApi.sendGlobalMessage(q);
      const assistantMsg: ChatHistoryItem = {
        id: res.message_id,
        session_id: res.session_id,
        role: "assistant",
        content: res.content,
        tool_calls: res.tool_calls,
        citations: res.citations,
        created_at: res.created_at,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.message || "Failed to get AI response";
      showError(err, "Failed to get AI response");
      // Append an error message in chat
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          session_id: 0,
          role: "assistant",
          content: `⚠️ Error: ${detail}`,
          citations: [],
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleClearHistory = async () => {
    if (!confirm("Are you sure you want to clear your global conversation history?")) return;
    try {
      await chatApi.clearGlobalHistory();
      setMessages([]);
      push({ title: "Conversation Reset", description: "Global chat history has been cleared.", tone: "info" });
    } catch (err: any) {
      showError(err, "Failed to clear history");
    }
  };

  const toggleTools = (msgId: number) => {
    setExpandedTools((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  const toggleCitations = (msgId: number) => {
    setExpandedCitations((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col rounded-2xl border border-ink-200 bg-paper-50 shadow-sm overflow-hidden">
      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-ink-200 px-6 py-4 bg-paper-100/60">
        <div className="flex items-center gap-3">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-sm"
            style={{ backgroundImage: "var(--gradient-primary)" }}
          >
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-ink-900">EFDI Intelligence Assistant</h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-medium text-primary-800">
                <ShieldCheck className="h-3.5 w-3.5" />
                {user?.role === "FINANCE_ANALYST" ? "Role Scoped (Your Uploads)" : "Full Corpus Access"}
              </span>
            </div>
            <p className="text-xs text-ink-500">
              Enterprise-wide financial document and data intelligence
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleClearHistory}
            disabled={messages.length === 0}
            className="gap-1.5 text-xs text-ink-600 hover:text-ink-900"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset Conversation
          </Button>
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {initialLoading ? (
          <div className="flex h-48 items-center justify-center text-sm text-ink-400">
            <Clock className="mr-2 h-4 w-4 animate-spin" /> Loading assistant session...
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full max-w-lg mx-auto text-center py-12">
            <div
              className="flex h-14 w-14 items-center justify-center rounded-2xl mb-4 text-white shadow-md"
              style={{ backgroundImage: "var(--gradient-primary)" }}
            >
              <Sparkles className="h-7 w-7" />
            </div>
            <h3 className="text-lg font-semibold text-ink-900 mb-1">Ask EFDI Anything</h3>
            <p className="text-sm text-ink-500 mb-6">
              Ask compound questions combining aggregate financial data, precise settlement discounts, and
              unstructured contractual clauses.
            </p>

            {/* Prompt Chips */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full text-left">
              {PROMPT_CHIPS.map((chip, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSend(chip.query)}
                  className="flex items-start gap-2.5 p-3 rounded-xl border border-ink-200 bg-white hover:border-primary-400 hover:bg-primary-50/50 transition-all text-left shadow-2xs group"
                >
                  <chip.icon className="h-4 w-4 text-primary-600 mt-0.5 shrink-0 group-hover:scale-110 transition-transform" />
                  <div>
                    <div className="text-xs font-semibold text-ink-800">{chip.label}</div>
                    <div className="text-[11px] text-ink-500 line-clamp-1">{chip.query}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg) => {
            const isAssistant = msg.role === "assistant";
            const hasTools = msg.tool_calls && msg.tool_calls.length > 0;
            const hasCitations = msg.citations && msg.citations.length > 0;
            const toolsExpanded = !!expandedTools[msg.id];
            const citationsExpanded = !!expandedCitations[msg.id];

            return (
              <div
                key={msg.id}
                className={`flex flex-col ${isAssistant ? "items-start" : "items-end"}`}
              >
                <div className="flex items-center gap-1.5 mb-1 px-1 text-[11px] text-ink-400 font-medium">
                  {isAssistant ? (
                    <>
                      <Sparkles className="h-3 w-3 text-primary-600" />
                      <span>EFDI Multi-Tool Agent</span>
                    </>
                  ) : (
                    <span>{user?.full_name || "You"}</span>
                  )}
                </div>

                <div
                  className={`max-w-2xl rounded-2xl p-4 text-sm shadow-2xs leading-relaxed ${
                    isAssistant
                      ? "bg-white border border-ink-200 text-ink-900"
                      : "bg-seal-600 text-white rounded-br-xs"
                  }`}
                >
                  {/* Tool Execution Badges (Assistant only) */}
                  {isAssistant && hasTools && (
                    <div className="mb-3 border-b border-ink-100 pb-2.5">
                      <button
                        onClick={() => toggleTools(msg.id)}
                        className="flex items-center gap-1.5 text-xs font-medium text-ink-600 hover:text-ink-900 transition-colors"
                      >
                        {toolsExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                        <span>
                          Executed {msg.tool_calls!.length} Specialized Tool{msg.tool_calls!.length > 1 ? "s" : ""}
                        </span>
                      </button>

                      {toolsExpanded && (
                        <div className="mt-2 space-y-1.5 pl-4 border-l-2 border-primary-200">
                          {msg.tool_calls!.map((tc: ToolCallItem, tidx: number) => (
                            <div key={tidx} className="rounded-lg bg-paper-100 p-2 text-xs text-ink-700">
                              <div className="font-semibold text-primary-800 flex items-center gap-1.5">
                                {tc.tool === "database_query_tool" && <Database className="h-3.5 w-3.5" />}
                                {tc.tool === "financial_calculator_tool" && <Calculator className="h-3.5 w-3.5" />}
                                {tc.tool === "document_rag_tool" && <FileText className="h-3.5 w-3.5" />}
                                <span>{tc.tool}</span>
                              </div>
                              {tc.summary && <div className="mt-0.5 text-[11px] text-ink-600">{tc.summary}</div>}
                              {tc.sql && (
                                <code className="mt-1 block font-mono text-[10px] bg-white p-1 rounded border border-ink-200 text-ink-800 break-all">
                                  {tc.sql}
                                </code>
                              )}
                              {tc.result && typeof tc.result === "object" && (
                                <div className="mt-1 text-[11px] text-ink-700 font-mono">
                                  {JSON.stringify(tc.result)}
                                </div>
                              )}
                              {tc.error && (
                                <div className="mt-1 text-xs text-rose-600 flex items-center gap-1">
                                  <AlertCircle className="h-3 w-3" /> {tc.error}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {isAssistant ? (
                    <MarkdownRenderer content={msg.content} />
                  ) : (
                    <div className="whitespace-pre-wrap">{msg.content}</div>
                  )}

                  {/* Citations Accordion (Assistant only) */}
                  {isAssistant && hasCitations && (
                    <div className="mt-3 border-t border-ink-100 pt-2.5">
                      <button
                        onClick={() => toggleCitations(msg.id)}
                        className="flex items-center gap-1.5 text-xs font-medium text-primary-700 hover:text-primary-800"
                      >
                        {citationsExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                        <span>{msg.citations.length} Verified OCR Grounding Reference(s)</span>
                      </button>

                      {citationsExpanded && (
                        <div className="mt-2 space-y-2 pl-2">
                          {msg.citations.map((cite: CitationItem, cidx: number) => (
                            <div
                              key={cidx}
                              className="rounded-lg border border-ink-200 bg-paper-50 p-2.5 text-xs text-ink-700"
                            >
                              <div className="flex items-center justify-between text-[11px] font-medium text-ink-500 mb-1">
                                <span>
                                  Doc #{cite.document_id || "?"} · Page {cite.page_number} · {cite.chunk_type}
                                </span>
                              </div>
                              <p className="italic text-ink-600 bg-white p-1.5 rounded border border-ink-150">
                                "{cite.snippet}"
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-ink-500 italic pl-1">
            <Sparkles className="h-3.5 w-3.5 animate-spin text-primary-600" />
            <span>Coordinating tools & synthesizing grounded answer...</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Form */}
      <div className="border-t border-ink-200 bg-white p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex items-center gap-3"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything across documents, relational metrics, or settlement terms..."
            className="flex-1 rounded-xl border border-ink-200 bg-paper-50 px-4 py-2.5 text-sm text-ink-900 placeholder-ink-400 focus:border-primary-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-primary-500"
            disabled={loading}
          />
          <Button
            type="submit"
            disabled={!input.trim() || loading}
            className="gap-2 px-5 py-2.5 shadow-sm"
          >
            <Send className="h-4 w-4" />
            <span>Ask</span>
          </Button>
        </form>
      </div>
    </div>
  );
}

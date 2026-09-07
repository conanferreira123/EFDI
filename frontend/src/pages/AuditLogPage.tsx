import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { auditApi } from "@/services/admin";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import type { AuditAction } from "@/types/domain";
import type { AuditLogResponse } from "@/types/api";

const ACTION_OPTIONS: (AuditAction | "ALL")[] = [
  "ALL",
  "LOGIN_SUCCESS",
  "LOGIN_FAILED",
  "USER_REGISTERED",
  "DOCUMENT_UPLOADED",
  "DOCUMENT_DELETED",
  "OCR_RUN",
  "CLASSIFICATION_RUN",
  "EXTRACTION_RUN",
  "EXTRACTION_FIELD_CORRECTED",
  "VALIDATION_RUN",
  "APPROVAL_REQUESTED",
  "DOCUMENT_APPROVED",
  "DOCUMENT_REJECTED",
];

const ACTION_TONE: Record<string, "neutral" | "ink" | "seal" | "sage" | "clay"> = {
  LOGIN_FAILED: "clay",
  DOCUMENT_REJECTED: "clay",
  DOCUMENT_APPROVED: "sage",
  LOGIN_SUCCESS: "sage",
  APPROVAL_REQUESTED: "seal",
};

const PAGE_SIZE = 30;

export function AuditLogPage() {
  const navigate = useNavigate();
  const showError = useApiErrorToast();

  const [items, setItems] = useState<AuditLogResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [actionFilter, setActionFilter] = useState<AuditAction | "ALL">("ALL");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    auditApi
      .list({
        action: actionFilter === "ALL" ? undefined : actionFilter,
        skip,
        limit: PAGE_SIZE,
      })
      .then((response) => {
        if (cancelled) return;
        setItems(response.items);
        setTotal(response.total);
      })
      .catch((err) => !cancelled && showError(err, "Could not load audit logs"))
      .finally(() => !cancelled && setIsLoading(false));

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actionFilter, skip]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-1">
        {ACTION_OPTIONS.map((action) => (
          <button
            key={action}
            onClick={() => {
              setIsLoading(true);
              setSkip(0);
              setActionFilter(action);
            }}
            className={`whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              actionFilter === action
                ? "bg-ink-900 text-paper-50"
                : "bg-ink-100 text-ink-600 hover:bg-ink-200"
            }`}
          >
            {action === "ALL" ? "All actions" : action.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      <div className="ledger-rule" />

      <div className="overflow-hidden rounded-lg border border-ink-200">
        <table className="w-full text-sm">
          <thead className="bg-ink-50 text-left text-xs font-medium uppercase tracking-wide text-ink-500">
            <tr>
              <th className="px-4 py-3">When</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Document</th>
              <th className="px-4 py-3">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {isLoading ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-ink-400">
                  Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-ink-400">
                  No matching audit entries.
                </td>
              </tr>
            ) : (
              items.map((entry) => (
                <tr key={entry.id} className="align-top">
                  <td className="font-data px-4 py-2.5 text-xs text-ink-500">
                    {formatDateTime(entry.created_at)}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone={ACTION_TONE[entry.action] ?? "neutral"}>
                      {entry.action.replace(/_/g, " ")}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-ink-700">
                    {entry.user?.full_name ?? <span className="italic text-ink-400">unknown</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    {entry.document_id ? (
                      <button
                        className="font-data text-xs text-ink-600 underline-offset-2 hover:underline"
                        onClick={() => navigate(`/documents/${entry.document_id}`)}
                      >
                        #{entry.document_id}
                      </button>
                    ) : (
                      <span className="text-ink-300">—</span>
                    )}
                  </td>
                  <td className="max-w-xs px-4 py-2.5 text-xs text-ink-500">
                    {entry.details ? (
                      <code className="font-data break-words">{JSON.stringify(entry.details)}</code>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm text-ink-500">
        <span className="font-data">{total} entries</span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={skip === 0}
            onClick={() => {
              setIsLoading(true);
              setSkip(Math.max(0, skip - PAGE_SIZE));
            }}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={skip + PAGE_SIZE >= total}
            onClick={() => {
              setIsLoading(true);
              setSkip(skip + PAGE_SIZE);
            }}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

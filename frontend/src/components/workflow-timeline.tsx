import { formatDateTime } from "@/lib/format";
import type { WorkflowHistoryResponse } from "@/types/api";

const ACTION_LABEL: Record<string, string> = {
  REQUEST_APPROVAL: "Requested approval",
  APPROVE: "Approved",
  REJECT: "Rejected",
};

export function WorkflowTimeline({ history }: { history: WorkflowHistoryResponse[] }) {
  if (history.length === 0) {
    return <p className="text-sm text-ink-400">No workflow activity yet.</p>;
  }

  return (
    <ol className="space-y-4 border-l border-ink-200 pl-5">
      {history.map((entry) => (
        <li key={entry.id} className="relative">
          <span className="absolute -left-[27px] top-1 h-2.5 w-2.5 rounded-full bg-ink-600" />
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-medium text-ink-900">
              {ACTION_LABEL[entry.action] ?? entry.action}
            </span>
            <span className="font-data text-xs text-ink-400">{formatDateTime(entry.created_at)}</span>
          </div>
          <p className="text-xs text-ink-500">
            {entry.performed_by_user?.full_name ?? `User #${entry.performed_by}`} ·{" "}
            {entry.from_status} → {entry.to_status}
          </p>
          {entry.comment && (
            <p className="mt-1 rounded-md bg-ink-50 px-3 py-2 text-sm text-ink-700">{entry.comment}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

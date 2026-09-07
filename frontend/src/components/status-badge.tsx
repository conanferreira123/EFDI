import { cn } from "@/lib/utils";
import { DOCUMENT_STATUS_LABELS, type DocumentStatus } from "@/types/domain";

// Modern soft-fill pill with a colored dot -- Linear/Stripe-style
// status indicator, not a stamped/inked look.
const STATUS_STYLE: Record<DocumentStatus, { bg: string; text: string; dot: string }> = {
  UPLOADED: { bg: "bg-slate-warm-100", text: "text-slate-warm-500", dot: "bg-slate-warm-500" },
  OCR_COMPLETED: { bg: "bg-ink-100", text: "text-ink-600", dot: "bg-ink-500" },
  EXTRACTED: { bg: "bg-ink-100", text: "text-ink-600", dot: "bg-ink-500" },
  VALIDATED: { bg: "bg-ink-100", text: "text-ink-700", dot: "bg-ink-600" },
  PENDING_APPROVAL: { bg: "bg-seal-100", text: "text-seal-600", dot: "bg-seal-500" },
  APPROVED: { bg: "bg-sage-100", text: "text-sage-600", dot: "bg-sage-500" },
  REJECTED: { bg: "bg-clay-100", text: "text-clay-600", dot: "bg-clay-500" },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const style = STATUS_STYLE[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        style.bg,
        style.text
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
      {DOCUMENT_STATUS_LABELS[status]}
    </span>
  );
}

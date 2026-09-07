import { DOCUMENT_TYPE_LABELS, type DocumentType } from "@/types/domain";

export function ClassificationScoresBreakdown({
  scores,
  predictedType,
}: {
  scores: Record<string, number>;
  predictedType: DocumentType;
}) {
  const entries = Object.entries(scores).sort(([, a], [, b]) => b - a);
  const maxScore = Math.max(...entries.map(([, score]) => score), 0.01);

  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="space-y-1.5">
      {entries.map(([type, score]) => {
        const isWinner = type === predictedType;
        return (
          <div key={type} className="flex items-center gap-3 text-xs">
            <span
              className={`w-32 shrink-0 truncate ${isWinner ? "font-semibold text-ink-900" : "text-ink-500"}`}
            >
              {DOCUMENT_TYPE_LABELS[type as DocumentType] ?? type}
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-100">
              <div
                className={`h-full rounded-full ${isWinner ? "bg-seal-500" : "bg-ink-300"}`}
                style={{ width: `${(score / maxScore) * 100}%` }}
              />
            </div>
            <span className="font-data w-10 shrink-0 text-right text-ink-400">
              {score.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

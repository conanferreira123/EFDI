import { formatConfidence } from "@/lib/format";
import { cn } from "@/lib/utils";

export function ConfidenceBar({ value, className }: { value: number; className?: string }) {
  const tone = value >= 0.8 ? "bg-sage-500" : value >= 0.5 ? "bg-seal-500" : "bg-clay-500";

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-ink-100">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${value * 100}%` }} />
      </div>
      <span className="font-data text-xs text-ink-500">{formatConfidence(value)}</span>
    </div>
  );
}

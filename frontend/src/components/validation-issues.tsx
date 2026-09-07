import { AlertTriangle, OctagonAlert, CheckCircle2 } from "lucide-react";
import type { ValidationIssue } from "@/types/api";

export function ValidationIssuesList({
  issues,
  isValid,
}: {
  issues: ValidationIssue[];
  isValid: boolean;
}) {
  if (issues.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md bg-sage-50 px-4 py-3 text-sm text-sage-600">
        <CheckCircle2 className="h-4 w-4" />
        No issues found. This document is clean.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {!isValid && (
        <p className="text-sm text-clay-600">
          This document has blocking errors and cannot advance to validated status until they're
          resolved.
        </p>
      )}
      {issues.map((issue, i) => (
        <div
          key={i}
          className={`flex items-start gap-2 rounded-md px-4 py-2.5 text-sm ${
            issue.severity === "ERROR" ? "bg-clay-50 text-clay-700" : "bg-seal-50 text-seal-600"
          }`}
        >
          {issue.severity === "ERROR" ? (
            <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          <div>
            <span className="font-medium">{issue.field_key ? `${issue.field_key}: ` : ""}</span>
            {issue.message}
          </div>
        </div>
      ))}
    </div>
  );
}

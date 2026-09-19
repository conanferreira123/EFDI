import { AlertTriangle, OctagonAlert, CheckCircle2, ShieldAlert, AlertCircle } from "lucide-react";
import type { ValidationIssue } from "@/types/api";
import { fieldLabel } from "@/lib/format";

export function ValidationIssuesList({
  issues,
  isValid,
}: {
  issues: ValidationIssue[];
  isValid: boolean;
}) {
  const errors = issues.filter((i) => i.severity === "ERROR");
  const warnings = issues.filter((i) => i.severity === "WARNING");

  return (
    <div className="space-y-4">
      {/* 1. Status Overview Header Banner */}
      {isValid && issues.length === 0 ? (
        <div className="flex items-center gap-3 rounded-lg bg-sage-50 border border-sage-200 p-4 text-sm text-sage-800 shadow-xs">
          <CheckCircle2 className="h-5 w-5 text-sage-600 shrink-0" />
          <div>
            <span className="font-semibold block">Validation Status: VALID</span>
            <span className="text-xs text-sage-700">
              All mandatory processing core fields are present, format validations passed, and financial reconciliation balances within tolerance.
            </span>
          </div>
        </div>
      ) : !isValid ? (
        <div className="flex items-center gap-3 rounded-lg bg-clay-50 border border-clay-200 p-4 text-sm text-clay-800 shadow-xs">
          <OctagonAlert className="h-5 w-5 text-clay-600 shrink-0" />
          <div>
            <span className="font-semibold block">Validation Status: ACTION REQUIRED (Blocking Errors)</span>
            <span className="text-xs text-clay-700">
              This invoice contains {errors.length} blocking error{errors.length > 1 ? "s" : ""}. Review and correct mandatory fields to proceed to approval.
            </span>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-lg bg-seal-50 border border-seal-200 p-4 text-sm text-seal-800 shadow-xs">
          <AlertCircle className="h-5 w-5 text-seal-600 shrink-0" />
          <div>
            <span className="font-semibold block">Validation Status: VALID (With Review Warnings)</span>
            <span className="text-xs text-seal-700">
              Mandatory core fields are satisfied, but {warnings.length} advisory warning{warnings.length > 1 ? "s" : ""} or arithmetic discrepancies require AP attention.
            </span>
          </div>
        </div>
      )}

      {/* 2. Blocking Errors Section */}
      {errors.length > 0 && (
        <div className="rounded-xl border border-clay-200 bg-white p-4 shadow-xs space-y-3">
          <div className="flex items-center gap-2 text-clay-900 font-semibold text-sm border-b border-clay-100 pb-2">
            <ShieldAlert className="h-4 w-4 text-clay-600" />
            <span>Blocking Errors ({errors.length})</span>
          </div>
          <div className="space-y-2">
            {errors.map((issue, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2.5 rounded-lg bg-clay-50/70 p-3 text-xs text-clay-800 border border-clay-200"
              >
                <OctagonAlert className="h-4 w-4 text-clay-600 mt-0.5 shrink-0" />
                <div className="space-y-0.5">
                  <div className="font-semibold text-clay-950">
                    {issue.field_key ? fieldLabel(issue.field_key) : "Document-Level Rule"}
                    <span className="ml-2 inline-block rounded bg-clay-200/60 px-1.5 py-0.5 text-[10px] font-mono uppercase text-clay-800">
                      {issue.rule_type}
                    </span>
                  </div>
                  <div className="text-clay-700">{issue.message}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 3. Review Warnings & Discrepancies Section */}
      {warnings.length > 0 && (
        <div className="rounded-xl border border-seal-200 bg-white p-4 shadow-xs space-y-3">
          <div className="flex items-center gap-2 text-seal-900 font-semibold text-sm border-b border-seal-100 pb-2">
            <AlertTriangle className="h-4 w-4 text-seal-600" />
            <span>Advisory Warnings & Arithmetic Mismatches ({warnings.length})</span>
          </div>
          <div className="space-y-2">
            {warnings.map((issue, idx) => {
              const isMismatch = issue.message.toLowerCase().includes("mismatch") || issue.message.toLowerCase().includes("differ");
              return (
                <div
                  key={idx}
                  className={`flex items-start gap-2.5 rounded-lg p-3 text-xs border ${
                    isMismatch
                      ? "bg-seal-50/80 border-seal-300 text-seal-900"
                      : "bg-ink-50/60 border-ink-200 text-ink-800"
                  }`}
                >
                  <AlertTriangle className="h-4 w-4 text-seal-600 mt-0.5 shrink-0" />
                  <div className="space-y-0.5">
                    <div className="font-semibold text-ink-950">
                      {issue.field_key ? fieldLabel(issue.field_key) : "Accounting Consistency"}
                      <span className="ml-2 inline-block rounded bg-ink-200/60 px-1.5 py-0.5 text-[10px] font-mono uppercase text-ink-700">
                        {issue.rule_type}
                      </span>
                    </div>
                    <div className="text-ink-700 leading-relaxed">{issue.message}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

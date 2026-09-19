import { useState } from "react";
import { Pencil, Check, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ConfidenceBar } from "@/components/confidence-bar";
import { extractionApi } from "@/services/pipeline";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useToast } from "@/components/ui/toast";
import { fieldLabel } from "@/lib/format";
import type { CanonicalNPO, ExtractedField } from "@/types/api";
import { NPOInvoiceReview } from "@/components/npo-invoice-review";

interface ExtractionFieldsProps {
  documentId: number;
  documentType?: string;
  fields: Record<string, ExtractedField>;
  canonical?: CanonicalNPO | null;
  onFieldUpdated: () => void;
}

export function ExtractionFields({
  documentId,
  documentType,
  fields,
  canonical,
  onFieldUpdated,
}: ExtractionFieldsProps) {
  const showError = useApiErrorToast();
  const { push } = useToast();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  // If this is an NPO invoice or has canonical representation, render the AP-friendly NPO review
  const isNpo = (documentType || "").toUpperCase() === "NPO" || Boolean(canonical) || Boolean(fields.canonical);
  if (isNpo) {
    return (
      <NPOInvoiceReview
        documentId={documentId}
        fields={fields}
        canonical={canonical || (fields.canonical?.value as CanonicalNPO)}
        onFieldUpdated={onFieldUpdated}
      />
    );
  }

  const entries = Object.entries(fields).filter(([key, field]) => {
    if (key === "line_items" || key === "_line_items" || key === "taxes" || key === "canonical") return false;
    if (Array.isArray(field)) return false;
    if (!field || typeof field !== "object") return false;
    return true;
  });

  async function handleSave(key: string) {
    setIsSaving(true);
    try {
      await extractionApi.updateField(documentId, key, draftValue);
      push({ tone: "success", title: "Field updated", description: fieldLabel(key) });
      setEditingKey(null);
      onFieldUpdated();
    } catch (err) {
      showError(err, "Could not update field");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border border-ink-200">
      <table className="w-full text-sm">
        <thead className="bg-ink-50 text-left text-xs font-medium uppercase tracking-wide text-ink-500">
          <tr>
            <th className="px-4 py-3">Field</th>
            <th className="px-4 py-3">Value</th>
            <th className="px-4 py-3">Confidence</th>
            <th className="px-4 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">
          {entries.map(([key, field]) => (
            <tr key={key} className={!field.is_found ? "bg-clay-50/40" : undefined}>
              <td className="px-4 py-2.5 font-medium text-ink-700">{fieldLabel(key)}</td>
              <td className="px-4 py-2.5">
                {editingKey === key ? (
                  <Input
                    autoFocus
                    value={draftValue}
                    onChange={(e) => setDraftValue(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSave(key)}
                    className="h-8"
                  />
                ) : (
                  <span className={`font-data ${field.value == null ? "italic text-ink-400" : "text-ink-900"}`}>
                    {field.value != null ? String(field.value) : "Not found"}
                  </span>
                )}
              </td>
              <td className="px-4 py-2.5">
                <ConfidenceBar value={field.confidence} />
              </td>
              <td className="px-4 py-2.5 text-right">
                {editingKey === key ? (
                  <div className="flex justify-end gap-1">
                    <Button size="icon" variant="ghost" disabled={isSaving} onClick={() => handleSave(key)}>
                      <Check className="h-4 w-4 text-sage-500" />
                    </Button>
                    <Button size="icon" variant="ghost" onClick={() => setEditingKey(null)}>
                      <X className="h-4 w-4 text-ink-400" />
                    </Button>
                  </div>
                ) : (
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => {
                      setEditingKey(key);
                      setDraftValue(field.value != null ? String(field.value) : "");
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5 text-ink-400" />
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

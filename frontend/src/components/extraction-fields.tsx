import { useState } from "react";
import { Pencil, Check, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ConfidenceBar } from "@/components/confidence-bar";
import { extractionApi } from "@/services/pipeline";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useToast } from "@/components/ui/toast";
import type { ExtractedField } from "@/types/api";

interface ExtractionFieldsProps {
  documentId: number;
  fields: Record<string, ExtractedField>;
  onFieldUpdated: () => void;
}

function fieldLabel(key: string): string {
  return key
    .split("_")
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

export function ExtractionFields({ documentId, fields, onFieldUpdated }: ExtractionFieldsProps) {
  const showError = useApiErrorToast();
  const { push } = useToast();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const entries = Object.entries(fields);

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
                  <span className={`font-data ${!field.value ? "italic text-ink-400" : "text-ink-900"}`}>
                    {field.value ?? "Not found"}
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
                      setDraftValue(field.value ?? "");
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

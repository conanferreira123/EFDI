import { useState } from "react";
import { Check, X, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { classificationApi } from "@/services/pipeline";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useToast } from "@/components/ui/toast";
import { DOCUMENT_TYPE_LABELS, type DocumentType } from "@/types/domain";

interface ClassificationCorrectionProps {
  documentId: number;
  predictedType: DocumentType;
  onCorrected: () => void;
}

export function ClassificationCorrection({
  documentId,
  predictedType,
  onCorrected,
}: ClassificationCorrectionProps) {
  const showError = useApiErrorToast();
  const { push } = useToast();
  const [isEditing, setIsEditing] = useState(false);
  const [draftType, setDraftType] = useState<DocumentType>(predictedType);
  const [isSaving, setIsSaving] = useState(false);

  async function handleSave() {
    setIsSaving(true);
    try {
      await classificationApi.correct(documentId, draftType);
      push({
        tone: "success",
        title: "Classification corrected",
        description: DOCUMENT_TYPE_LABELS[draftType],
      });
      setIsEditing(false);
      onCorrected();
    } catch (err) {
      showError(err, "Could not correct classification");
    } finally {
      setIsSaving(false);
    }
  }

  if (!isEditing) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setIsEditing(true)}>
        <Pencil className="mr-1.5 h-3.5 w-3.5" />
        Correct type
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Select value={draftType} onValueChange={(v) => setDraftType(v as DocumentType)}>
        <SelectTrigger className="w-56">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(DOCUMENT_TYPE_LABELS).map(([value, label]) => (
            <SelectItem key={value} value={value}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button size="sm" onClick={handleSave} disabled={isSaving}>
        <Check className="h-3.5 w-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          setIsEditing(false);
          setDraftType(predictedType);
        }}
        disabled={isSaving}
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

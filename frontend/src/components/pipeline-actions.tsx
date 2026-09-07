import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ocrApi, classificationApi, extractionApi, validationApi } from "@/services/pipeline";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useToast } from "@/components/ui/toast";
import type { DocumentStatus } from "@/types/domain";

interface PipelineActionsProps {
  documentId: number;
  status: DocumentStatus;
  onComplete: () => void;
}

const NEXT_ACTION: Record<DocumentStatus, { label: string; run: (id: number) => Promise<unknown> } | null> = {
  UPLOADED: { label: "Run OCR", run: (id) => ocrApi.run(id) },
  OCR_COMPLETED: { label: "Classify document", run: (id) => classificationApi.run(id) },
  EXTRACTED: { label: "Validate", run: (id) => validationApi.run(id) },
  VALIDATED: null,
  PENDING_APPROVAL: null,
  APPROVED: null,
  // A rejected document isn't a dead end -- once corrections are made
  // (via the Extraction tab's field-correction UI), re-running
  // validation is what lets it become VALIDATED again and therefore
  // eligible for REQUEST_APPROVAL a second time. ValidationService
  // doesn't require any particular starting status to run, so this is
  // always safe to offer.
  REJECTED: { label: "Re-run Validation", run: (id) => validationApi.run(id) },
};

export function PipelineActions({ documentId, status, onComplete }: PipelineActionsProps) {
  const showError = useApiErrorToast();
  const { push } = useToast();
  const [isRunning, setIsRunning] = useState(false);

  // OCR_COMPLETED can mean "classified but not yet extracted" too --
  // the status only advances again at EXTRACTED, so offer "Extract
  // fields" once classification has actually produced a result. This
  // mirrors the backend's own design decision (Phase 5): classification
  // alone doesn't move Document.status forward.
  const action = NEXT_ACTION[status];

  async function handleRun(run: (id: number) => Promise<unknown>, label: string) {
    setIsRunning(true);
    try {
      await run(documentId);
      push({ tone: "success", title: `${label} complete` });
      onComplete();
    } catch (err) {
      showError(err, `${label} failed`);
    } finally {
      setIsRunning(false);
    }
  }

  if (status === "OCR_COMPLETED") {
    return (
      <div className="flex gap-2">
        <Button
          variant="outline"
          disabled={isRunning}
          onClick={() => handleRun((id) => classificationApi.run(id), "Classification")}
        >
          Classify document
        </Button>
        <Button
          disabled={isRunning}
          onClick={() => handleRun((id) => extractionApi.run(id, "hybrid"), "Extraction")}
        >
          Extract fields
        </Button>
      </div>
    );
  }

  if (!action) return null;

  return (
    <Button disabled={isRunning} onClick={() => handleRun(action.run, action.label)}>
      {isRunning ? "Running…" : action.label}
    </Button>
  );
}

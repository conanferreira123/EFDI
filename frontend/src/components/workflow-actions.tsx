import { useState } from "react";
import { CheckCircle2, XCircle, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { workflowApi } from "@/services/workflow";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/context/AuthContext";
import type { DocumentStatus } from "@/types/domain";

const APPROVER_ROLES = ["FINANCE_MANAGER", "AUDITOR", "ADMIN"];

interface WorkflowActionsProps {
  documentId: number;
  status: DocumentStatus;
  onComplete: () => void;
}

export function WorkflowActions({ documentId, status, onComplete }: WorkflowActionsProps) {
  const { user } = useAuth();
  const showError = useApiErrorToast();
  const { push } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [rejectComment, setRejectComment] = useState("");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [approveComment, setApproveComment] = useState("");
  const [approveOpen, setApproveOpen] = useState(false);

  const canApprove = user && APPROVER_ROLES.includes(user.role);

  if (status === "VALIDATED") {
    return (
      <Button
        disabled={isSubmitting}
        onClick={async () => {
          setIsSubmitting(true);
          try {
            await workflowApi.requestApproval(documentId);
            push({ tone: "success", title: "Approval requested" });
            onComplete();
          } catch (err) {
            showError(err, "Could not request approval");
          } finally {
            setIsSubmitting(false);
          }
        }}
      >
        <Send className="h-4 w-4" />
        Request approval
      </Button>
    );
  }

  if (status === "PENDING_APPROVAL" && canApprove) {
    return (
      <div className="flex gap-2">
        <Dialog open={approveOpen} onOpenChange={setApproveOpen}>
          <DialogTrigger asChild>
            <Button>
              <CheckCircle2 className="h-4 w-4" />
              Approve
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Approve document</DialogTitle>
              <DialogDescription>A comment is optional but helpful for the record.</DialogDescription>
            </DialogHeader>
            <Label htmlFor="approve-comment">Comment (optional)</Label>
            <Textarea
              id="approve-comment"
              className="mt-1.5"
              rows={3}
              value={approveComment}
              onChange={(e) => setApproveComment(e.target.value)}
            />
            <DialogFooter>
              <Button variant="outline" onClick={() => setApproveOpen(false)}>
                Cancel
              </Button>
              <Button
                disabled={isSubmitting}
                onClick={async () => {
                  setIsSubmitting(true);
                  try {
                    await workflowApi.approve(documentId, approveComment);
                    push({ tone: "success", title: "Document approved" });
                    setApproveOpen(false);
                    setApproveComment("");
                    onComplete();
                  } catch (err) {
                    showError(err, "Could not approve");
                  } finally {
                    setIsSubmitting(false);
                  }
                }}
              >
                Approve
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
          <DialogTrigger asChild>
            <Button variant="destructive">
              <XCircle className="h-4 w-4" />
              Reject
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Reject document</DialogTitle>
              <DialogDescription>
                A comment is required so the submitter knows what to fix.
              </DialogDescription>
            </DialogHeader>
            <Label htmlFor="reject-comment">Comment</Label>
            <Textarea
              id="reject-comment"
              className="mt-1.5"
              rows={3}
              value={rejectComment}
              onChange={(e) => setRejectComment(e.target.value)}
              placeholder="What needs to be corrected before this can be resubmitted?"
            />
            <DialogFooter>
              <Button variant="outline" onClick={() => setRejectOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                disabled={isSubmitting || !rejectComment.trim()}
                onClick={async () => {
                  setIsSubmitting(true);
                  try {
                    await workflowApi.reject(documentId, rejectComment);
                    push({ tone: "info", title: "Document rejected" });
                    setRejectOpen(false);
                    setRejectComment("");
                    onComplete();
                  } catch (err) {
                    showError(err, "Could not reject");
                  } finally {
                    setIsSubmitting(false);
                  }
                }}
              >
                Reject
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  if (status === "REJECTED") {
    return (
      <p className="text-sm text-ink-500">
        This document was rejected. Re-run validation once corrections are made to resubmit it for
        approval.
      </p>
    );
  }

  return null;
}

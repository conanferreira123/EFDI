import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, XCircle, FolderUp } from "lucide-react";
import { Dropzone } from "@/components/dropzone";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { documentsApi } from "@/services/documents";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useToast } from "@/components/ui/toast";
import type { BulkIntakeItemResult } from "@/types/api";

const ACCEPTED_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg"];

// Non-standard but universally supported by Chromium/Firefox/Safari:
// makes the native file picker let the user select an entire folder
// instead of individual files. The browser still only ever hands us
// the files themselves (as File objects) -- there is no way for a
// browser to give a server a filesystem path to go scan on its own,
// so this reads every file inside the chosen folder client-side and
// uploads them through the exact same bulk-upload path as picking
// files individually, just with one click instead of many.
interface DirectoryInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  webkitdirectory?: string;
  directory?: string;
}

export function UploadPage() {
  const navigate = useNavigate();
  const showError = useApiErrorToast();
  const { push } = useToast();
  const folderInputRef = useRef<HTMLInputElement>(null);

  const [isUploading, setIsUploading] = useState(false);
  const [results, setResults] = useState<BulkIntakeItemResult[] | null>(null);

  async function handleFiles(files: File[]) {
    setIsUploading(true);
    setResults(null);
    try {
      if (files.length === 1) {
        const result = await documentsApi.upload(files[0]);
        push({ tone: "success", title: "Uploaded", description: result.original_filename });
        navigate(`/documents/${result.id}`);
        return;
      }

      const bulkResult = await documentsApi.bulkUpload(files);
      setResults(bulkResult.results);
      push({
        tone: bulkResult.failed === 0 ? "success" : "info",
        title: `${bulkResult.succeeded} of ${bulkResult.total_files} uploaded`,
        description: bulkResult.failed > 0 ? `${bulkResult.failed} file(s) failed — see details below.` : undefined,
      });
    } catch (err) {
      showError(err, "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }

  function handleFolderSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const allFiles = Array.from(e.target.files ?? []);
    const supported = allFiles.filter((f) =>
      ACCEPTED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext))
    );
    e.target.value = "";

    if (supported.length === 0) {
      push({
        tone: "info",
        title: "No supported files found",
        description: "That folder didn't contain any PDF, PNG, or JPG files.",
      });
      return;
    }
    handleFiles(supported);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Upload documents</CardTitle>
          <CardDescription>
            Drop one file for immediate processing, several at once for bulk intake, or select an
            entire folder below.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Dropzone multiple onFiles={handleFiles} disabled={isUploading} />

          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-ink-100" />
            <span className="text-xs font-medium uppercase tracking-wide text-ink-400">or</span>
            <div className="h-px flex-1 bg-ink-100" />
          </div>

          <Button
            variant="outline"
            className="w-full"
            disabled={isUploading}
            onClick={() => folderInputRef.current?.click()}
          >
            <FolderUp className="mr-2 h-4 w-4" />
            Select a folder to upload
          </Button>
          <input
            ref={folderInputRef}
            type="file"
            multiple
            webkitdirectory=""
            directory=""
            {...({} as DirectoryInputProps)}
            className="hidden"
            onChange={handleFolderSelected}
          />
        </CardContent>
      </Card>

      {results && (
        <Card>
          <CardHeader>
            <CardTitle>Intake results</CardTitle>
            <CardDescription>
              {results.filter((r) => r.success).length} succeeded, {results.filter((r) => !r.success).length}{" "}
              failed
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {results.map((r, i) => (
              <div
                key={`${r.filename}-${i}`}
                className="flex items-center justify-between rounded-md border border-ink-100 px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  {r.success ? (
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-sage-500" />
                  ) : (
                    <XCircle className="h-4 w-4 shrink-0 text-clay-500" />
                  )}
                  <span className="font-medium text-ink-900">{r.filename}</span>
                </div>
                {r.success ? (
                  <button
                    onClick={() => navigate(`/documents/${r.document_id}`)}
                    className="text-xs font-medium text-ink-600 underline-offset-2 hover:underline"
                  >
                    View document
                  </button>
                ) : (
                  <span className="text-xs text-clay-500">{r.error}</span>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

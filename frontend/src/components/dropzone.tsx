import { useCallback, useState } from "react";
import { UploadCloud } from "lucide-react";
import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = ["application/pdf", "image/png", "image/jpeg"];

interface DropzoneProps {
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

export function Dropzone({ multiple = false, onFiles, disabled }: DropzoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLLabelElement>) => {
      e.preventDefault();
      setIsDragOver(false);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files).filter((f) => ACCEPTED_TYPES.includes(f.type));
      if (files.length > 0) onFiles(multiple ? files : [files[0]]);
    },
    [disabled, multiple, onFiles]
  );

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-14 text-center transition-colors",
        isDragOver ? "border-seal-500 bg-seal-50" : "border-ink-300 bg-ink-50 hover:border-ink-400",
        disabled && "cursor-not-allowed opacity-50"
      )}
    >
      <UploadCloud className="h-8 w-8 text-ink-400" />
      <div>
        <p className="text-sm font-medium text-ink-900">
          Drop {multiple ? "files" : "a file"} here, or click to browse
        </p>
        <p className="mt-1 text-xs text-ink-400">PDF, PNG, or JPG — up to 25MB each</p>
      </div>
      <input
        type="file"
        multiple={multiple}
        accept={ACCEPTED_TYPES.join(",")}
        disabled={disabled}
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onFiles(files);
          e.target.value = "";
        }}
      />
    </label>
  );
}

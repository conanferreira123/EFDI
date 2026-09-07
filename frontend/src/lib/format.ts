import { format, formatDistanceToNow } from "date-fns";

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateTime(isoString: string): string {
  return format(new Date(isoString), "dd MMM yyyy, HH:mm");
}

export function formatRelative(isoString: string): string {
  return formatDistanceToNow(new Date(isoString), { addSuffix: true });
}

export function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

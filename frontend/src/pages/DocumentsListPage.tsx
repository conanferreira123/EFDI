import { Fragment, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, FileText, ChevronRight, Folder, Clock } from "lucide-react";
import { documentsApi } from "@/services/documents";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { StatusBadge } from "@/components/status-badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatFileSize, formatDateTime } from "@/lib/format";
import { DOCUMENT_TYPE_LABELS, type DocumentStatus, type DocumentType } from "@/types/domain";
import type { DocumentListItem } from "@/types/api";

const STATUS_FILTERS: (DocumentStatus | "ALL")[] = [
  "ALL",
  "UPLOADED",
  "OCR_COMPLETED",
  "EXTRACTED",
  "VALIDATED",
  "PENDING_APPROVAL",
  "APPROVED",
  "REJECTED",
];

const STATUS_ACCENT: Record<DocumentStatus, string> = {
  UPLOADED: "var(--color-slate-warm-500)",
  OCR_COMPLETED: "var(--color-ink-500)",
  EXTRACTED: "var(--color-ink-500)",
  VALIDATED: "var(--color-ink-600)",
  PENDING_APPROVAL: "var(--color-seal-500)",
  APPROVED: "var(--color-sage-500)",
  REJECTED: "var(--color-clay-500)",
};

// 200 = the backend's max allowed limit (see routers/documents.py).
// Deliberately large rather than a typical 20-per-page: folder
// grouping happens client-side on whatever page is fetched, so a
// small page size would split a folder's files across multiple pages
// whenever a folder has more files than fit on one page.
const PAGE_SIZE = 200;

interface StatCounts {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
}

// A document uploaded via "Select a folder to upload" carries its
// source folder as a "folder/filename.ext" prefix in original_filename
// (the browser includes the relative path for directory-selected
// files) -- so folders can be grouped purely by parsing that, with no
// backend change needed. A document with no "/" in its filename was
// uploaded individually and stays a normal top-level row.
interface FolderGroup {
  folderName: string;
  items: DocumentListItem[];
}

function groupByFolder(items: DocumentListItem[]): { folders: FolderGroup[]; ungrouped: DocumentListItem[] } {
  const folderMap = new Map<string, DocumentListItem[]>();
  const ungrouped: DocumentListItem[] = [];
  for (const item of items) {
    const slashIndex = item.original_filename.lastIndexOf("/");
    if (slashIndex > 0) {
      const folderName = item.original_filename.slice(0, slashIndex);
      if (!folderMap.has(folderName)) folderMap.set(folderName, []);
      folderMap.get(folderName)!.push(item);
    } else {
      ungrouped.push(item);
    }
  }
  const folders = Array.from(folderMap.entries()).map(([folderName, folderItems]) => ({
    folderName,
    items: folderItems,
  }));
  return { folders, ungrouped };
}

function basename(filename: string): string {
  const idx = filename.lastIndexOf("/");
  return idx >= 0 ? filename.slice(idx + 1) : filename;
}

export function DocumentsListPage() {
  const navigate = useNavigate();
  const showError = useApiErrorToast();

  const [items, setItems] = useState<DocumentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [filenameQuery, setFilenameQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | "ALL">("ALL");
  const [isLoading, setIsLoading] = useState(true);
  const [stats, setStats] = useState<StatCounts | null>(null);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [recentlyViewed, setRecentlyViewed] = useState<DocumentListItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    documentsApi
      .getRecentlyViewed()
      .then((docs) => {
        if (!cancelled) setRecentlyViewed(docs);
      })
      .catch(() => {
        /* fail silently if not loaded */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    documentsApi
      .list({
        filename: filenameQuery || undefined,
        status: statusFilter === "ALL" ? undefined : statusFilter,
        skip,
        limit: PAGE_SIZE,
      })
      .then((response) => {
        if (cancelled) return;
        setItems(response.items);
        setTotal(response.total);
      })
      .catch((err) => !cancelled && showError(err, "Could not load documents"))
      .finally(() => !cancelled && setIsLoading(false));

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filenameQuery, statusFilter, skip]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      documentsApi.list({ skip: 0, limit: 1 }),
      documentsApi.list({ status: "PENDING_APPROVAL", skip: 0, limit: 1 }),
      documentsApi.list({ status: "APPROVED", skip: 0, limit: 1 }),
      documentsApi.list({ status: "REJECTED", skip: 0, limit: 1 }),
    ])
      .then(([all, pending, approved, rejected]) => {
        if (cancelled) return;
        setStats({
          total: all.total,
          pending: pending.total,
          approved: approved.total,
          rejected: rejected.total,
        });
      })
      .catch(() => {
        /* nice-to-have, not core functionality */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleFolder(name: string) {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const { folders, ungrouped } = groupByFolder(items);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 divide-x divide-ink-200 rounded-2xl border border-ink-100 bg-paper-50">
        {(
          [
            { label: "Total", value: stats?.total, color: "var(--color-ink-900)" },
            { label: "Pending approval", value: stats?.pending, color: "var(--color-seal-500)" },
            { label: "Approved", value: stats?.approved, color: "var(--color-sage-500)" },
            { label: "Rejected", value: stats?.rejected, color: "var(--color-clay-500)" },
          ] as const
        ).map((stat) => (
          <div key={stat.label} className="flex flex-col items-center gap-1 px-4 py-5">
            <span className="text-3xl font-semibold leading-none" style={{ color: stat.color }}>
              {stat.value ?? "—"}
            </span>
            <span className="font-data text-[11px] uppercase tracking-wider text-ink-500">
              {stat.label}
            </span>
          </div>
        ))}
      </div>
      {recentlyViewed.length > 0 && (
        <div className="space-y-2.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-500">
            <Clock className="h-3.5 w-3.5 text-ink-400" />
            <span>Recently Viewed</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {recentlyViewed.map((doc) => (
              <div
                key={doc.id}
                onClick={() => navigate(`/documents/${doc.id}`)}
                className="group flex items-center rounded-xl border border-ink-100 bg-paper-50 p-3 cursor-pointer transition-all hover:border-ink-300 hover:shadow-xs min-w-0"
                style={{ borderLeft: `3px solid ${STATUS_ACCENT[doc.status]}` }}
              >
                <div className="flex items-center gap-1.5 overflow-hidden min-w-0">
                  <FileText className="h-3.5 w-3.5 shrink-0 text-ink-400 group-hover:text-ink-600" />
                  <span
                    className="truncate text-xs font-medium text-ink-900"
                    title={doc.original_filename}
                  >
                    {basename(doc.original_filename)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="relative w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
          <Input
            placeholder="Search by filename…"
            className="pl-9"
            value={filenameQuery}
            onChange={(e) => {
              setIsLoading(true);
              setSkip(0);
              setFilenameQuery(e.target.value);
            }}
          />
        </div>
      </div>

      <div className="flex gap-5 overflow-x-auto border-b border-ink-200">
        {STATUS_FILTERS.map((status) => (
          <button
            key={status}
            onClick={() => {
              setIsLoading(true);
              setSkip(0);
              setStatusFilter(status);
            }}
            className={`relative whitespace-nowrap pb-3 text-xs font-semibold uppercase tracking-wider transition-colors ${
              statusFilter === status ? "text-ink-900" : "text-ink-400 hover:text-ink-600"
            }`}
          >
            {status === "ALL" ? "All" : status.replace(/_/g, " ")}
            {statusFilter === status && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 bg-seal-500" />
            )}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-2xl border border-ink-100 bg-paper-50">
        <table className="w-full text-sm">
          <thead className="text-left text-[11px] font-medium uppercase tracking-wider text-ink-500">
            <tr>
              <th className="px-5 py-3">Document</th>
              <th className="px-5 py-3">Type</th>
              <th className="px-5 py-3">Status</th>
              <th className="px-5 py-3">Size</th>
              <th className="px-5 py-3">Uploaded</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-5 py-10 text-center text-ink-400">
                  Loading documents…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-10 text-center text-ink-400">
                  No documents match these filters.
                </td>
              </tr>
            ) : (
              <>
                {folders.map((folder) => {
                  const isExpanded = expandedFolders.has(folder.folderName);
                  return (
                    <Fragment key={folder.folderName}>
                      <tr
                        onClick={() => toggleFolder(folder.folderName)}
                        className="cursor-pointer bg-ink-50 transition-colors hover:bg-ink-100"
                      >
                        <td colSpan={6} className="px-5 py-3">
                          <div className="flex items-center gap-2">
                            <ChevronRight
                              className={cn(
                                "h-4 w-4 text-ink-400 transition-transform",
                                isExpanded && "rotate-90"
                              )}
                            />
                            <Folder className="h-4 w-4 text-seal-500" />
                            <span className="font-medium text-ink-900">{folder.folderName}</span>
                            <span className="text-xs text-ink-400">
                              {folder.items.length} file{folder.items.length !== 1 ? "s" : ""}
                            </span>
                          </div>
                        </td>
                      </tr>
                      {isExpanded &&
                        folder.items.map((doc) => (
                          <tr
                            key={doc.id}
                            onClick={() => navigate(`/documents/${doc.id}`)}
                            className="group cursor-pointer transition-colors hover:bg-ink-50"
                            style={{ boxShadow: `inset 3px 0 0 ${STATUS_ACCENT[doc.status]}` }}
                          >
                            <td className="py-4 pl-12 pr-5">
                              <div className="flex items-center gap-2.5">
                                <FileText className="h-4 w-4 shrink-0 text-ink-400" />
                                <span className="font-medium text-ink-900">
                                  {basename(doc.original_filename)}
                                </span>
                              </div>
                            </td>
                            <td className="px-5 py-4 text-ink-600">
                              {DOCUMENT_TYPE_LABELS[doc.document_type as DocumentType]}
                            </td>
                            <td className="px-5 py-4">
                              <StatusBadge status={doc.status} />
                            </td>
                            <td className="font-data px-5 py-4 text-ink-500">
                              {formatFileSize(doc.file_size_bytes)}
                            </td>
                            <td className="font-data px-5 py-4 text-ink-500">
                              {formatDateTime(doc.created_at)}
                            </td>
                            <td className="px-5 py-4">
                              <ChevronRight className="h-4 w-4 text-ink-300 transition-transform group-hover:translate-x-0.5 group-hover:text-ink-500" />
                            </td>
                          </tr>
                        ))}
                    </Fragment>
                  );
                })}
                {ungrouped.map((doc) => (
                  <tr
                    key={doc.id}
                    onClick={() => navigate(`/documents/${doc.id}`)}
                    className="group cursor-pointer transition-colors hover:bg-ink-50"
                    style={{ boxShadow: `inset 3px 0 0 ${STATUS_ACCENT[doc.status]}` }}
                  >
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2.5">
                        <FileText className="h-4 w-4 shrink-0 text-ink-400" />
                        <span className="font-medium text-ink-900">{doc.original_filename}</span>
                      </div>
                    </td>
                    <td className="px-5 py-4 text-ink-600">
                      {DOCUMENT_TYPE_LABELS[doc.document_type as DocumentType]}
                    </td>
                    <td className="px-5 py-4">
                      <StatusBadge status={doc.status} />
                    </td>
                    <td className="font-data px-5 py-4 text-ink-500">
                      {formatFileSize(doc.file_size_bytes)}
                    </td>
                    <td className="font-data px-5 py-4 text-ink-500">
                      {formatDateTime(doc.created_at)}
                    </td>
                    <td className="px-5 py-4">
                      <ChevronRight className="h-4 w-4 text-ink-300 transition-transform group-hover:translate-x-0.5 group-hover:text-ink-500" />
                    </td>
                  </tr>
                ))}
              </>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm text-ink-500">
        <span className="font-data">
          {total} document{total !== 1 ? "s" : ""}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={skip === 0}
            onClick={() => {
              setIsLoading(true);
              setSkip(Math.max(0, skip - PAGE_SIZE));
            }}
          >
            Previous
          </Button>
          <span className="font-data text-xs">
            Page {currentPage} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={skip + PAGE_SIZE >= total}
            onClick={() => {
              setIsLoading(true);
              setSkip(skip + PAGE_SIZE);
            }}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

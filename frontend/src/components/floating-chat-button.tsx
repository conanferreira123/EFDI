import { useLocation, useNavigate } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

export function FloatingChatButton() {
  const location = useLocation();
  const navigate = useNavigate();

  // Document Detail context: matches /documents/:id (with a numeric document ID)
  const isDocumentDetail = /^\/documents\/\d+/.test(location.pathname);
  // Documents / Home context: matches /documents or / (with optional trailing slash)
  const isDocumentsHome = /^\/documents\/?$/.test(location.pathname) || location.pathname === "/";

  const searchParams = new URLSearchParams(location.search);
  const isDocumentChatOpen = searchParams.get("tab") === "chat";

  // Visibility:
  // - On Document Detail: visible ONLY if the document-level chat tab is closed
  // - On Documents/Home: visible to provide the global Ask AI entry point
  // - On any other page (e.g. /chat where global AI is already open): hidden
  // Mutual exclusivity: isDocumentDetail and isDocumentsHome cannot both be true
  const isVisible = (isDocumentDetail && !isDocumentChatOpen) || isDocumentsHome;

  if (!isVisible) {
    return null;
  }

  function handleClick() {
    if (isDocumentDetail) {
      // Open document-specific EFDI Bot via the document tab query param
      const nextParams = new URLSearchParams(location.search);
      nextParams.set("tab", "chat");
      navigate(
        {
          pathname: location.pathname,
          search: nextParams.toString(),
        },
        { replace: false }
      );
    } else if (isDocumentsHome) {
      // Open global Ask AI interface via navigation
      navigate("/chat");
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label="Open Ask AI"
      aria-expanded={false}
      className={cn(
        "absolute bottom-6 left-8 z-30 flex h-13 w-13 items-center justify-center rounded-full transition-all duration-200 cursor-pointer select-none",
        "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-seal-400 focus-visible:ring-offset-2",
        "bg-[image:var(--gradient-primary)] text-white shadow-md shadow-seal-500/30 hover:shadow-lg hover:shadow-seal-500/40 hover:scale-105 active:scale-95"
      )}
      title="Ask AI"
    >
      <MessageSquare className="h-5 w-5 text-white stroke-[2.25]" />
    </button>
  );
}

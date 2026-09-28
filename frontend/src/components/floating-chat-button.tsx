import { useLocation, useNavigate } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

export function FloatingChatButton() {
  const location = useLocation();
  const navigate = useNavigate();

  // Document is open if the pathname matches /documents/:id (with a numeric document ID)
  const isDocumentOpen = /^\/documents\/\d+/.test(location.pathname);
  const searchParams = new URLSearchParams(location.search);
  const isChatOpen = searchParams.get("tab") === "chat";

  // SHOW FLOATING BUTTON = document detail is open AND document chatbot is closed
  const isVisible = isDocumentOpen && !isChatOpen;

  if (!isVisible) {
    return null;
  }

  function handleClick() {
    const nextParams = new URLSearchParams(location.search);
    nextParams.set("tab", "chat");
    navigate(
      {
        pathname: location.pathname,
        search: nextParams.toString(),
      },
      { replace: false }
    );
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

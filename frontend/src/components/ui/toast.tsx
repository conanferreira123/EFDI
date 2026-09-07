import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { CheckCircle2, AlertCircle, XCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ToastItem {
  id: string;
  title: string;
  description?: string;
  tone: "success" | "error" | "info";
}

interface ToastContextValue {
  push: (toast: Omit<ToastItem, "id">) => void;
}

const ToastContext = React.createContext<ToastContextValue | undefined>(undefined);

const TONE_ICON: Record<ToastItem["tone"], React.ReactNode> = {
  success: <CheckCircle2 className="h-5 w-5 text-sage-500" />,
  error: <XCircle className="h-5 w-5 text-clay-500" />,
  info: <AlertCircle className="h-5 w-5 text-ink-600" />,
};

const TONE_BORDER: Record<ToastItem["tone"], string> = {
  success: "border-l-sage-500",
  error: "border-l-clay-500",
  info: "border-l-ink-600",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<ToastItem[]>([]);

  const push = React.useCallback((toast: Omit<ToastItem, "id">) => {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, { ...toast, id }]);
  }, []);

  const remove = React.useCallback((id: string) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      <ToastPrimitive.Provider swipeDirection="right">
        {children}
        {toasts.map((toast) => (
          <ToastPrimitive.Root
            key={toast.id}
            duration={5000}
            onOpenChange={(open) => !open && remove(toast.id)}
            className={cn(
              "flex items-start gap-3 rounded-md border-l-4 bg-paper-50 p-4 shadow-lg",
              "data-[state=open]:animate-in data-[state=open]:slide-in-from-right-4",
              "data-[state=closed]:animate-out data-[state=closed]:fade-out-80",
              TONE_BORDER[toast.tone]
            )}
          >
            {TONE_ICON[toast.tone]}
            <div className="flex-1">
              <ToastPrimitive.Title className="text-sm font-semibold text-ink-900">
                {toast.title}
              </ToastPrimitive.Title>
              {toast.description && (
                <ToastPrimitive.Description className="mt-0.5 text-sm text-ink-500">
                  {toast.description}
                </ToastPrimitive.Description>
              )}
            </div>
            <ToastPrimitive.Close className="text-ink-400 hover:text-ink-700">
              <X className="h-4 w-4" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="fixed bottom-0 right-0 z-50 flex w-full max-w-sm flex-col gap-2 p-6 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

// Standard shadcn/ui pattern: pairing a context provider with its
// consumer hook in the same file. useToast is a hook, not a component,
// so Fast Refresh can't recognize it -- DX-only, not a correctness issue.
// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

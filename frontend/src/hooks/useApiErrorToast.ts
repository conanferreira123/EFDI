import { useToast } from "@/components/ui/toast";
import { ApiError } from "@/services/client";

export function useApiErrorToast() {
  const { push } = useToast();

  return function showApiError(error: unknown, fallbackTitle = "Something went wrong") {
    if (error instanceof ApiError) {
      push({
        tone: "error",
        title: error.body?.error ?? fallbackTitle,
        description: error.message,
      });
    } else {
      push({ tone: "error", title: fallbackTitle, description: String(error) });
    }
  };
}

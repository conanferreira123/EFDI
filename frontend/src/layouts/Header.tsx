import { LogOut, Moon, Sun } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const ROLE_LABEL: Record<string, string> = {
  ADMIN: "Administrator",
  FINANCE_MANAGER: "Finance Manager",
  FINANCE_ANALYST: "Finance Analyst",
  AUDITOR: "Auditor",
};

export function Header({ title }: { title: string }) {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="border-b border-ink-200 bg-paper-50">
      <div className="flex h-16 items-center justify-between px-8">
        <h1
          className="text-xl font-semibold tracking-tight text-ink-900"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {title}
        </h1>

      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
        {user && (
          <>
            <div className="text-right">
              <div className="text-sm font-medium text-ink-900">{user.full_name}</div>
              <Badge tone="ink" className="mt-0.5">
                {ROLE_LABEL[user.role] ?? user.role}
              </Badge>
            </div>
            <Button variant="ghost" size="icon" onClick={logout} title="Log out">
              <LogOut className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>
      </div>
      <div className="ledger-rule" />
    </header>
  );
}

import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Upload,
  FolderSearch,
  ScrollText,
  Users,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";
import type { UserRole } from "@/types/domain";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  roles?: UserRole[]; // omitted = visible to everyone authenticated
}

const NAV_ITEMS: NavItem[] = [
  { to: "/documents", label: "Documents", icon: LayoutDashboard },
  { to: "/upload", label: "Upload", icon: Upload },
  { to: "/chat", label: "Ask AI", icon: Sparkles },
  {
    to: "/audit",
    label: "Audit Log",
    icon: ScrollText,
    roles: ["AUDITOR", "ADMIN"],
  },
  { to: "/users", label: "Users", icon: Users, roles: ["ADMIN"] },
];

// This sidebar is fixed brand chrome -- always the deep indigo-violet
// gradient, in both light and dark mode -- so every color here reads
// from the dedicated --color-sidebar-* / --gradient-sidebar tokens
// (which never change with the `.dark` class) rather than the ink-*
// scale (which inverts with the theme).
export function Sidebar() {
  const { user } = useAuth();
  if (!user) return null;

  const visibleItems = NAV_ITEMS.filter((item) => !item.roles || item.roles.includes(user.role));

  return (
    <aside
      className="flex h-screen w-60 flex-col text-[var(--color-sidebar-text)]"
      style={{
        backgroundImage: "var(--gradient-sidebar)",
        borderRight: "1px solid var(--color-sidebar-border)",
      }}
    >
      <div className="flex items-center gap-2 px-5 py-6">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-lg"
          style={{ backgroundImage: "var(--gradient-primary)" }}
        >
          <FolderSearch className="h-4 w-4 text-white" />
        </div>
        <div>
          <div className="text-sm font-semibold leading-none text-[var(--color-sidebar-text)]">
            EFDI
          </div>
          <div className="text-[11px] leading-none text-[var(--color-sidebar-text-muted)]">
            Document Intelligence
          </div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3">
        {visibleItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all",
                isActive
                  ? "bg-[var(--color-sidebar-active)] text-white shadow-md shadow-[var(--color-sidebar-active)]/30"
                  : "text-[var(--color-sidebar-text-muted)] hover:bg-white/5 hover:text-[var(--color-sidebar-text)]"
              )
            }
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div
        className="mx-5 mb-2 h-px opacity-60"
        style={{ backgroundColor: "var(--color-sidebar-border)" }}
      />
      <div className="px-5 pb-5 text-[11px] text-[var(--color-sidebar-text-muted)]">
        Enterprise Financial Document Intelligence
      </div>
    </aside>
  );
}

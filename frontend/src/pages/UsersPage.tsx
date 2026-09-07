import { useEffect, useState } from "react";
import { usersApi } from "@/services/admin";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/context/AuthContext";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { formatDateTime } from "@/lib/format";
import type { UserRole } from "@/types/domain";
import type { UserResponse } from "@/types/api";

const ROLES: UserRole[] = ["ADMIN", "FINANCE_MANAGER", "FINANCE_ANALYST", "AUDITOR"];

const ROLE_LABEL: Record<UserRole, string> = {
  ADMIN: "Administrator",
  FINANCE_MANAGER: "Finance Manager",
  FINANCE_ANALYST: "Finance Analyst",
  AUDITOR: "Auditor",
};

export function UsersPage() {
  const { user: currentUser } = useAuth();
  const showError = useApiErrorToast();
  const { push } = useToast();
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    usersApi
      .list()
      .then((result) => !cancelled && setUsers(result))
      .catch((err) => !cancelled && showError(err, "Could not load users"))
      .finally(() => !cancelled && setIsLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleRoleChange(userId: number, role: UserRole) {
    try {
      const updated = await usersApi.updateRole(userId, role);
      setUsers((current) => current.map((u) => (u.id === userId ? updated : u)));
      push({ tone: "success", title: "Role updated" });
    } catch (err) {
      showError(err, "Could not update role");
    }
  }

  async function handleStatusToggle(userId: number, isActive: boolean) {
    try {
      const updated = await usersApi.updateStatus(userId, isActive);
      setUsers((current) => current.map((u) => (u.id === userId ? updated : u)));
      push({ tone: "success", title: isActive ? "Account activated" : "Account deactivated" });
    } catch (err) {
      showError(err, "Could not update account status");
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border border-ink-200">
      <table className="w-full text-sm">
        <thead className="bg-ink-50 text-left text-xs font-medium uppercase tracking-wide text-ink-500">
          <tr>
            <th className="px-4 py-3">Name</th>
            <th className="px-4 py-3">Username</th>
            <th className="px-4 py-3">Role</th>
            <th className="px-4 py-3">Joined</th>
            <th className="px-4 py-3">Active</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">
          {isLoading ? (
            <tr>
              <td colSpan={5} className="px-4 py-10 text-center text-ink-400">
                Loading users…
              </td>
            </tr>
          ) : (
            users.map((u) => {
              const isSelf = u.id === currentUser?.id;
              return (
                <tr key={u.id}>
                  <td className="px-4 py-2.5 font-medium text-ink-900">
                    {u.full_name}
                    {isSelf && <Badge tone="ink" className="ml-2">You</Badge>}
                  </td>
                  <td className="font-data px-4 py-2.5 text-ink-500">{u.username}</td>
                  <td className="px-4 py-2.5">
                    <Select
                      value={u.role}
                      disabled={isSelf}
                      onValueChange={(value) => handleRoleChange(u.id, value as UserRole)}
                    >
                      <SelectTrigger className="w-44">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ROLES.map((role) => (
                          <SelectItem key={role} value={role}>
                            {ROLE_LABEL[role]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="font-data px-4 py-2.5 text-xs text-ink-500">
                    {formatDateTime(u.created_at)}
                  </td>
                  <td className="px-4 py-2.5">
                    <Switch
                      checked={u.is_active}
                      disabled={isSelf}
                      onCheckedChange={(checked) => handleStatusToggle(u.id, checked)}
                    />
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

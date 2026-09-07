import { Outlet, useMatches } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";

interface RouteHandle {
  title?: string;
}

export function AppShell() {
  const matches = useMatches();
  const lastMatch = matches[matches.length - 1];
  const title = (lastMatch?.handle as RouteHandle | undefined)?.title ?? "EFDI";

  return (
    <div className="flex h-screen overflow-hidden bg-paper-50">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header title={title} />
        <main className="flex-1 overflow-y-auto p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

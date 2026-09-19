import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { ToastProvider } from "@/components/ui/toast";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppShell } from "@/layouts/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import {RegisterPage } from "@/pages/RegisterPage";
import { DocumentsListPage } from "@/pages/DocumentsListPage";
import { UploadPage } from "@/pages/UploadPage";
import { DocumentDetailPage } from "@/pages/DocumentDetailPage";
import { GlobalChatPage } from "@/pages/GlobalChatPage";
import { AuditLogPage } from "@/pages/AuditLogPage";
import { UsersPage } from "@/pages/UsersPage";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  {
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { path: "/", element: <Navigate to="/documents" replace /> },
      {
        path: "/documents",
        element: <DocumentsListPage />,
        handle: { title: "Documents" },
      },
      {
        path: "/documents/:documentId",
        element: <DocumentDetailPage />,
        handle: { title: "Document Detail" },
      },
      {
        path: "/upload",
        element: <UploadPage />,
        handle: { title: "Upload" },
      },
      {
        path: "/chat",
        element: <GlobalChatPage />,
        handle: { title: "Ask AI" },
      },
      {
        path: "/audit",
        element: (
          <ProtectedRoute roles={["AUDITOR", "ADMIN"]}>
            <AuditLogPage />
          </ProtectedRoute>
        ),
        handle: { title: "Audit Log" },
      },
      {
        path: "/users",
        element: (
          <ProtectedRoute roles={["ADMIN"]}>
            <UsersPage />
          </ProtectedRoute>
        ),
        handle: { title: "User Management" },
      },
    ],
  },
  { path: "*", element: <Navigate to="/documents" replace /> },
]);

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

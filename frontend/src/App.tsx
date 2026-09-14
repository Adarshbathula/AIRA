import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "./context/AuthContext";
import AppLayout from "./layouts/AppLayout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Assistant from "./pages/Assistant";
import History from "./pages/History";
import Incidents from "./pages/Incidents";
import IncidentDetail from "./pages/IncidentDetail";
import Knowledge from "./pages/Knowledge";
import AdminOverview from "./pages/admin/AdminOverview";
import DocumentsAdmin from "./pages/admin/DocumentsAdmin";
import UsersAdmin from "./pages/admin/UsersAdmin";
import { Spinner } from "./components/ui";

function RequireAuth({ children, adminOnly = false }: { children: ReactNode; adminOnly?: boolean }) {
  const { user, loading, isAdmin } = useAuth();
  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center text-slate-400">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (adminOnly && !isAdmin) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

export default function App() {
  const { user, loading, isAdmin } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={loading ? null : user ? <Navigate to={isAdmin ? "/admin" : "/dashboard"} replace /> : <Login />} />
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route path="/" element={<Navigate to={user && isAdmin ? "/admin" : "/dashboard"} replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/history" element={<History />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/incidents/:id" element={<IncidentDetail />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/admin" element={<RequireAuth adminOnly><AdminOverview /></RequireAuth>} />
        <Route path="/admin/documents" element={<RequireAuth adminOnly><DocumentsAdmin /></RequireAuth>} />
        <Route path="/admin/users" element={<RequireAuth adminOnly><UsersAdmin /></RequireAuth>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

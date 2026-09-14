import { useCallback, useEffect, useState } from "react";
import { userApi, apiError } from "../../services/api";
import { useAuth } from "../../context/AuthContext";
import type { User } from "../../types";
import { Badge, Card, EmptyState, ErrorNote, Modal, Spinner } from "../../components/ui";
import { fmtDate } from "../../utils/format";
import { useToast } from "../../hooks/useToast";

export default function UsersAdmin() {
  const { user: me } = useAuth();
  const toast = useToast();
  const [rows, setRows] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "user" });

  const load = useCallback(async () => {
    setLoading(true);
    try { setRows(await userApi.list(q || undefined)); }
    catch (e) { setError(apiError(e, "Could not load users")); }
    finally { setLoading(false); }
  }, [q]);

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(t);
  }, [load]);

  const toggle = async (u: User, patch: Partial<{ role: string; is_active: boolean }>) => {
    try {
      await userApi.update(u.id, patch);
      toast.success(patch.role ? `${u.email} is now ${patch.role}` : `${u.email} ${patch.is_active ? "re-activated" : "deactivated"}`);
      void load();
    } catch (e) {
      toast.error(apiError(e, "Update failed"));
    }
  };

  const create = async () => {
    try {
      await userApi.create(form);
      toast.success(`Account ${form.email} created (${form.role})`);
      setCreating(false);
      setForm({ name: "", email: "", password: "", role: "user" });
      void load();
    } catch (e) {
      toast.error(apiError(e, "Create failed"));
    }
  };

  const remove = async (u: User) => {
    if (!window.confirm(`Delete ${u.email}? Their conversations and incidents are removed too.`)) return;
    try {
      await userApi.remove(u.id);
      toast.success("User deleted");
      void load();
    } catch (e) {
      toast.error(apiError(e, "Delete failed"));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">User & role management</h2>
          <p className="text-sm text-slate-500">Engineers can analyse incidents and browse the knowledge base; admins additionally manage the corpus, users and analytics.</p>
        </div>
        <div className="flex items-center gap-2">
          <input className="input w-64" placeholder="Search name / email…" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn-primary" onClick={() => setCreating(true)}>+ New user</button>
        </div>
      </div>

      {error && <ErrorNote message={error} />}

      <Card bodyClass="p-0">
        {loading ? (
          <div className="flex justify-center py-20 text-slate-400"><Spinner className="h-7 w-7" /></div>
        ) : rows.length === 0 ? (
          <div className="p-6"><EmptyState title="No users found" /></div>
        ) : (
          <table className="w-full min-w-[760px]">
            <thead className="border-b border-slate-100 bg-slate-50/70">
              <tr><th className="th">User</th><th className="th">Role</th><th className="th">Status</th><th className="th">Created</th><th className="th text-right">Actions</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((u) => (
                <tr key={u.id} className="hover:bg-slate-50/70">
                  <td className="td">
                    <p className="font-medium text-slate-800">{u.name} {u.id === me?.id && <span className="text-[10px] font-semibold text-brand-600">(you)</span>}</p>
                    <p className="text-xs text-slate-500">{u.email}</p>
                  </td>
                  <td className="td">
                    <Badge tone={u.role === "admin" ? "bg-ink-900 text-white" : "bg-slate-100 text-slate-600 ring-1 ring-slate-200"}>{u.role.toUpperCase()}</Badge>
                  </td>
                  <td className="td">
                    <Badge tone={u.is_active ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200" : "bg-rose-100 text-rose-700 ring-1 ring-rose-200"}>
                      {u.is_active ? "active" : "disabled"}
                    </Badge>
                  </td>
                  <td className="td whitespace-nowrap text-xs text-slate-500">{fmtDate(u.created_at)}</td>
                  <td className="td text-right whitespace-nowrap">
                    <button
                      className="text-xs font-medium text-brand-600 hover:underline disabled:opacity-40"
                      disabled={u.id === me?.id}
                      onClick={() => void toggle(u, { role: u.role === "admin" ? "user" : "admin" })}
                    >
                      {u.role === "admin" ? "demote" : "promote"}
                    </button>
                    <button
                      className="ml-3 text-xs font-medium text-amber-600 hover:underline disabled:opacity-40"
                      disabled={u.id === me?.id}
                      onClick={() => void toggle(u, { is_active: !u.is_active })}
                    >
                      {u.is_active ? "disable" : "enable"}
                    </button>
                    <button className="ml-3 text-xs font-medium text-rose-600 hover:underline disabled:opacity-40" disabled={u.id === me?.id} onClick={() => void remove(u)}>
                      delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Modal open={creating} onClose={() => setCreating(false)} title="Create account">
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-slate-500">Full name</span>
            <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-slate-500">Email</span>
            <input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-[11px] font-medium text-slate-500">Temporary password (min 8)</span>
              <input className="input" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </label>
            <label className="block">
              <span className="mb-1 block text-[11px] font-medium text-slate-500">Role</span>
              <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="user">Engineer (user)</option>
                <option value="admin">Admin</option>
              </select>
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => setCreating(false)}>Cancel</button>
            <button className="btn-primary" onClick={() => void create()} disabled={form.name.length < 2 || !form.email.includes("@") || form.password.length < 8}>
              Create
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

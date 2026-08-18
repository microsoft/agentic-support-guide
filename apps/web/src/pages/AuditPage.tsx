import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { AuditResponse } from "../api/types";
import { Card } from "../components/Card";
import { ApiUnavailable, EmptyState, LoadingState } from "../components/States";

type State =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; data: AuditResponse };

export function AuditPage() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [endpointFilter, setEndpointFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [providerFilter, setProviderFilter] = useState("");

  const load = () => {
    setState({ kind: "loading" });
    api
      .audit()
      .then((data) => setState({ kind: "ready", data }))
      .catch(() => setState({ kind: "error" }));
  };

  useEffect(load, []);

  const endpoints = useMemo(() => {
    if (state.kind !== "ready") return [] as string[];
    return Array.from(new Set(state.data.events.map((e) => e.endpoint))).sort();
  }, [state]);
  const statuses = useMemo(() => {
    if (state.kind !== "ready") return [] as string[];
    return Array.from(new Set(state.data.events.map((e) => e.status))).sort();
  }, [state]);

  const providers = useMemo(() => {
    if (state.kind !== "ready") return [] as string[];
    return Array.from(new Set(state.data.events.map((e) => e.provider_model))).sort();
  }, [state]);

  const rows = useMemo(() => {
    if (state.kind !== "ready") return [];
    return state.data.events.filter(
      (e) =>
        (!endpointFilter || e.endpoint === endpointFilter) &&
        (!statusFilter || e.status === statusFilter) &&
        (!providerFilter || e.provider_model === providerFilter),
    );
  }, [state, endpointFilter, statusFilter, providerFilter]);

  if (state.kind === "loading") return <LoadingState label="Loading audit events..." />;
  if (state.kind === "error") return <ApiUnavailable onRetry={load} />;

  return (
    <div className="space-y-6">
      <Card title="AI Audit trail (synthetic)">
        <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
          {state.data.disclaimer}
        </div>
      </Card>

      <Card title="Filters">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label
              htmlFor="audit-endpoint"
              className="block text-xs uppercase tracking-wide text-slate-400"
            >
              Endpoint
            </label>
            <select
              id="audit-endpoint"
              value={endpointFilter}
              onChange={(e) => setEndpointFilter(e.target.value)}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            >
              <option value="">All</option>
              {endpoints.map((ep) => (
                <option key={ep} value={ep}>
                  {ep}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label
              htmlFor="audit-provider"
              className="block text-xs uppercase tracking-wide text-slate-400"
            >
              Provider/model
            </label>
            <select
              id="audit-provider"
              value={providerFilter}
              onChange={(e) => setProviderFilter(e.target.value)}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            >
              <option value="">All</option>
              {providers.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label
              htmlFor="audit-status"
              className="block text-xs uppercase tracking-wide text-slate-400"
            >
              Status
            </label>
            <select
              id="audit-status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            >
              <option value="">All</option>
              {statuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          The <span className="text-slate-300">User</span> column shows a fixed synthetic
          placeholder <span className="font-mono">Staff S-01</span> because no auth provider is
          wired up. In production this would be a Microsoft Entra ID identity.
        </p>
      </Card>

      {rows.length === 0 ? (
        <EmptyState label="No audit rows match the current filters." />
      ) : (
        <Card title={`Transactions (${rows.length} of ${state.data.total})`}>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400">
                  <th className="py-2 pr-3">Timestamp</th>
                  <th className="py-2 pr-3">Endpoint</th>
                  <th className="py-2 pr-3">Context</th>
                  <th className="py-2 pr-3">User</th>
                  <th className="py-2 pr-3">Provider/model</th>
                  <th className="py-2 pr-3">Duration (ms)</th>
                  <th className="py-2 pr-3">Token est.</th>
                  <th className="py-2 pr-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.event_id} className="border-t border-slate-800 text-slate-300">
                    <td className="py-2 pr-3 whitespace-nowrap">{row.timestamp}</td>
                    <td className="py-2 pr-3">{row.endpoint}</td>
                    <td className="py-2 pr-3">{row.context}</td>
                    <td className="py-2 pr-3">{row.user}</td>
                    <td className="py-2 pr-3">{row.provider_model}</td>
                    <td className="py-2 pr-3">{row.duration_ms}</td>
                    <td className="py-2 pr-3">{row.token_estimate}</td>
                    <td className="py-2 pr-3">
                      <span
                        className={
                          row.status === "ok"
                            ? "text-emerald-400"
                            : row.status === "warning"
                              ? "text-amber-300"
                              : "text-rose-300"
                        }
                      >
                        {row.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

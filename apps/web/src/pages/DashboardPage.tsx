import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { DashboardSummary } from "../api/types";
import { Card } from "../components/Card";
import { ApiUnavailable, EmptyState, LoadingState } from "../components/States";

type State =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; data: DashboardSummary };

export function DashboardPage() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = () => {
    setState({ kind: "loading" });
    api
      .dashboardSummary()
      .then((data) => setState({ kind: "ready", data }))
      .catch(() => setState({ kind: "error" }));
  };

  useEffect(load, []);

  if (state.kind === "loading") return <LoadingState label="Loading dashboard..." />;
  if (state.kind === "error") return <ApiUnavailable onRetry={load} />;

  const { data } = state;
  if (!data.kpi_cards.length) return <EmptyState label="No dashboard data." />;

  return (
    <div className="space-y-6">
      <section
        aria-label="Key performance indicators"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
      >
        {data.kpi_cards.map((card) => (
          <article
            key={card.id}
            data-testid={`kpi-${card.id}`}
            className="rounded-lg border border-slate-800 bg-slate-900/70 p-4"
          >
            <div className="text-xs uppercase tracking-wide text-slate-400">{card.label}</div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {card.value.toLocaleString()}
              <span className="ml-1 text-sm text-slate-400">
                {card.unit === "percent" ? "%" : ""}
              </span>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Trend: <span className="text-slate-300">{card.trend}</span>
            </div>
          </article>
        ))}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Proficiency trend (synthetic)">
          <div className="h-64">
            <ResponsiveContainer>
              <LineChart data={data.proficiency_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="period" stroke="#94a3b8" />
                <YAxis stroke="#94a3b8" />
                <Tooltip
                  contentStyle={{
                    background: "#0f172a",
                    border: "1px solid #334155",
                    color: "#e2e8f0",
                  }}
                />
                <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Domain distribution (synthetic)">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={data.domain_distribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="domain" stroke="#94a3b8" tick={{ fontSize: 10 }} />
                <YAxis stroke="#94a3b8" />
                <Tooltip
                  contentStyle={{
                    background: "#0f172a",
                    border: "1px solid #334155",
                    color: "#e2e8f0",
                  }}
                />
                <Bar dataKey="value" fill="#0ea5e9" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="Synthetic data notice">
        <ul className="space-y-1 text-sm text-slate-300">
          {data.notes.map((note) => (
            <li key={note}>· {note}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

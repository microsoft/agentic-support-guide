import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import type { AssessmentsSummary } from "../api/types";
import { Card } from "../components/Card";
import { ApiUnavailable, EmptyState, LoadingState } from "../components/States";

interface Filters {
  school: string;
  grade: string;
  domain: string;
  group: string;
}

const SCHOOL_OPTIONS = ["SCH-001", "SCH-002", "SCH-003", "SCH-004"];
const GRADE_OPTIONS = ["1", "2", "3", "4", "5", "6", "7", "8"];
const DOMAIN_OPTIONS = [
  "early-literacy",
  "reading-comprehension",
  "math-foundations",
  "math-acceleration",
  "attendance-engagement",
  "multi-domain",
];
const GROUP_OPTIONS = ["GRP-A", "GRP-B", "GRP-C"];

type State =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; data: AssessmentsSummary };

type SortField = "learner_id" | "domain" | "proficiency" | "score" | "period";

export function AssessmentsPage() {
  const [filters, setFilters] = useState<Filters>({
    school: "",
    grade: "",
    domain: "",
    group: "",
  });
  const [state, setState] = useState<State>({ kind: "loading" });
  const [sortField, setSortField] = useState<SortField>("score");
  const [sortAsc, setSortAsc] = useState(false);

  const load = () => {
    setState({ kind: "loading" });
    api
      .assessmentsSummary({
        school: filters.school || undefined,
        grade: filters.grade || undefined,
        domain: filters.domain || undefined,
        group: filters.group || undefined,
      })
      .then((data) => setState({ kind: "ready", data }))
      .catch(() => setState({ kind: "error" }));
  };

  useEffect(load, [filters]);

  const sortedRows = useMemo(() => {
    if (state.kind !== "ready") return [];
    const rows = [...state.data.table_rows];
    rows.sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (av === bv) return 0;
      if (av === undefined) return 1;
      if (bv === undefined) return -1;
      return (av < bv ? -1 : 1) * (sortAsc ? 1 : -1);
    });
    return rows;
  }, [state, sortField, sortAsc]);

  const toggleSort = (field: SortField) => {
    if (field === sortField) {
      setSortAsc((prev) => !prev);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  return (
    <div className="space-y-6">
      <Card title="Filters">
        <div
          role="group"
          aria-label="Assessment filters"
          className="grid grid-cols-1 gap-3 md:grid-cols-4"
        >
          <FilterSelect
            label="School"
            value={filters.school}
            onChange={(v) => setFilters((f) => ({ ...f, school: v }))}
            options={SCHOOL_OPTIONS}
          />
          <FilterSelect
            label="Grade"
            value={filters.grade}
            onChange={(v) => setFilters((f) => ({ ...f, grade: v }))}
            options={GRADE_OPTIONS}
          />
          <FilterSelect
            label="Domain"
            value={filters.domain}
            onChange={(v) => setFilters((f) => ({ ...f, domain: v }))}
            options={DOMAIN_OPTIONS}
          />
          <FilterSelect
            label="Group"
            value={filters.group}
            onChange={(v) => setFilters((f) => ({ ...f, group: v }))}
            options={GROUP_OPTIONS}
          />
        </div>
      </Card>

      {state.kind === "loading" && <LoadingState label="Loading assessments..." />}
      {state.kind === "error" && <ApiUnavailable onRetry={load} />}
      {state.kind === "ready" && state.data.total_records === 0 && (
        <EmptyState label="No records match the current filters." />
      )}

      {state.kind === "ready" && state.data.total_records > 0 && (
        <>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card title="Proficiency distribution">
              <ul className="space-y-2 text-sm">
                {state.data.proficiency_distribution.map((bucket) => (
                  <li key={bucket.label} className="flex justify-between text-slate-300">
                    <span>{bucket.label}</span>
                    <span>
                      {bucket.count} ({bucket.percent}%)
                    </span>
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="Domain averages (synthetic)">
              <div className="h-64">
                <ResponsiveContainer>
                  <BarChart
                    data={state.data.domain_trends.map((d) => ({
                      domain: d.domain,
                      value:
                        d.points.reduce((s, p) => s + p.value, 0) /
                        (d.points.length || 1),
                    }))}
                  >
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
                    <Bar dataKey="value" fill="#38bdf8" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <Card title="Performance summary">
            <p className="text-xs uppercase tracking-wide text-amber-300">
              Local rule-based output
            </p>
            <p className="mt-2 text-sm text-slate-200">{state.data.performance_summary}</p>
            <p className="mt-2 text-xs text-slate-500">{state.data.generated_by}</p>
          </Card>

          <Card title="Recommendations">
            <ul className="space-y-1 text-sm text-slate-300">
              {state.data.recommendation_bullets.map((b) => (
                <li key={b}>· {b}</li>
              ))}
            </ul>
          </Card>

          <Card title={`Assessment records (${state.data.total_records} total, first 100 shown)`}>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-400">
                    {(["learner_id", "domain", "proficiency", "score", "period"] as SortField[]).map(
                      (field) => (
                        <th key={field} scope="col" className="py-2 pr-4">
                          <button
                            type="button"
                            onClick={() => toggleSort(field)}
                            className="text-left uppercase text-xs tracking-wide hover:text-slate-100"
                            aria-label={`Sort by ${field}`}
                          >
                            {field.replace("_", " ")}
                            {sortField === field ? (sortAsc ? " ▲" : " ▼") : ""}
                          </button>
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {sortedRows.map((row, idx) => (
                    <tr
                      key={`${row.record_id}-${idx}`}
                      className="border-t border-slate-800 text-slate-300"
                    >
                      <td className="py-2 pr-4">{row.learner_id}</td>
                      <td className="py-2 pr-4">{row.domain}</td>
                      <td className="py-2 pr-4">{row.proficiency}</td>
                      <td className="py-2 pr-4">{row.score}</td>
                      <td className="py-2 pr-4">{row.period}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  const id = `filter-${label.toLowerCase()}`;
  return (
    <div>
      <label htmlFor={id} className="block text-xs uppercase tracking-wide text-slate-400">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
      >
        <option value="">All</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}

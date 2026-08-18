import type { AgentTraceStep } from "../api/types";

interface Props {
  running: boolean;
  trace: AgentTraceStep[];
}

const AGENTS = [
  { key: "data-analyst-agent", label: "Data Analyst Agent" },
  { key: "support-recommendation-agent", label: "Support Recommendation Agent" },
  { key: "validator-agent", label: "Validator Agent" },
];

export function AgentWorkflowPanel({ running, trace }: Props) {
  const byAgent = new Map<string, AgentTraceStep>();
  for (const step of trace) {
    // Prefer the repair step if present so the final status wins.
    byAgent.set(step.agent.replace(":repair", ""), step);
  }

  return (
    <div
      aria-label="Agent workflow"
      data-testid="agent-workflow"
      className="rounded-lg border border-slate-800 bg-slate-900/70 p-4"
    >
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">Agent workflow</h3>
          <p className="text-xs text-slate-400">
            Three agents collaborate via typed contracts and one validator repair loop.
          </p>
        </div>
        {running && <span className="text-xs text-sky-300">Running...</span>}
      </div>
      <ol className="mt-3 space-y-2">
        {AGENTS.map((row, idx) => {
          const step = byAgent.get(row.key);
          const status = step?.status ?? (running ? "pending" : "not-run");
          const errorStatuses = new Set([
            "failed",
            "provider_timeout",
            "provider_error",
            "provider_content_filter",
            "provider_throttling",
            "provider_missing",
            "invalid_model_json",
            "budget_exhausted",
            "orchestration_budget_exhausted",
          ]);
          const tone =
            status === "ok" || status === "passed"
              ? "text-emerald-300"
              : errorStatuses.has(status)
              ? "text-rose-300"
              : status === "pending"
              ? "text-sky-300"
              : "text-slate-400";
          return (
            <li
              key={row.key}
              className="flex items-center justify-between rounded border border-slate-800 px-3 py-2 text-sm text-slate-200"
              data-testid={`agent-step-${idx + 1}`}
            >
              <div>
                <div className="font-medium">{row.label}</div>
                {step && (
                  <div className="text-xs text-slate-500">
                    {step.provider} / {step.model} · {step.latency_ms} ms
                  </div>
                )}
              </div>
              <span className={`text-xs uppercase tracking-wide ${tone}`}>{status}</span>
            </li>
          );
        })}
      </ol>
      {trace.some((s) => (s.issue_codes ?? []).length || (s.warning_codes ?? []).length) && (
        <div className="mt-3 rounded bg-slate-950/60 p-2 text-xs text-slate-400">
          {trace.map((step) => (
            <div key={`${step.agent}-${step.status}`}>
              <span className="text-slate-300">{step.agent}</span>
              {(step.issue_codes ?? []).length > 0 && (
                <span className="ml-2 text-rose-300">
                  issues: {(step.issue_codes ?? []).join(", ")}
                </span>
              )}
              {(step.warning_codes ?? []).length > 0 && (
                <span className="ml-2 text-amber-300">
                  warnings: {(step.warning_codes ?? []).join(", ")}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

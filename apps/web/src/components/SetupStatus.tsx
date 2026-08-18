import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { HealthDetailsResponse } from "../api/types";

type State =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; details: HealthDetailsResponse };

interface Props {
  compact?: boolean;
}

export function SetupStatus({ compact = false }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = () => {
    setState({ kind: "loading" });
    api
      .healthDetails()
      .then((details) => setState({ kind: "ready", details }))
      .catch(() => setState({ kind: "error" }));
  };

  useEffect(load, []);

  if (state.kind === "loading") {
    return (
      <div className="rounded border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-400">
        Checking setup status...
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div
        role="alert"
        data-testid="setup-status"
        className="rounded border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200"
      >
        API unavailable - start the local backend.
      </div>
    );
  }

  const { details } = state;
  const ready = details.customer_demo_ready;
  const bannerTone = ready
    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
    : "border-rose-500/40 bg-rose-500/10 text-rose-100";

  const bannerLabel = ready
    ? "Customer demo ready - Azure AI Foundry is configured."
    : "Customer demo NOT ready - finish Azure AI Foundry setup before demoing.";

  return (
    <section
      aria-label="Setup status"
      data-testid="setup-status"
      className="space-y-3"
    >
      <div
        role="status"
        data-testid="setup-banner"
        className={`rounded border px-3 py-2 text-sm ${bannerTone}`}
      >
        <div className="font-semibold">{bannerLabel}</div>
        <div className="mt-1 text-xs opacity-90">{details.guidance}</div>
      </div>

      {details.warnings.length > 0 && (
        <ul className="rounded border border-amber-400/40 bg-amber-500/10 p-3 text-xs text-amber-100">
          {details.warnings.map((w) => (
            <li key={w} className="mb-1 last:mb-0">
              · {w}
            </li>
          ))}
        </ul>
      )}

      {!compact && (
        <ul
          aria-label="Setup checks"
          className="rounded border border-slate-800 bg-slate-900/70 divide-y divide-slate-800 text-sm"
        >
          {details.checks.map((c) => (
            <li
              key={c.name}
              data-testid={`setup-check-${c.name}`}
              className="flex items-start gap-3 px-3 py-2"
            >
              <span
                aria-hidden="true"
                className={`mt-0.5 inline-block h-2 w-2 rounded-full ${
                  c.ok ? "bg-emerald-400" : "bg-rose-400"
                }`}
              />
              <div className="flex-1">
                <div className="text-slate-100">{c.label}</div>
                <div className="text-xs text-slate-400">{c.detail}</div>
              </div>
              <span className="text-xs uppercase tracking-wide text-slate-400">
                {c.ok ? "ok" : "todo"}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-slate-500">
        Active provider: <span className="text-slate-300">{details.active_provider}</span>
      </p>
    </section>
  );
}

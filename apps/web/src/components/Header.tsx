import { useEffect, useState } from "react";
import { api } from "../api/client";
import { usePrincipal } from "../auth/AuthGate";

interface HealthState {
  service: string;
  configured: boolean;
}

export function Header() {
  const { principal, districts, signOut } = usePrincipal();
  const [health, setHealth] = useState<HealthState>({
    service: "agentic-support-guide-api",
    configured: false,
  });
  const [status, setStatus] = useState<"ok" | "unavailable" | "loading">("loading");

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((res) => {
        if (cancelled) return;
        setHealth({ service: res.service, configured: res.provider_configured });
        setStatus("ok");
      })
      .catch(() => {
        if (!cancelled) setStatus("unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="bg-slate-900 border-b border-slate-800 px-6 py-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Agentic Support Guide</h1>
          <p className="text-xs text-slate-400">
            Three-agent workflow via Azure AI Foundry. Synthetic data only.
          </p>
        </div>
        <div className="text-xs text-slate-400">
          <span aria-label="Service status">
            Service: <span className="text-slate-200">{health.service}</span> ·{" "}
            {status === "loading" && <span>checking...</span>}
            {status === "ok" && (
              <>
                <span className="text-emerald-400">online</span>
                {!health.configured && (
                  <span className="ml-2 text-rose-300">Azure Foundry setup incomplete</span>
                )}
              </>
            )}
            {status === "unavailable" && (
              <span className="text-rose-400">API unavailable</span>
            )}
          </span>
          {principal && (
            <div className="mt-1 flex items-center gap-2 sm:justify-end">
              <span aria-label="Signed in as">
                <span className="text-slate-200">{principal.display_name}</span> ·{" "}
                {districts.join(", ")}
                {principal.is_facilitator && (
                  <span className="ml-1 text-amber-300">facilitator</span>
                )}
              </span>
              <button
                type="button"
                onClick={signOut}
                className="rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:bg-slate-800"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

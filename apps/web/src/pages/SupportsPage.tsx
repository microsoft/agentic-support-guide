import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  AgentTraceStep,
  Recommendation,
  RecommendationEnvelope,
  SavedPlan,
  GoalOption,
  StrategyOption,
  SupportOptions,
} from "../api/types";
import { AgentWorkflowPanel } from "../components/AgentWorkflowPanel";
import { Card } from "../components/Card";
import { SetupStatus } from "../components/SetupStatus";
import { ApiUnavailable, LoadingState } from "../components/States";

type Step = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;

interface OptionsState {
  kind: "loading" | "ready" | "error";
  data?: SupportOptions;
}

const ERROR_MESSAGES: Record<string, string> = {
  provider_missing:
    "Azure AI Foundry is not configured. Populate AZURE_AI_FOUNDRY_* environment variables and restart the backend.",
  provider_timeout: "The model provider timed out. Try again in a moment.",
  provider_throttling: "The model provider throttled the request. Try again shortly.",
  provider_content_filter:
    "The request was blocked by content-safety. Please rephrase and try again.",
  provider_error: "The model provider returned an error.",
  invalid_model_json:
    "The model returned invalid JSON. The coordinator did not surface a recommendation.",
  validation_failed:
    "The recommendation could not be validated after one repair attempt. No recommendation was returned.",
  orchestration_budget_exhausted:
    "The three-agent workflow exceeded its overall budget. Try again in a moment.",
  orchestration_error: "The workflow failed before it could produce a recommendation.",
  evidence_missing:
    "No evidence was found for this dealer group, so no grounded recommendation could be made.",
};

export function SupportsPage() {
  const [dealerGroup, setDealerGroup] = useState("");
  const [options, setOptions] = useState<OptionsState>({ kind: "loading" });
  const [step, setStep] = useState<Step>(1);
  const [dealershipId, setDealershipId] = useState("");
  const [category, setCategory] = useState("");
  const [concern, setConcern] = useState("");
  const [envelope, setEnvelope] = useState<RecommendationEnvelope | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [selectedGoal, setSelectedGoal] = useState<string | null>(null);
  const [strategies, setStrategies] = useState<string[]>([]);
  const [savedPlans, setSavedPlans] = useState<SavedPlan[]>([]);
  const [savedError, setSavedError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const loadOptions = () => {
    setOptions({ kind: "loading" });
    api
      .supportOptions()
      .then((data) => {
        setOptions({ kind: "ready", data });
        // The roster comes from the API so the bundle carries no dealer group
        // names of its own.
        setDealerGroup((current) => current || (data.dealer_groups[0] ?? ""));
      })
      .catch(() => setOptions({ kind: "error" }));
  };

  const loadPlans = () => {
    api
      .savedPlans()
      .then((res) => setSavedPlans(res.plans))
      .catch(() => setSavedError("Unable to load saved plans."));
  };

  useEffect(() => {
    loadOptions();
    loadPlans();
  }, []);

  const goalsForCategory = useMemo<GoalOption[]>(
    () => options.data?.goals.filter((g) => g.category_id === category) ?? [],
    [options, category],
  );
  const strategiesForCategory = useMemo<StrategyOption[]>(
    () => options.data?.strategies.filter((s) => s.category_id === category) ?? [],
    [options, category],
  );

  if (options.kind === "loading") return <LoadingState label="Loading support catalog..." />;
  if (options.kind === "error" || !options.data)
    return <ApiUnavailable onRetry={loadOptions} />;
  const data = options.data;

  const rec: Recommendation | null = envelope?.recommendation ?? null;
  const trace: AgentTraceStep[] = envelope?.agent_trace ?? [];
  const canAdvanceFromStep = (current: Step): boolean => {
    switch (current) {
      case 1:
        return !!dealershipId;
      case 2:
        return !!category;
      case 3:
        return concern.trim().length >= 5;
      case 4:
        return !!rec;
      case 5:
        return !!selectedGoal;
      case 6:
        return strategies.length > 0;
      case 7:
        return true;
      default:
        return false;
    }
  };

  const generateRecommendation = () => {
    setEnvelope(null);
    setRecLoading(true);
    api
      .recommendation({
        dealership_id: dealershipId,
        category,
        concern_text: concern,
        dealer_group_id: dealerGroup,
      })
      .then((env) => {
        setEnvelope(env);
        if (env.status === "ok") setStep(5);
      })
      .catch((err: unknown) =>
        // The client already parsed the typed error body. Collapsing every
        // transport failure to "provider_error" would report a 401 or a 422
        // as a model outage and send the user looking in the wrong place.
        setEnvelope({
          status: "provider_error",
          error_code: err instanceof ApiError ? `HTTP_${err.status}` : "REQUEST_FAILED",
          error_message:
            err instanceof ApiError
              ? err.message
              : "Request failed. Ensure the backend is running.",
          recommendation: null,
          agent_trace: [],
          provider_model: "unknown",
          correlation_id: "",
          dealer_group_id: dealerGroup,
        }),
      )
      .finally(() => setRecLoading(false));
  };

  const savePlan = () => {
    if (!rec) return;
    setSaving(true);
    api
      .savePlan({
        dealership_id: dealershipId,
        category,
        concern_text: concern,
        selected_goal: selectedGoal,
        selected_strategies: strategies,
        recommendation: rec,
        dealer_group_id: dealerGroup,
      })
      .then((plan) => {
        setSavedPlans((prev) => [...prev, plan]);
        setStep(1);
        setDealershipId("");
        setCategory("");
        setConcern("");
        setEnvelope(null);
        setSelectedGoal(null);
        setStrategies([]);
      })
      .catch(() => setSavedError("Unable to save plan."))
      .finally(() => setSaving(false));
  };

  return (
    <div className="space-y-6">
      <SetupStatus compact />

      <AgentWorkflowPanel running={recLoading} trace={trace} />

      <Card title="Guided plan builder">
        {data.dealer_groups.length > 1 && (
          <div className="mb-4">
            <label
              htmlFor="dealer-group-select"
              className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-400"
            >
              Dealer group
            </label>
            <select
              id="dealer-group-select"
              aria-label="Dealer group"
              value={dealerGroup}
              onChange={(e) => setDealerGroup(e.target.value)}
              className="w-full max-w-md rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            >
              {data.dealer_groups.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
        )}
        <ol className="space-y-4" aria-label="Plan builder steps">
          <StepRow n={1} current={step} title="Select dealership">
            <select
              aria-label="Dealership"
              value={dealershipId}
              onChange={(e) => setDealershipId(e.target.value)}
              className="w-full max-w-md rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            >
              <option value="">Choose a dealership...</option>
              {data.dealerships.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.label}
                </option>
              ))}
            </select>
          </StepRow>

          <StepRow n={2} current={step} title="Select support category">
            <select
              aria-label="Category"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setSelectedGoal(null);
                setStrategies([]);
              }}
              className="w-full max-w-md rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            >
              <option value="">Choose a category...</option>
              {data.categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </StepRow>

          <StepRow n={3} current={step} title="Describe the concern">
            <textarea
              aria-label="Concern text"
              value={concern}
              onChange={(e) => setConcern(e.target.value)}
              rows={3}
              maxLength={1000}
              placeholder="Describe the observed pattern..."
              className="w-full max-w-2xl rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            />
          </StepRow>

          <StepRow n={4} current={step} title="Generate recommendation (three agents)">
            <button
              type="button"
              disabled={!canAdvanceFromStep(3) || recLoading}
              onClick={generateRecommendation}
              className="rounded bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-40"
            >
              {recLoading ? "Running agents..." : "Generate recommendation"}
            </button>
            {envelope && envelope.status !== "ok" && (
              <div
                role="alert"
                data-testid="recommendation-error"
                className="mt-3 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-100"
              >
                <div className="font-semibold">
                  {ERROR_MESSAGES[envelope.status] ?? envelope.error_message ?? envelope.status}
                </div>
                {envelope.error_code && (
                  <div className="text-xs text-rose-200/80">Code: {envelope.error_code}</div>
                )}
              </div>
            )}
            {rec && <RecommendationPanel rec={rec} providerModel={envelope?.provider_model ?? ""} />}
          </StepRow>

          <StepRow n={5} current={step} title="Select a goal">
            {goalsForCategory.length === 0 ? (
              <p className="text-sm text-slate-400">Choose a category first.</p>
            ) : (
              <ul className="space-y-2">
                {goalsForCategory.map((goal) => (
                  <li key={goal.id}>
                    <label className="flex items-start gap-2 text-sm text-slate-200">
                      <input
                        type="radio"
                          name="goal"
                        value={goal.id}
                        checked={selectedGoal === goal.id}
                        onChange={() => setSelectedGoal(goal.id)}
                      />
                      <span>{goal.description}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </StepRow>

          <StepRow n={6} current={step} title="Select strategies">
            {strategiesForCategory.length === 0 ? (
              <p className="text-sm text-slate-400">Choose a category first.</p>
            ) : (
              <ul className="space-y-2">
                {strategiesForCategory.map((s) => (
                  <li key={s.id}>
                    <label className="flex items-start gap-2 text-sm text-slate-200">
                      <input
                        type="checkbox"
                        value={s.id}
                        checked={strategies.includes(s.id)}
                        onChange={(e) => {
                          setStrategies((prev) =>
                            e.target.checked
                              ? [...prev, s.id]
                              : prev.filter((x) => x !== s.id),
                          );
                        }}
                      />
                      <span>{s.description}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </StepRow>

          <StepRow n={7} current={step} title="Progress monitoring next steps">
            {rec ? (
              <ul className="list-disc pl-5 text-sm text-slate-300">
                {rec.progress_monitoring.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-400">Generate a recommendation to view.</p>
            )}
          </StepRow>

          <StepRow n={8} current={step} title="Save plan in memory">
            <button
              type="button"
              disabled={!rec || !selectedGoal || strategies.length === 0 || saving}
              onClick={savePlan}
              className="rounded bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-40"
            >
              {saving ? "Saving..." : "Save plan"}
            </button>
            {savedError && <p className="mt-2 text-sm text-rose-300">{savedError}</p>}
          </StepRow>
        </ol>

        <div className="mt-4 flex items-center justify-between border-t border-slate-800 pt-3 text-xs text-slate-400">
          <div>Current step: {step} of 8</div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setStep((s) => Math.max(1, (s - 1) as Step) as Step)}
              className="rounded border border-slate-700 px-3 py-1"
            >
              Back
            </button>
            <button
              type="button"
              disabled={!canAdvanceFromStep(step)}
              onClick={() => setStep((s) => Math.min(8, (s + 1) as Step) as Step)}
              className="rounded bg-slate-700 px-3 py-1 text-slate-100 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </Card>

      <Card title={`Saved plans (${savedPlans.length})`}>
        {savedPlans.length === 0 ? (
          <p className="text-sm text-slate-400">No saved plans yet.</p>
        ) : (
          <ul className="space-y-2 text-sm text-slate-300">
            {savedPlans.slice(-6).reverse().map((p) => (
              <li key={p.plan_id} className="rounded border border-slate-800 p-2">
                <div>
                  <span className="font-medium text-slate-100">{p.plan_id}</span> ·{" "}
                  {p.dealership_id} · {p.category}
                </div>
                <div className="text-xs text-slate-500">Created {p.created_at}</div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function StepRow({
  n,
  current,
  title,
  children,
}: {
  n: Step;
  current: Step;
  title: string;
  children: React.ReactNode;
}) {
  const active = n === current;
  return (
    <li
      className={`rounded border p-3 ${
        active ? "border-sky-500/60 bg-sky-500/5" : "border-slate-800 bg-slate-900/50"
      }`}
    >
      <div className="text-xs uppercase tracking-wide text-slate-400">Step {n}</div>
      <div className="mt-0.5 text-sm font-medium text-slate-100">{title}</div>
      <div className="mt-2">{children}</div>
    </li>
  );
}

function RecommendationPanel({
  rec,
  providerModel,
}: {
  rec: Recommendation;
  providerModel: string;
}) {
  const ok = rec.completeness.ok;
  // Must match PROVIDER_DISPLAY_CONFIGURED in services/api/app/config.py.
  const isFoundry = providerModel.startsWith("Azure AI Foundry");
  return (
    <div className="mt-3 rounded border border-slate-800 bg-slate-900/70 p-3 text-sm text-slate-200">
      <p className="text-xs uppercase tracking-wide text-amber-300">
        {isFoundry
          ? "Three-agent output via Azure AI Foundry"
          : `Three-agent output via ${providerModel || "unknown provider"}`}
      </p>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <p>
          <span className="text-slate-400">Detected need: </span>
          {rec.detected_need}
        </p>
        <p>
          <span className="text-slate-400">Support tier: </span>
          {rec.support_tier}
        </p>
        <p>
          <span className="text-slate-400">Frequency: </span>
          {rec.recommended_frequency}
        </p>
        <p>
          <span className="text-slate-400">Grouping: </span>
          {rec.grouping_guidance}
        </p>
        <p>
          <span className="text-slate-400">Review window: </span>
          {rec.review_window_days} days
        </p>
        <p>
          <span className="text-slate-400">Validator: </span>
          <span data-testid="completeness" className={ok ? "text-emerald-400" : "text-rose-300"}>
            {ok ? "Complete" : `Issues: ${rec.completeness.missing.join(", ")}`}
          </span>
        </p>
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-slate-400">
          Show rationale &amp; caveats
        </summary>
        <p className="mt-2 text-xs text-slate-300">{rec.rationale}</p>
        <p className="mt-1 text-xs text-slate-500">Decision rule: {rec.decision_rule}</p>
        <ul className="mt-2 list-disc pl-5 text-xs text-slate-400">
          {rec.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </details>
      <p className="mt-2 text-xs text-slate-500">{rec.generated_by}</p>
    </div>
  );
}


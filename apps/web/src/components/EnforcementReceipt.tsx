import type { RecommendationEnvelope } from "../api/types";

interface Props {
  envelope: RecommendationEnvelope;
}

/** Examples, not observations: what each control rejects when it fires. */
const REJECTS = [
  "a citation id the retriever did not return for this dealer group",
  "a resource id outside the request's allowed catalog, such as RES-999",
  'a plan whose caveats omit the phrase "human review"',
  'a determination such as "authorise a discount of $500"',
  "a draft stamped GROUP-B on a GROUP-A request",
];

function has(value: number | null | undefined): value is number {
  return typeof value === "number";
}

export function EnforcementReceipt({ envelope }: Props) {
  const {
    evidence_count,
    citations_proposed,
    citations_accepted,
    unknown_resource_ids,
    validation_reached,
    deterministic_checks_total,
    attempts,
    validator_status,
    dealer_group_id,
  } = envelope;

  const lines: string[] = [];

  if (has(evidence_count)) {
    lines.push(
      `Retrieval was issued scoped to ${dealer_group_id} and returned ${evidence_count} document(s).`,
    );
  }

  if (has(citations_proposed) && has(citations_accepted)) {
    const dropped = citations_proposed - citations_accepted;
    lines.push(
      `The model proposed ${citations_proposed} citation id(s); ${citations_accepted} matched the retrieved bundle` +
        (dropped > 0 ? ` and ${dropped} were dropped as absent from it.` : ".") +
        " The model selects citation ids; the application substitutes the retriever's stored citation text.",
    );
  }

  if ((unknown_resource_ids ?? []).length > 0) {
    lines.push(
      `Resource id(s) outside the request's allowed catalog: ${(unknown_resource_ids ?? []).join(", ")}.`,
    );
  }

  if (validation_reached && has(deterministic_checks_total)) {
    const summary = (validator_status ?? "").trim().replace(/\.$/, "");
    lines.push(
      `All ${deterministic_checks_total} deterministic checks were applied to this output` +
        (summary ? ` — ${summary}.` : "."),
    );
  } else if (validation_reached === false) {
    lines.push("Validation not reached: the run ended before the checks could be applied.");
  }

  if (has(attempts) && attempts > 1) {
    lines.push(`The recommender ran ${attempts} times; the repair edge fired once.`);
  }

  const steps = envelope.agent_trace ?? [];
  // A step can carry the model provider without making a model call: evidence
  // retrieval reports the retriever, and the validator's repair pass skips the
  // advisory critique and reports model "none".
  const modelSteps = steps.filter(
    (s) => s.provider === "azure_foundry_responses" && s.model && s.model !== "none",
  );
  if (modelSteps.length > 0) {
    const known = modelSteps.filter((s) => typeof s.token_estimate === "number");
    if (known.length > 0) {
      const total = known.reduce((sum, s) => sum + (s.token_estimate ?? 0), 0);
      const latency = steps.reduce((sum, s) => sum + (s.latency_ms ?? 0), 0);
      // A model step with no reported usage is unknown, not zero, so a
      // partial sum is stated as a floor.
      const prefix = known.length === modelSteps.length ? "" : "at least ";
      lines.push(
        `This run cost ${prefix}${total} tokens across ${modelSteps.length} model call(s), ${latency} ms of agent time.`,
      );
    }
  }

  if (lines.length === 0) {
    return null;
  }

  return (
    <div
      aria-label="Enforcement receipt"
      data-testid="enforcement-receipt"
      className="rounded-lg border border-slate-800 bg-slate-900/70 p-4"
    >
      <h3 className="text-sm font-semibold text-slate-100">What ran on this output</h3>
      <p className="mt-1 text-xs text-slate-400">
        Application controls, not a quality score. These say what was enforced, not whether the
        plan is any good.
      </p>
      <ul className="mt-3 space-y-1.5 text-xs text-slate-300">
        {lines.map((line) => (
          <li key={line} className="flex gap-2">
            <span aria-hidden="true" className="text-emerald-300">
              &#8226;
            </span>
            <span>{line}</span>
          </li>
        ))}
      </ul>
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-slate-400">What these checks reject</summary>
        <ul className="mt-2 space-y-1 pl-4 text-xs text-slate-500">
          {REJECTS.map((item) => (
            <li key={item} className="list-disc">
              {item}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

import { SetupStatus } from "../components/SetupStatus";
import { Card } from "../components/Card";

export function DemoGuidePage() {
  return (
    <div className="space-y-6">
      <Card title="Demo guide">
        <p className="text-sm text-slate-200">
          This prototype demonstrates a generic learner-support workflow. All values on
          screen are synthetic. When the backend is connected to Azure AI Foundry, three
          collaborating agents run on real language-model calls to produce a structured
          support recommendation for a chosen learner and category.
        </p>
        <p className="mt-3 rounded border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-300">
          This prototype uses synthetic data. It is intended to demonstrate architecture
          and workflow patterns, not to make production educational, legal, compliance,
          medical, disability, or placement decisions.
        </p>
      </Card>

      <Card title="Setup status">
        <SetupStatus />
      </Card>

      <Card title="Recommended demo sequence (5-7 minutes)">
        <ol className="list-decimal space-y-2 pl-5 text-sm text-slate-200">
          <li>
            <span className="font-medium text-slate-100">Dashboard.</span> Open the
            Dashboard to introduce the demo. Point out the four KPI cards and the
            proficiency / domain charts. Say the numbers are synthetic signals used to
            illustrate the shape of a support workflow.
          </li>
          <li>
            <span className="font-medium text-slate-100">Assessments.</span> Switch the
            filters and show the trend chart update. Highlight the "Local rule-based
            output" panel: this shows how a non-agent summary sits next to charts.
          </li>
          <li>
            <span className="font-medium text-slate-100">Supports.</span> Walk through
            the guided plan builder: pick a learner, pick a category, type a short
            concern, and click <em>Generate recommendation</em>. Explain that this is
            where the three agents run.
          </li>
          <li>
            <span className="font-medium text-slate-100">Agent workflow panel.</span>{" "}
            Show the three agents rendering in order:
            <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-300">
              <li>
                <span className="text-slate-100">Data Analyst Agent</span> reviews the
                synthetic evidence for the chosen learner.
              </li>
              <li>
                <span className="text-slate-100">Support Recommendation Agent</span>{" "}
                proposes support options from an allowed catalog.
              </li>
              <li>
                <span className="text-slate-100">Validator Agent</span> checks
                structure, safety wording, and grounding before the recommendation is
                shown.
              </li>
            </ul>
          </li>
          <li>
            <span className="font-medium text-slate-100">Read the recommendation.</span>{" "}
            Point at detected need, support tier, review window, and the required
            human-review caveat.
          </li>
          <li>
            <span className="font-medium text-slate-100">AI Audit.</span> Open the
            AI Audit page. Show that only metadata is recorded (timestamp, endpoint,
            provider/model, duration, token estimate, status). No prompts, completions,
            raw concern text, or secrets are stored.
          </li>
          <li>
            <span className="font-medium text-slate-100">Close.</span> Reiterate that
            all data is synthetic and the app is a prototype for architecture and
            workflow patterns.
          </li>
        </ol>
      </Card>

      <Card title="What Azure AI Foundry is doing">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-200">
          <li>
            Hosting the language-model deployment that each agent calls with a
            structured JSON contract.
          </li>
          <li>
            Providing keyless authentication through Microsoft Entra ID and
            role-based access.
          </li>
          <li>
            Sitting inside an Azure AI Foundry project - the same organizational unit
            used for future hosted agents, evaluations, and safety workflows.
          </li>
        </ul>
      </Card>

      <Card title="How to confirm you are on Azure AI Foundry (not a test double)">
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-200">
          <li>
            The banner at the top of this page should show{" "}
            <span className="font-mono">Customer demo ready</span>.
          </li>
          <li>
            <span className="font-mono">Active provider</span> above should read{" "}
            <span className="font-mono">azure_foundry</span>.
          </li>
          <li>
            Open the AI Audit page after generating a recommendation. The runtime rows
            should show <span className="font-mono">azure-openai / &lt;deployment&gt;</span>{" "}
            in the provider/model column.
          </li>
        </ol>
      </Card>

      <Card title="Reset the demo">
        <p className="text-sm text-slate-200">
          Application state lives in memory. To reset saved plans and runtime audit
          rows, restart the backend. A guarded reset endpoint is also available for
          development machines when <span className="font-mono">DEMO_RESET_ENABLED=true</span>
          is set; it is disabled by default.
        </p>
      </Card>
    </div>
  );
}

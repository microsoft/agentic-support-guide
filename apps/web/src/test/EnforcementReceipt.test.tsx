import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { AgentTraceStep, RecommendationEnvelope } from "../api/types";
import { EnforcementReceipt } from "../components/EnforcementReceipt";
import { AgentWorkflowPanel } from "../components/AgentWorkflowPanel";

const base: RecommendationEnvelope = {
  status: "ok",
  error_code: null,
  error_message: null,
  recommendation: null,
  agent_trace: [],
  provider_model: "remote",
  correlation_id: "abc",
  dealer_group_id: "GROUP-A",
};

function step(overrides: Partial<AgentTraceStep>): AgentTraceStep {
  return {
    agent: "support-recommendation-agent",
    status: "ok",
    provider: "azure_foundry_responses",
    model: "remote",
    latency_ms: 5,
    token_estimate: 10,
    issue_codes: [],
    warning_codes: [],
    ...overrides,
  };
}

describe("EnforcementReceipt", () => {
  it("reports the citation accounting and the checks that were applied", () => {
    render(
      <EnforcementReceipt
        envelope={{
          ...base,
          evidence_count: 4,
          citations_proposed: 3,
          citations_accepted: 2,
          validation_reached: true,
          deterministic_checks_total: 8,
          validator_status: "passed",
          attempts: 1,
        }}
      />,
    );

    expect(screen.getByTestId("enforcement-receipt")).toBeInTheDocument();
    expect(screen.getByText(/proposed 3 citation id/i)).toBeInTheDocument();
    expect(screen.getByText(/1 were dropped as absent/i)).toBeInTheDocument();
    expect(screen.getByText(/All 8 deterministic checks/i)).toBeInTheDocument();
    expect(screen.getByText(/scoped to GROUP-A/i)).toBeInTheDocument();
  });

  it("renders nothing when the envelope carries no enforcement fields", () => {
    // The transport-failure envelope the page synthesises. Absent must not
    // render as zero.
    const { container } = render(<EnforcementReceipt envelope={base} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says validation was not reached rather than showing a zero score", () => {
    render(
      <EnforcementReceipt envelope={{ ...base, evidence_count: 2, validation_reached: false }} />,
    );
    expect(screen.getByText(/Validation not reached/i)).toBeInTheDocument();
    expect(screen.queryByText(/deterministic checks/i)).not.toBeInTheDocument();
  });

  it("lists out-of-catalog resource ids when the run was withheld", () => {
    render(
      <EnforcementReceipt
        envelope={{ ...base, evidence_count: 1, unknown_resource_ids: ["RES-999"] }}
      />,
    );
    expect(screen.getByText(/^Resource id\(s\) outside the request's allowed catalog: RES-999\.$/))
      .toBeInTheDocument();
  });

  it("states a partial token sum as a floor rather than a total", () => {
    render(
      <EnforcementReceipt
        envelope={{
          ...base,
          evidence_count: 1,
          agent_trace: [
            step({ token_estimate: 100, latency_ms: 5 }),
            step({ agent: "validator-agent", token_estimate: null, latency_ms: 5 }),
          ],
        }}
      />,
    );
    expect(screen.getByText(/at least 100 tokens across 2 model call\(s\)/i)).toBeInTheDocument();
  });

  it("does not count evidence retrieval as a model call", () => {
    // Caught on a live run: the retrieval step has no token usage, which both
    // inflated the call count and falsely triggered the "at least" hedge.
    render(
      <EnforcementReceipt
        envelope={{
          ...base,
          evidence_count: 1,
          agent_trace: [
            step({ agent: "evidence-retrieval", provider: "foundry_iq", token_estimate: null }),
            step({ token_estimate: 60 }),
            step({ agent: "validator-agent", token_estimate: 40 }),
          ],
        }}
      />,
    );
    expect(screen.getByText(/This run cost 100 tokens across 2 model call\(s\)/i)).toBeInTheDocument();
  });

  it("does not double the full stop after the validator summary", () => {
    render(
      <EnforcementReceipt
        envelope={{
          ...base,
          evidence_count: 1,
          validation_reached: true,
          deterministic_checks_total: 8,
          validator_status: "Validator passed all deterministic checks.",
        }}
      />,
    );
    expect(
      screen.getByText(/Validator passed all deterministic checks\.$/),
    ).toBeInTheDocument();
  });

  it("does not count the validator's repair pass as a model call", () => {
    // Caught on a forced refusal: the second validator pass skips the
    // advisory critique, so it reports model "none" and makes no call.
    render(
      <EnforcementReceipt
        envelope={{
          ...base,
          evidence_count: 1,
          agent_trace: [
            step({ agent: "evidence-retrieval", provider: "foundry_iq", token_estimate: null }),
            step({ token_estimate: 60 }),
            step({ agent: "validator-agent", token_estimate: 40 }),
            step({ agent: "support-recommendation-agent:repair", token_estimate: 50 }),
            step({ agent: "validator-agent", model: "none", token_estimate: null }),
          ],
        }}
      />,
    );
    expect(screen.getByText(/This run cost 150 tokens across 3 model call\(s\)/i)).toBeInTheDocument();
  });

  it("reports advisory warnings raised alongside a pass", () => {
    // A deployed run passed while raising two warnings, and the receipt
    // showed only the verdict, which read as an all-clear.
    render(
      <EnforcementReceipt
        envelope={{
          ...base,
          validation_reached: true,
          deterministic_checks_total: 8,
          validator_status: "Validator passed all deterministic checks.",
          agent_trace: [
            step({
              agent: "validator-agent",
              warning_codes: ["MISSING_DATA_FIRST_RESPONSE_TIME", "HUMAN_REVIEW_REQUIRED"],
            }),
          ],
        }}
      />,
    );
    expect(
      screen.getByText(/2 advisory warning\(s\) that do not fail validation/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/MISSING_DATA_FIRST_RESPONSE_TIME/)).toBeInTheDocument();
  });

  it("says nothing about warnings when the validator raised none", () => {
    render(
      <EnforcementReceipt
        envelope={{
          ...base,
          validation_reached: true,
          deterministic_checks_total: 8,
          agent_trace: [step({ agent: "validator-agent" })],
        }}
      />,
    );
    expect(screen.queryByText(/advisory warning/i)).not.toBeInTheDocument();
  });

  it("states a complete token sum without hedging", () => {
    render(
      <EnforcementReceipt
        envelope={{
          ...base,
          evidence_count: 1,
          agent_trace: [step({ token_estimate: 60 }), step({ token_estimate: 40 })],
        }}
      />,
    );
    expect(screen.getByText(/This run cost 100 tokens/i)).toBeInTheDocument();
  });
});

describe("AgentWorkflowPanel repair visibility", () => {
  it("shows both recommender attempts instead of collapsing the repair", () => {
    render(
      <AgentWorkflowPanel
        running={false}
        trace={[
          step({ agent: "data-analyst-agent" }),
          step({
            agent: "support-recommendation-agent",
            status: "failed",
            issue_codes: ["MISSING_CITATIONS"],
          }),
          step({ agent: "support-recommendation-agent:repair", status: "ok" }),
          step({ agent: "validator-agent", status: "passed" }),
        ]}
      />,
    );

    const attempts = screen.getByTestId("agent-attempts-2");
    expect(attempts).toBeInTheDocument();
    expect(attempts).toHaveTextContent(/Attempt 1/);
    expect(attempts).toHaveTextContent(/MISSING_CITATIONS/);
    expect(attempts).toHaveTextContent(/Attempt 2/);
  });

  it("does not render an attempts list when nothing was repaired", () => {
    render(
      <AgentWorkflowPanel
        running={false}
        trace={[
          step({ agent: "data-analyst-agent" }),
          step({ agent: "support-recommendation-agent" }),
          step({ agent: "validator-agent", status: "passed" }),
        ]}
      />,
    );
    expect(screen.queryByTestId("agent-attempts-2")).not.toBeInTheDocument();
  });
});

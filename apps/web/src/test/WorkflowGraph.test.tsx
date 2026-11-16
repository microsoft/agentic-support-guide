import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import { WorkflowGraph } from "../components/WorkflowGraph";
import type { AgentTraceStep } from "../api/types";

function step(agent: string, status: string): AgentTraceStep {
  return { agent, status, provider: "fixture", model: "none", latency_ms: 100, token_estimate: null };
}

const ACCEPTED = [
  step("evidence-retrieval", "ok"),
  step("data-analyst-agent", "ok"),
  step("support-recommendation-agent", "ok"),
  step("validator-agent", "passed"),
];

const REFUSED = [
  step("evidence-retrieval", "ok"),
  step("data-analyst-agent", "ok"),
  step("support-recommendation-agent", "ok"),
  step("validator-agent", "failed"),
];

function fillOf(container: HTMLElement, node: string): string | null {
  const g = [...container.querySelectorAll("g.node")].find(
    (el) => el.querySelector("title")?.textContent?.trim() === node,
  );
  return g?.querySelector("polygon")?.getAttribute("fill") ?? null;
}

describe("WorkflowGraph", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("draws the committed graph on the first render", () => {
    const { container } = render(<WorkflowGraph running={false} trace={[]} />);

    expect(container.querySelectorAll("g.node")).toHaveLength(6);
    expect(container.querySelectorAll("g.edge")).toHaveLength(6);
    expect(container.querySelector("script")).toBeNull();
    expect(fillOf(container, "retrieve-evidence")).toBe("lightgreen");
  });

  it("lights only the terminal a run reached and resets every node for the next run", () => {
    vi.useFakeTimers();
    const { container, rerender } = render(<WorkflowGraph running={false} trace={ACCEPTED} />);
    act(() => {
      vi.runAllTimers();
    });
    expect(fillOf(container, "finalise")).toBe("#34d399");
    expect(fillOf(container, "refuse")).toBe("lightblue");

    rerender(<WorkflowGraph running trace={[]} />);
    expect(fillOf(container, "finalise")).toBe("lightblue");
    expect(fillOf(container, "validator")).toBe("lightblue");
    expect(fillOf(container, "retrieve-evidence")).toBe("lightgreen");

    rerender(<WorkflowGraph running={false} trace={REFUSED} />);
    act(() => {
      vi.runAllTimers();
    });
    expect(fillOf(container, "refuse")).toBe("#fb7185");
    expect(fillOf(container, "validator")).toBe("#fb7185");
    expect(fillOf(container, "finalise")).toBe("lightblue");
  });
});

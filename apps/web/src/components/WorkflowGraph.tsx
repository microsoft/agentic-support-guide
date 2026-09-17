import { useEffect, useRef, useState } from "react";
import type { AgentTraceStep } from "../api/types";

interface Props {
  running: boolean;
  trace: AgentTraceStep[];
}

/** Graphviz node id -> the trace step that proves it ran. */
const SEQUENCE = [
  { node: "retrieve-evidence", agent: "evidence-retrieval" },
  { node: "data-analyst", agent: "data-analyst-agent" },
  { node: "support-recommender", agent: "support-recommendation-agent" },
  { node: "validator", agent: "validator-agent" },
] as const;

const OK = new Set(["ok", "passed"]);
const FILL = { done: "#34d399", active: "#38bdf8", failed: "#fb7185" };

// The replay is a teaching aid, not a stopwatch: real latencies vary from
// under a second to tens of seconds, so they are scaled into a watchable range.
const REPLAY_TOTAL_MS = 2600;
const MIN_STEP_MS = 260;

function paint(root: SVGElement, node: string, fill: string | null, pulse: boolean) {
  const g = [...root.querySelectorAll("g.node")].find(
    (el) => el.querySelector("title")?.textContent?.trim() === node,
  );
  const shape = g?.querySelector("polygon, ellipse") as SVGElement | undefined;
  if (!g || !shape) return;
  if (fill) {
    shape.setAttribute("fill", fill);
    shape.setAttribute("stroke-width", "2");
  } else {
    shape.removeAttribute("stroke-width");
  }
  g.classList.toggle("wf-pulse", pulse);
}

// Our own build artifact, served same-origin, but it is injected as markup:
// strip anything executable so a tampered asset cannot become script execution.
function sanitizeSvg(raw: string): string {
  return raw
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/\son\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, "")
    .replace(/(href|xlink:href)\s*=\s*(?:"|')?\s*javascript:[^"'\s>]*/gi, "");
}

export function WorkflowGraph({ running, trace }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [markup, setMarkup] = useState<string>("");
  const [cursor, setCursor] = useState<number>(-1);

  useEffect(() => {
    let cancelled = false;
    fetch("/workflow-graph.svg")
      .then((r) => (r.ok ? r.text() : ""))
      .then((t) => {
        if (!cancelled) setMarkup(sanitizeSvg(t));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Replay the path the run actually took, paced by its own step latencies.
  useEffect(() => {
    const ran = SEQUENCE.filter((s) => trace.some((t) => t.agent.replace(":repair", "") === s.node || t.agent === s.agent));
    if (running || ran.length === 0) {
      setCursor(-1);
      return;
    }
    const weights = SEQUENCE.map((s) => {
      const step = trace.find((t) => t.agent === s.agent);
      return Math.max(step?.latency_ms ?? 0, 1);
    });
    const total = weights.reduce((a, b) => a + b, 0);
    const timers: number[] = [];
    let elapsed = 0;
    SEQUENCE.forEach((_, i) => {
      elapsed += Math.max((weights[i] / total) * REPLAY_TOTAL_MS, MIN_STEP_MS);
      timers.push(window.setTimeout(() => setCursor(i), elapsed));
    });
    // One tick past the end so nothing is left pulsing as though still running.
    timers.push(window.setTimeout(() => setCursor(SEQUENCE.length), elapsed + MIN_STEP_MS));
    setCursor(-1);
    return () => timers.forEach(window.clearTimeout);
  }, [trace, running]);

  useEffect(() => {
    const svg = host.current?.querySelector("svg");
    if (!svg) return;
    const byAgent = new Map(trace.map((t) => [t.agent, t]));

    SEQUENCE.forEach((s, i) => {
      const step = byAgent.get(s.agent);
      if (running) {
        paint(svg, s.node, null, true);
        return;
      }
      if (!step || i > cursor) {
        paint(svg, s.node, null, false);
        return;
      }
      const failed = !OK.has(step.status);
      paint(svg, s.node, failed ? FILL.failed : i === cursor ? FILL.active : FILL.done, i === cursor);
    });

    const validator = byAgent.get("validator-agent");
    const finished = !running && cursor >= SEQUENCE.length - 1 && validator;
    const refused = finished && !OK.has(validator.status);
    paint(svg, "finalise", finished && !refused ? FILL.done : null, false);
    paint(svg, "refuse", refused ? FILL.failed : null, false);
  }, [cursor, running, trace, markup]);

  const caption = running
    ? "Running. The app cannot see which node is active until the run returns."
    : trace.length > 0
    ? "Replaying the path this run actually took, paced by its own step latencies."
    : "Green is the start node; dashed edges are conditional.";

  return (
    <div className="mt-3 rounded bg-slate-950/60 p-2">
      <style>{`@keyframes wfPulse{0%,100%{opacity:1}50%{opacity:.45}}.wf-pulse{animation:wfPulse 1.1s ease-in-out infinite}`}</style>
      <p className="text-xs font-semibold text-slate-300">Workflow graph</p>
      <p className="mt-1 text-xs text-slate-400">
        Rendered by Agent Framework&apos;s <code>WorkflowViz</code> from the same graph
        this request runs, so it cannot drift from the code. {caption}
      </p>
      <div
        ref={host}
        data-testid="workflow-graph"
        role="img"
        aria-label="The plan workflow graph: retrieve evidence, analyse, recommend, validate, then finalise, with conditional edges from validate back to recommend for one repair attempt and onward to refuse when repair is exhausted."
        className="mx-auto mt-2 w-fit rounded bg-white p-2 [&_svg]:h-auto [&_svg]:max-h-96 [&_svg]:w-auto"
        dangerouslySetInnerHTML={{ __html: markup }}
      />
    </div>
  );
}

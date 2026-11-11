"""The workflow, as a Microsoft Agent Framework graph.

This is the whole orchestration. Six nodes and six edges:

    retrieve-evidence -> data-analyst -> support-recommender -> validator
                                 ^                                 |
                                 +--------- one repair ------------+
                                                                   |
                                             passed -> finalise    |
                                           exhausted -> refuse  <--+

Sequential orchestration with one conditional repair edge. The order is
fixed; no agent chooses who runs next. The only branch is the validator's
verdict, decided by the deterministic checks in
`app/agents/validator/checks.py`.

`WorkflowViz(build_plan_workflow(...)).to_mermaid()` draws it, and
`python/scripts/render_workflow_diagram.py` puts that picture in the workshop.

https://learn.microsoft.com/agent-framework/workflows/orchestrations/sequential
"""

from __future__ import annotations

from agent_framework import Workflow, WorkflowBuilder

from ..agents.data_analyst import DataAnalystAgent
from ..agents.support_recommender import SupportRecommendationAgent
from ..agents.validator import ValidatorAgent
from ..evidence import EvidenceRetriever
from ..foundry_agents.maf_runtime import MafAgentRuntime
from .executors import (
    Analyse,
    Finalise,
    PlanRun,
    Recommend,
    Refuse,
    RetrieveEvidence,
    Validate,
)
from .plan import needs_repair, passed, repair_exhausted
from .results import CoordinatorRequest, RunContext


def build_plan_workflow(
    *,
    request: CoordinatorRequest,
    context: RunContext,
    runtime: MafAgentRuntime,
    evidence_retriever: EvidenceRetriever,
    provider_display: str,
) -> Workflow:
    """Build one workflow for one request.

    Never cached. A `Workflow` instance rejects concurrent runs, and these
    nodes hold this request's identity, so two callers must not share one.
    """

    run = PlanRun(request=request, context=context)

    retrieve = RetrieveEvidence(run, evidence_retriever)
    analyse = Analyse(run, DataAnalystAgent(runtime))
    recommend = Recommend(run, SupportRecommendationAgent(runtime))
    validate = Validate(run, ValidatorAgent(runtime))
    finalise = Finalise(run, provider_display)
    refuse = Refuse(run)

    return (
        WorkflowBuilder(
            start_executor=retrieve,
            name="support-plan",
            description="Sequential orchestration with one conditional repair edge.",
            # Only these two produce the run's result. Naming them keeps a
            # future yield from joining it.
            output_from=[finalise, refuse],
            # The working nodes yield their trace rows; these arrive on the
            # event stream as intermediate outputs, never as the result.
            intermediate_output_from=[retrieve, analyse, recommend, validate],
        )
        .add_edge(retrieve, analyse)
        .add_edge(analyse, recommend)
        .add_edge(recommend, validate)
        .add_edge(validate, finalise, condition=passed)
        .add_edge(validate, recommend, condition=needs_repair)
        .add_edge(validate, refuse, condition=repair_exhausted)
        .build()
    )

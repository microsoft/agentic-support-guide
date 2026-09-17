from __future__ import annotations

from typing import Any

from app.agents.data_analyst import DataAnalystAgent
from app.agents.support_recommender import SupportRecommendationAgent
from app.agents.validator import ValidatorAgent, ValidatorContext, ValidatorInput

from .conftest import (
    DEFAULT_DEALER_GROUP,
    canned_data_analyst_output,
    canned_recommendation_draft,
)
from .fakes import FakeChatClientFactory, make_fake_runtime
from .test_agents import _analyst_ctx, _bundle, _rec_ctx


def _runtime_with_adversarial_critique(critique: dict[str, Any]) -> Any:
    client = FakeChatClientFactory()
    client.register_response(
        "data-analyst-agent",
        canned_data_analyst_output(),
    )
    client.register_response(
        "support-recommendation-agent",
        canned_recommendation_draft(
            goal_ids=["GOAL-lead-response-1"],
            strategy_ids=["ST-lead-response-1"],
        ),
    )
    client.register_response(
        "validator-agent",
        critique,
    )
    return make_fake_runtime(client)[0]


async def test_validator_drops_non_conforming_llm_warnings() -> None:
    runtime = _runtime_with_adversarial_critique(
        {
            "warning_codes": [
                "leaked user secret abcdef",
                "here is the concern: password=hunter2",
                "OK",
                "REAL_WARNING_CODE",
                "lower_case_should_drop",
                "  TRIMMED_CODE  ",
            ],
            "repair_guidance": "",
        }
    )
    analysis = await DataAnalystAgent(runtime).analyze(_analyst_ctx())
    draft = await SupportRecommendationAgent(runtime).recommend(analysis, await _rec_ctx())
    bundle = await _bundle()
    report = await ValidatorAgent(runtime).validate(
        ValidatorInput(
            analysis=analysis,
            draft=draft,
            context=ValidatorContext(
                dealer_group_id=DEFAULT_DEALER_GROUP,
                allowed_resource_ids=(),
                allowed_goal_ids=("GOAL-lead-response-1",),
                allowed_strategy_ids=("ST-lead-response-1",),
                allowed_citation_ids=tuple(c.citation_id for c in bundle.citations),
                required_contract_version="1.0.0",
            ),
        ),
        use_llm_critique=True,
    )
    assert set(report.warning_codes) == {"REAL_WARNING_CODE", "TRIMMED_CODE"}
    for w in report.warning_codes:
        assert "password" not in w.lower()
        assert "concern" not in w.lower()


def test_every_issue_code_a_check_can_emit_has_repair_guidance() -> None:
    """Catches a new validator rule that forgot its repair template.

    The codes are read out of checks.py rather than listed here, so adding a
    rule cannot pass by also updating a hand-maintained list in this test.
    """

    import ast
    import inspect

    from app.agents.validator import checks
    from app.agents.validator.repair import REPAIRABLE_ISSUE_CODES

    tree = ast.parse(inspect.getsource(checks))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "flag"
    ]
    assert calls, "found no findings.flag(...) calls; the AST scan is broken"

    # A code built at runtime cannot be checked against the templates, so the
    # scan refuses to pass rather than reporting coverage it did not verify.
    dynamic = [
        node
        for node in calls
        if not node.args
        or not isinstance(node.args[0], ast.Constant)
        or not isinstance(node.args[0].value, str)
    ]
    assert not dynamic, (
        "findings.flag() called with a non-literal issue code at line(s) "
        f"{sorted(n.lineno for n in dynamic)}; this test cannot verify those"
    )

    emitted = {
        node.args[0].value
        for node in calls
        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
    }
    assert emitted <= REPAIRABLE_ISSUE_CODES, (
        f"issue codes with no repair template: {sorted(emitted - REPAIRABLE_ISSUE_CODES)}"
    )

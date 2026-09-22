import type {
  ScoresSummary,
  AuditResponse,
  DashboardSummary,
  HealthDetailsResponse,
  HealthResponse,
  Recommendation,
  RecommendationEnvelope,
  SavedPlansResponse,
  SupportOptions,
} from "../api/types";

export const healthFixture: HealthResponse = {
  status: "ok",
  service: "agentic-support-guide-api",
  version: "0.3.0",
  banner: "Prototype",
  provider_configured: false,
  foundry_auth_mode: "entra",
  build_id: "test-build",
};

export const healthDetailsNotReadyFixture: HealthDetailsResponse = {
  status: "ok",
  service: "agentic-support-guide-api",
  version: "0.3.0",
  active_provider: "unconfigured",
  foundry_project_configured: false,
  agent_definitions_valid: false,
  model_deployments_configured: false,
  service_side_remote_workflow_active: false,
  evidence_fixture_available: false,
  evidence_source: "fixture",
  evidence_knowledge_base: "synthetic",
  evidence_verified: false,
  api_auth_mode: "unprotected",
  dealer_group_isolation_enabled: true,
  customer_demo_ready: false,
  checks: [
    { name: "backend", label: "Backend service running", ok: true, detail: "ok" },
    {
      name: "foundry_project_endpoint",
      label: "Microsoft Foundry project endpoint configured",
      ok: false,
      detail: "Not set. Populate AZURE_AI_FOUNDRY_PROJECT_ENDPOINT.",
    },
    {
      name: "agent_definitions_valid",
      label: "Foundry agent bindings present",
      ok: false,
      detail:
        "One or more roles are not bound. Run scripts/validate_agent_definitions.py.",
    },
  ],
  warnings: [
    "Microsoft Foundry project endpoint is not configured. Recommendation requests will fail.",
  ],
  guidance: "Not demo-ready. Finish Terraform + .env setup + validate_agent_definitions.py.",
};

export const healthDetailsReadyFixture: HealthDetailsResponse = {
  status: "ok",
  service: "agentic-support-guide-api",
  version: "0.3.0",
  active_provider: "azure_foundry_responses",
  foundry_project_configured: true,
  agent_definitions_valid: true,
  model_deployments_configured: true,
  service_side_remote_workflow_active: true,
  evidence_fixture_available: true,
  evidence_source: "fixture",
  evidence_knowledge_base: "synthetic",
  evidence_verified: true,
  api_auth_mode: "shared_key",
  dealer_group_isolation_enabled: true,
  customer_demo_ready: true,
  checks: [
    { name: "backend", label: "Backend service running", ok: true, detail: "ok" },
    {
      name: "foundry_project_endpoint",
      label: "Microsoft Foundry project endpoint configured",
      ok: true,
      detail: "Set.",
    },
    {
      name: "agent_definitions_valid",
      label: "Foundry agent bindings present",
      ok: true,
      detail: "All required roles are bound to remote Foundry agents.",
    },
  ],
  warnings: [],
  guidance: "Ready for a live demo.",
};

export const dashboardFixture: DashboardSummary = {
  kpi_cards: [
    { id: "kpi-dealerships", label: "Active Dealerships", value: 120, unit: "count", delta: 0, trend: "steady" },
    { id: "kpi-flagged", label: "Flagged for Support", value: 30, unit: "count", delta: 25, trend: "watch" },
    { id: "kpi-process-score", label: "Avg Process Score", value: 62.5, unit: "index", delta: 1.2, trend: "up" },
    { id: "kpi-appointments", label: "Avg Attendance", value: 91.4, unit: "percent", delta: -0.4, trend: "down" },
  ],
  process_score_trend: [
    { period: "2026-P01", value: 55.2 },
    { period: "2026-P02", value: 57.1 },
  ],
  area_distribution: [
    { process_area: "lead-response", value: 60 },
    { process_area: "listing-completeness", value: 65 },
  ],
  engagement_trend: [
    { period: "2026-P01", value: 65 },
    { period: "2026-P02", value: 68 },
  ],
  notes: ["All values are synthetic and generated locally."],
};

export const assessmentsFixture: ScoresSummary = {
  filters_applied: { region: null, process_area: null, segment: null },
  total_records: 3,
  band_distribution: [
    { label: "At risk", count: 1, percent: 33.3 },
    { label: "Developing", count: 1, percent: 33.3 },
    { label: "On track", count: 1, percent: 33.3 },
    { label: "Leading", count: 0, percent: 0 },
  ],
  area_trends: [
    { process_area: "lead-response", points: [{ period: "2026-04", value: 50 }] },
  ],
  recommendation_bullets: ["Consider a focused coaching cycle."],
  performance_summary: "Illustrative synthetic summary.",
  generated_by: "Generated from local rules over synthetic data.",
  table_rows: [
    {
      record_id: "SCR-00001",
      dealership_id: "DLR-0001",
      region_id: "REG-001",
      segment: "SEG-VOLUME",
      process_area: "lead-response",
      band: "At risk",
      score: 35,
      period: "2026-04",
    },
  ],
};

export const supportOptionsFixture: SupportOptions = {
  dealer_groups: ["GROUP-DEMO"],
  dealerships: [
    { id: "DLR-0001", label: "Dealership 0001" },
    { id: "DLR-0002", label: "Dealership 0002" },
  ],
  categories: [
    { id: "lead-response", label: "Enquiry Response", description: "desc" },
    { id: "listing-completeness", label: "Listing Completeness", description: "desc" },
  ],
  goals: [
    {
      id: "GOAL-lead-response-1",
      label: "goal 1",
      category_id: "lead-response",
      description: "Increase same-day enquiry replies.",
    },
  ],
  strategies: [
    {
      id: "ST-lead-response-1",
      label: "Strategy 1",
      category_id: "lead-response",
      description: "Daily 15-minute enquiry triage routine.",
    },
  ],
};

export const savedPlansFixture: SavedPlansResponse = {
  plans: [],
  total: 0,
};

export const recommendationFixture: Recommendation = {
  dealer_group_id: "GROUP-DEMO",
  detected_need: "Slow enquiry response",
  evidence_summary: ["Process score (synthetic): 35.0"],
  rationale: "Rule-based rationale.",
  support_tier: "Intensive",
  recommended_frequency: "4-5x weekly",
  grouping_guidance: "1:1 or 1:2",
  resource_matches: [],
  manager_next_steps: ["Confirm baseline."],
  progress_monitoring: ["Weekly probe."],
  review_window_days: 28,
  decision_rule: "IF ...",
  caveats: ["Illustrative only.", "Human review is required."],
  goal_suggestions: ["GOAL-lead-response-1"],
  strategy_suggestions: ["ST-lead-response-1"],
  citations: [
    {
      citation_id: "GROUP-DEMO-el-01",
      dealer_group_id: "GROUP-DEMO",
      source_type: "synthetic_fixture",
      source_title: "Demo group - Enquiry Response Fixture",
      section_or_page: "",
      evidence_summary: "Illustrative synthetic reference used only for the customer demo.",
      source_ref: "fixture://group-demo/lr-01",
      retrieved_at: "2026-01-05T09:00:00Z",
      confidence: 0.8,
    },
  ],
  completeness: { ok: true, missing: [] },
  human_review_state: "pending_review",
  generated_by:
    "Generated by three collaborating agents via Microsoft Foundry (Agent Framework, prompt agents).",
};

export const envelopeOkFixture: RecommendationEnvelope = {
  status: "ok",
  error_code: null,
  error_message: null,
  recommendation: recommendationFixture,
  agent_trace: [
    {
      agent: "data-analyst-agent",
      status: "ok",
      provider: "azure_foundry_responses",
      model: "remote",
      latency_ms: 5,
      token_estimate: 100,
      issue_codes: [],
      warning_codes: [],
    },
    {
      agent: "support-recommendation-agent",
      status: "ok",
      provider: "azure_foundry_responses",
      model: "remote",
      latency_ms: 5,
      token_estimate: 100,
      issue_codes: [],
      warning_codes: [],
    },
    {
      agent: "validator-agent",
      status: "passed",
      provider: "azure_foundry_responses",
      model: "remote",
      latency_ms: 1,
      token_estimate: 20,
      issue_codes: [],
      warning_codes: [],
    },
  ],
  provider_model: "Microsoft Foundry (Agent Framework, prompt agents)",
  correlation_id: "corr-fixture-1",
  dealer_group_id: "GROUP-DEMO",
};

export const envelopeErrorFixture: RecommendationEnvelope = {
  status: "provider_content_filter",
  error_code: "AGENT_PROVIDER_CONTENT_FILTER",
  error_message: "Remote agent blocked the request via content safety.",
  recommendation: null,
  agent_trace: [
    {
      agent: "data-analyst-agent",
      status: "provider_content_filter",
      provider: "azure_foundry_responses",
      model: "remote",
      latency_ms: 220,
      token_estimate: null,
      issue_codes: ["AGENT_PROVIDER_CONTENT_FILTER"],
      warning_codes: [],
    },
  ],
  provider_model: "Microsoft Foundry (Agent Framework, prompt agents)",
  correlation_id: "corr-fixture-err-1",
  dealer_group_id: "GROUP-DEMO",
};

export const auditFixture: AuditResponse = {
  events: [],
  total: 0,
  disclaimer: "Synthetic audit rows only.",
};




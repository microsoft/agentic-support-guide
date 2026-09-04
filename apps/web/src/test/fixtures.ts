import type {
  AssessmentsSummary,
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
  auth_mode: "entra",
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
  district_isolation_enabled: true,
  customer_demo_ready: false,
  checks: [
    { name: "backend", label: "Backend service running", ok: true, detail: "ok" },
    {
      name: "foundry_project_endpoint",
      label: "Azure AI Foundry project endpoint configured",
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
    "Azure AI Foundry project endpoint is not configured. Recommendation requests will fail.",
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
  district_isolation_enabled: true,
  customer_demo_ready: true,
  checks: [
    { name: "backend", label: "Backend service running", ok: true, detail: "ok" },
    {
      name: "foundry_project_endpoint",
      label: "Azure AI Foundry project endpoint configured",
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
    { id: "kpi-learners", label: "Active Learners", value: 120, unit: "count", delta: 0, trend: "steady" },
    { id: "kpi-flagged", label: "Flagged for Support", value: 30, unit: "count", delta: 25, trend: "watch" },
    { id: "kpi-proficiency", label: "Avg Proficiency Index", value: 62.5, unit: "index", delta: 1.2, trend: "up" },
    { id: "kpi-attendance", label: "Avg Attendance", value: 91.4, unit: "percent", delta: -0.4, trend: "down" },
  ],
  proficiency_trend: [
    { period: "2026-P01", value: 55.2 },
    { period: "2026-P02", value: 57.1 },
  ],
  domain_distribution: [
    { domain: "early-literacy", value: 60 },
    { domain: "math-foundations", value: 65 },
  ],
  engagement_trend: [
    { period: "2026-P01", value: 65 },
    { period: "2026-P02", value: 68 },
  ],
  notes: ["All values are synthetic and generated locally."],
};

export const assessmentsFixture: AssessmentsSummary = {
  filters_applied: { school: null, grade: null, domain: null, group: null },
  total_records: 3,
  proficiency_distribution: [
    { label: "Emerging", count: 1, percent: 33.3 },
    { label: "Approaching", count: 1, percent: 33.3 },
    { label: "Proficient", count: 1, percent: 33.3 },
    { label: "Advanced", count: 0, percent: 0 },
  ],
  domain_trends: [
    { domain: "early-literacy", points: [{ period: "2026-P01", value: 50 }] },
  ],
  recommendation_bullets: ["Consider targeted small-group instruction."],
  performance_summary: "Illustrative synthetic summary.",
  generated_by: "Generated from local rules over synthetic data.",
  table_rows: [
    {
      record_id: "ASM-00001",
      learner_id: "LRN-0001",
      school_id: "SCH-001",
      grade: 3,
      group: "GRP-A",
      domain: "early-literacy",
      proficiency: "Emerging",
      score: 35,
      period: "2026-P01",
    },
  ],
};

export const supportOptionsFixture: SupportOptions = {
  learners: [
    { id: "LRN-0001", label: "Learner 0001" },
    { id: "LRN-0002", label: "Learner 0002" },
  ],
  categories: [
    { id: "early-literacy", label: "Early Literacy Support", description: "desc" },
    { id: "reading-below-grade", label: "Reading Below Grade Level", description: "desc" },
  ],
  smart_goals: [
    {
      id: "SG-early-literacy-1",
      label: "SMART goal 1",
      category_id: "early-literacy",
      description: "Increase letter-sound correspondence.",
    },
  ],
  strategies: [
    {
      id: "ST-early-literacy-1",
      label: "Strategy 1",
      category_id: "early-literacy",
      description: "Daily 15-minute phonemic awareness routine.",
    },
  ],
};

export const savedPlansFixture: SavedPlansResponse = {
  plans: [],
  total: 0,
};

export const recommendationFixture: Recommendation = {
  district_id: "DIST-DEMO",
  detected_need: "Early literacy skill gap",
  evidence_summary: ["Proficiency index (synthetic): 35.0"],
  rationale: "Rule-based rationale.",
  support_tier: "Intensive support (Tier 3)",
  recommended_frequency: "4-5x weekly",
  grouping_guidance: "1:1 or 1:2",
  resource_matches: [],
  educator_next_steps: ["Confirm baseline."],
  progress_monitoring: ["Weekly probe."],
  review_window_days: 28,
  decision_rule: "IF ...",
  caveats: ["Illustrative only.", "Human review is required."],
  smart_goal_suggestions: ["SG-early-literacy-1"],
  strategy_suggestions: ["ST-early-literacy-1"],
  citations: [
    {
      citation_id: "DIST-DEMO-el-01",
      district_id: "DIST-DEMO",
      source_type: "synthetic_fixture",
      source_title: "Demo district - Early Literacy Fixture",
      section_or_page: "",
      evidence_summary: "Illustrative synthetic reference used only for the customer demo.",
      source_ref: "fixture://dist-demo/el-01",
      retrieved_at: "2026-01-05T09:00:00Z",
      confidence: 0.8,
    },
  ],
  completeness: { ok: true, missing: [] },
  human_review_state: "pending_review",
  generated_by:
    "Generated by three collaborating agents via Azure AI Foundry (Agent Framework, prompt agents).",
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
  provider_model: "Azure AI Foundry (Agent Framework, prompt agents)",
  correlation_id: "corr-fixture-1",
  district_id: "DIST-DEMO",
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
  provider_model: "Azure AI Foundry (Agent Framework, prompt agents)",
  correlation_id: "corr-fixture-err-1",
  district_id: "DIST-DEMO",
};

export const auditFixture: AuditResponse = {
  events: [],
  total: 0,
  disclaimer: "Synthetic audit rows only.",
};




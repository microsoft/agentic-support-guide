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
  version: "0.2.0",
  banner: "Prototype",
  provider_configured: false,
  auth_mode: "entra",
};

export const healthDetailsNotReadyFixture: HealthDetailsResponse = {
  status: "ok",
  service: "agentic-support-guide-api",
  version: "0.2.0",
  active_provider: "unconfigured",
  customer_demo_ready: false,
  checks: [
    { name: "backend", label: "Backend service running", ok: true, detail: "ok" },
    {
      name: "foundry_endpoint",
      label: "Azure AI Foundry endpoint configured",
      ok: false,
      detail: "Not set. Populate AZURE_AI_FOUNDRY_ENDPOINT from Terraform outputs.",
    },
    {
      name: "foundry_deployment",
      label: "Model deployment name",
      ok: false,
      detail: "Not set.",
    },
  ],
  warnings: [
    "Azure AI Foundry environment variables are missing. Recommendation requests will fail.",
  ],
  guidance: "Not demo-ready. Finish Terraform + .env setup.",
};

export const healthDetailsReadyFixture: HealthDetailsResponse = {
  status: "ok",
  service: "agentic-support-guide-api",
  version: "0.2.0",
  active_provider: "azure_foundry",
  customer_demo_ready: true,
  checks: [
    { name: "backend", label: "Backend service running", ok: true, detail: "ok" },
    {
      name: "foundry_endpoint",
      label: "Azure AI Foundry endpoint configured",
      ok: true,
      detail: "Set.",
    },
    {
      name: "foundry_deployment",
      label: "Model deployment name",
      ok: true,
      detail: "Set.",
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
  completeness: { ok: true, missing: [] },
  generated_by: "Generated by three collaborating agents via mock provider (offline mode).",
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
      provider: "mock",
      model: "mock-reasoner-v0",
      latency_ms: 5,
      token_estimate: 100,
      issue_codes: [],
      warning_codes: [],
    },
    {
      agent: "support-recommendation-agent",
      status: "ok",
      provider: "mock",
      model: "mock-reasoner-v0",
      latency_ms: 5,
      token_estimate: 100,
      issue_codes: [],
      warning_codes: [],
    },
    {
      agent: "validator-agent",
      status: "passed",
      provider: "mock",
      model: "mock-reasoner-v0",
      latency_ms: 1,
      token_estimate: 20,
      issue_codes: [],
      warning_codes: [],
    },
  ],
  provider_model: "mock / mock-reasoner-v0",
};

export const envelopeErrorFixture: RecommendationEnvelope = {
  status: "provider_content_filter",
  error_code: "AGENT_PROVIDER_CONTENT_FILTER",
  error_message: "Model provider blocked the request via content safety.",
  recommendation: null,
  agent_trace: [
    {
      agent: "data-analyst-agent",
      status: "provider_content_filter",
      provider: "azure-openai",
      model: "asg-chat",
      latency_ms: 220,
      token_estimate: null,
      issue_codes: ["AGENT_PROVIDER_CONTENT_FILTER"],
      warning_codes: [],
    },
  ],
  provider_model: "azure-openai / asg-chat",
};

export const auditFixture: AuditResponse = {
  events: [],
  total: 0,
  disclaimer: "Synthetic audit rows only.",
};

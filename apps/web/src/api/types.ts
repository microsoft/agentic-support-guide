// Hand-written types mirroring the Pydantic v2 models in /services/api/app/models.py.
// The FastAPI OpenAPI at /openapi.json is the source of truth.

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  banner: string;
  provider_configured: boolean;
  foundry_auth_mode: string;
  build_id: string;
}

export interface HealthCheckItem {
  name: string;
  label: string;
  ok: boolean;
  detail: string;
}

export interface HealthDetailsResponse {
  status: string;
  service: string;
  version: string;
  active_provider: string;
  foundry_project_configured: boolean;
  agent_definitions_valid: boolean;
  model_deployments_configured: boolean;
  service_side_remote_workflow_active: boolean;
  evidence_fixture_available: boolean;
  evidence_source: string;
  evidence_knowledge_base: string;
  evidence_verified: boolean;
  dealer_group_isolation_enabled: boolean;
  api_auth_mode: string;
  customer_demo_ready: boolean;
  checks: HealthCheckItem[];
  warnings: string[];
  guidance: string;
}

export interface DemoResetResponse {
  status: string;
  plans_reset: number;
  audit_reset: number;
}

export interface AgentTraceStep {
  agent: string;
  status: string;
  provider: string;
  model: string;
  latency_ms: number;
  token_estimate: number | null;
  issue_codes?: string[];
  warning_codes?: string[];
  citation_count?: number;
}

export interface KpiCard {
  id: string;
  label: string;
  value: number;
  unit: string;
  delta: number;
  trend: string;
}

export interface TrendPoint {
  period: string;
  value: number;
}

export interface AreaSlice {
  process_area: string;
  value: number;
}

export interface DashboardSummary {
  kpi_cards: KpiCard[];
  process_score_trend: TrendPoint[];
  area_distribution: AreaSlice[];
  engagement_trend: TrendPoint[];
  notes: string[];
}

export interface BandBucket {
  label: string;
  count: number;
  percent: number;
}

export interface AreaTrend {
  process_area: string;
  points: TrendPoint[];
}

export interface ScoresSummary {
  filters_applied: Record<string, string | null>;
  total_records: number;
  band_distribution: BandBucket[];
  area_trends: AreaTrend[];
  recommendation_bullets: string[];
  performance_summary: string;
  generated_by: string;
  table_rows: Array<Record<string, string | number>>;
}

export interface OperationsSummary {
  attendance_trend: TrendPoint[];
  escalation_trend: TrendPoint[];
  engagement_trend: TrendPoint[];
  highlights: string[];
  total_records: number;
}

export interface Option {
  id: string;
  label: string;
}

export interface CategoryOption extends Option {
  description: string;
}

export interface GoalOption extends Option {
  category_id: string;
  description: string;
}

export interface StrategyOption extends Option {
  category_id: string;
  description: string;
}

export interface SupportOptions {
  dealerships: Option[];
  categories: CategoryOption[];
  goals: GoalOption[];
  strategies: StrategyOption[];
  dealer_groups: string[];
}

export interface RecommendationResource {
  id: string;
  label: string;
  kind: string;
}

export interface RecommendationCitation {
  citation_id: string;
  dealer_group_id: string;
  source_type: string;
  source_title: string;
  section_or_page: string;
  evidence_summary: string;
  source_ref: string;
  retrieved_at: string;
  confidence: number;
}

export interface Recommendation {
  dealer_group_id: string;
  detected_need: string;
  evidence_summary: string[];
  rationale: string;
  support_tier: string;
  recommended_frequency: string;
  grouping_guidance: string;
  resource_matches: RecommendationResource[];
  manager_next_steps: string[];
  progress_monitoring: string[];
  review_window_days: number;
  decision_rule: string;
  caveats: string[];
  goal_suggestions: string[];
  strategy_suggestions: string[];
  citations: RecommendationCitation[];
  completeness: { ok: boolean; missing: string[] };
  human_review_state: string;
  generated_by: string;
}

export interface RecommendationEnvelope {
  status: string;
  error_code: string | null;
  error_message: string | null;
  recommendation: Recommendation | null;
  agent_trace?: AgentTraceStep[];
  provider_model: string;
  correlation_id: string;
  dealer_group_id: string;
}

export interface SavedPlan {
  plan_id: string;
  dealership_id: string;
  dealer_group_id: string;
  category: string;
  concern_text: string;
  selected_goal: string | null;
  selected_strategies: string[];
  created_at: string;
  recommendation: Recommendation;
  human_review_state: string;
}

export interface SavedPlansResponse {
  plans: SavedPlan[];
  total: number;
}

export interface AuditEvent {
  event_id: string;
  timestamp: string;
  endpoint: string;
  context: string;
  user: string;
  provider_model: string;
  duration_ms: number;
  token_estimate: number;
  status: string;
  correlation_id?: string;
  dealer_group_id?: string;
  evidence_count?: number;
  citation_count?: number;
  validator_status?: string;
}

export interface AuditResponse {
  events: AuditEvent[];
  total: number;
  disclaimer: string;
}

export interface DealershipSummary {
  dealership_id: string;
  display_label: string;
  region_id: string;
  segment: string;
  process_score: number;
  appointment_attendance_rate: number;
  followup_index: number;
  engagement_index: number;
  flagged: boolean;
}

export interface DealershipsResponse {
  dealerships: DealershipSummary[];
  total: number;
}



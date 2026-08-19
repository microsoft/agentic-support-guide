// Hand-written types mirroring the Pydantic v2 models in /services/api/app/models.py.
// The FastAPI OpenAPI at /openapi.json is the source of truth.

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  banner: string;
  provider_configured: boolean;
  auth_mode: string;
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
  foundry_agents_bound: boolean;
  service_side_remote_workflow_active: boolean;
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

export interface DomainSlice {
  domain: string;
  value: number;
}

export interface DashboardSummary {
  kpi_cards: KpiCard[];
  proficiency_trend: TrendPoint[];
  domain_distribution: DomainSlice[];
  engagement_trend: TrendPoint[];
  notes: string[];
}

export interface ProficiencyBucket {
  label: string;
  count: number;
  percent: number;
}

export interface DomainTrend {
  domain: string;
  points: TrendPoint[];
}

export interface AssessmentsSummary {
  filters_applied: Record<string, string | null>;
  total_records: number;
  proficiency_distribution: ProficiencyBucket[];
  domain_trends: DomainTrend[];
  recommendation_bullets: string[];
  performance_summary: string;
  generated_by: string;
  table_rows: Array<Record<string, string | number>>;
}

export interface BehaviorSummary {
  attendance_trend: TrendPoint[];
  behavior_trend: TrendPoint[];
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

export interface SmartGoalOption extends Option {
  category_id: string;
  description: string;
}

export interface StrategyOption extends Option {
  category_id: string;
  description: string;
}

export interface SupportOptions {
  learners: Option[];
  categories: CategoryOption[];
  smart_goals: SmartGoalOption[];
  strategies: StrategyOption[];
}

export interface RecommendationResource {
  id: string;
  label: string;
  kind: string;
}

export interface Recommendation {
  detected_need: string;
  evidence_summary: string[];
  rationale: string;
  support_tier: string;
  recommended_frequency: string;
  grouping_guidance: string;
  resource_matches: RecommendationResource[];
  educator_next_steps: string[];
  progress_monitoring: string[];
  review_window_days: number;
  decision_rule: string;
  caveats: string[];
  smart_goal_suggestions: string[];
  strategy_suggestions: string[];
  completeness: { ok: boolean; missing: string[] };
  generated_by: string;
}

export interface RecommendationEnvelope {
  status: string;
  error_code: string | null;
  error_message: string | null;
  recommendation: Recommendation | null;
  agent_trace?: AgentTraceStep[];
  provider_model: string;
}

export interface SavedPlan {
  plan_id: string;
  learner_id: string;
  category: string;
  concern_text: string;
  selected_smart_goal: string | null;
  selected_strategies: string[];
  created_at: string;
  recommendation: Recommendation;
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
}

export interface AuditResponse {
  events: AuditEvent[];
  total: number;
  disclaimer: string;
}

export interface LearnerSummary {
  learner_id: string;
  display_label: string;
  school_id: string;
  grade: number;
  group: string;
  proficiency_index: number;
  attendance_rate: number;
  behavior_index: number;
  engagement_index: number;
  flagged: boolean;
}

export interface LearnersResponse {
  learners: LearnerSummary[];
  total: number;
}

import type {
  AssessmentsSummary,
  AuditResponse,
  BehaviorSummary,
  DashboardSummary,
  DemoResetResponse,
  HealthDetailsResponse,
  HealthResponse,
  LearnersResponse,
  RecommendationEnvelope,
  SavedPlan,
  SavedPlansResponse,
  SupportOptions,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { "content-type": "application/json" },
      ...init,
    });
  } catch (err) {
    throw new ApiError(0, `Network error: ${(err as Error).message}`);
  }
  if (!response.ok) {
    throw new ApiError(response.status, `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  dashboardSummary: () => request<DashboardSummary>("/dashboard/summary"),
  learners: () => request<LearnersResponse>("/learners"),
  assessmentsSummary: (filters: {
    school?: string;
    grade?: string;
    domain?: string;
    group?: string;
  }) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value) params.set(key, value);
    }
    const qs = params.toString();
    return request<AssessmentsSummary>(`/assessments/summary${qs ? `?${qs}` : ""}`);
  },
  behaviorSummary: () => request<BehaviorSummary>("/behavior/summary"),
  supportOptions: () => request<SupportOptions>("/supports/options"),
  recommendation: (body: { learner_id: string; category: string; concern_text: string }) =>
    request<RecommendationEnvelope>("/recommendations/support-plan", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  savedPlans: () => request<SavedPlansResponse>("/supports/plans"),
  savePlan: (body: {
    learner_id: string;
    category: string;
    concern_text: string;
    selected_smart_goal: string | null;
    selected_strategies: string[];
    recommendation: import("./types").Recommendation;
  }) =>
    request<SavedPlan>("/supports/plans", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  audit: () => request<AuditResponse>("/audit/events"),
  healthDetails: () => request<HealthDetailsResponse>("/health/details"),
  demoReset: () =>
    request<DemoResetResponse>("/demo/reset", { method: "POST" }),
};

import type {
  ScoresSummary,
  AuditResponse,
  OperationsSummary,
  DashboardSummary,
  DemoResetResponse,
  HealthDetailsResponse,
  HealthResponse,
  DealershipsResponse,
  RecommendationEnvelope,
  SavedPlan,
  SavedPlansResponse,
  SupportOptions,
} from "./types";

// Same origin: the web tier serves this bundle and proxies /api to the API,
// attaching the shared key server-side. The browser holds no credential,
// because a bundle cannot keep one.
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

// A bare "Request failed: 503" reads as an outage. The key cases a user can
// act on are the ones where the deployment is misconfigured.
function describeStatus(status: number): string {
  if (status === 401) return "The web tier is not authorized to call the API.";
  if (status === 503) return "The API has no key configured and is refusing requests.";
  return `Request failed: ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = { "content-type": "application/json" };
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
    });
  } catch (err) {
    throw new ApiError(0, `Network error: ${(err as Error).message}`);
  }
  if (!response.ok) {
    // The API returns a typed error body. Prefer it: a generic status string
    // cannot tell provider throttling from a guardrail refusal.
    throw new ApiError(response.status, await describeFailure(response));
  }
  return (await response.json()) as T;
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      detail?: unknown;
      error_message?: string;
      error_code?: string;
    };
    const detail = typeof body.detail === "string" ? body.detail : undefined;
    const message = body.error_message ?? detail;
    if (message) {
      return body.error_code ? `${message} (${body.error_code})` : message;
    }
  } catch {
    // Not JSON, or already consumed. Fall through to the status text.
  }
  return describeStatus(response.status);
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  dashboardSummary: () => request<DashboardSummary>("/dashboard/summary"),
  dealerships: () => request<DealershipsResponse>("/dealerships"),
  scoresSummary: (filters: {
    region?: string;
    process_area?: string;
    segment?: string;
  }) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value) params.set(key, value);
    }
    const qs = params.toString();
    return request<ScoresSummary>(`/scores/summary${qs ? `?${qs}` : ""}`);
  },
  operationsSummary: () => request<OperationsSummary>("/operations/summary"),
  supportOptions: () => request<SupportOptions>("/supports/options"),
  recommendation: (body: {
    dealership_id: string;
    category: string;
    concern_text: string;
    dealer_group_id: string;
  }) =>
    request<RecommendationEnvelope>("/recommendations/support-plan", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  savedPlans: () => request<SavedPlansResponse>("/supports/plans"),
  savePlan: (body: {
    dealership_id: string;
    category: string;
    concern_text: string;
    selected_goal: string | null;
    selected_strategies: string[];
    recommendation: import("./types").Recommendation;
    dealer_group_id: string;
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

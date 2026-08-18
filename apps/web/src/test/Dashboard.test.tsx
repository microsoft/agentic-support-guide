import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DashboardPage } from "../pages/DashboardPage";
import { api } from "../api/client";
import { dashboardFixture } from "./fixtures";

describe("DashboardPage", () => {
  it("renders four KPI cards from the summary payload", async () => {
    vi.spyOn(api, "dashboardSummary").mockResolvedValue(dashboardFixture);

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("kpi-kpi-learners")).toBeInTheDocument();
    });
    expect(screen.getByTestId("kpi-kpi-flagged")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-kpi-proficiency")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-kpi-attendance")).toBeInTheDocument();
  });

  it("shows API unavailable banner on error", async () => {
    vi.spyOn(api, "dashboardSummary").mockRejectedValue(new Error("boom"));

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(/API unavailable - start the local backend\./i),
    ).toBeInTheDocument();
  });
});

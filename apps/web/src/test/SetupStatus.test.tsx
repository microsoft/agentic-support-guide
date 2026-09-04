import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SetupStatus } from "../components/SetupStatus";
import { api } from "../api/client";
import { healthDetailsNotReadyFixture, healthDetailsReadyFixture } from "./fixtures";

describe("SetupStatus", () => {
  it("renders customer-demo-ready messaging when Azure Foundry is configured", async () => {
    vi.spyOn(api, "healthDetails").mockResolvedValue(healthDetailsReadyFixture);
    render(<SetupStatus />);

    await waitFor(() =>
      expect(screen.getByTestId("setup-banner")).toHaveTextContent(
        /customer demo ready/i,
      ),
    );
    expect(screen.getByText(/azure_foundry_responses/i)).toBeInTheDocument();
  });

  it("warns that the customer demo is not ready when the backend reports missing config", async () => {
    vi.spyOn(api, "healthDetails").mockResolvedValue(healthDetailsNotReadyFixture);
    render(<SetupStatus />);

    await waitFor(() =>
      expect(screen.getByTestId("setup-banner")).toHaveTextContent(
        /customer demo not ready/i,
      ),
    );
    expect(
      screen.getByText(/azure ai foundry project endpoint is not configured/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId("setup-check-foundry_project_endpoint")).toBeInTheDocument();
    expect(screen.getByTestId("setup-check-agent_definitions_valid")).toBeInTheDocument();
  });

  it("shows the API unavailable state on network failure", async () => {
    vi.spyOn(api, "healthDetails").mockRejectedValue(new Error("boom"));
    render(<SetupStatus />);

    expect(
      await screen.findByText(/api unavailable - start the local backend/i),
    ).toBeInTheDocument();
  });
});


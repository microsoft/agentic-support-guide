import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { SupportsPage } from "../pages/SupportsPage";
import { api } from "../api/client";
import {
  envelopeErrorFixture,
  envelopeOkFixture,
  healthDetailsReadyFixture,
  healthFixture,
  savedPlansFixture,
  supportOptionsFixture,
} from "./fixtures";

function renderWithDistricts(districts: string[], children: ReactNode) {
  vi.spyOn(api, "supportOptions").mockResolvedValue({
    ...supportOptionsFixture,
    districts,
  });
  return render(<MemoryRouter>{children}</MemoryRouter>);
}

describe("SupportsPage", () => {
  it("advances through the guided plan builder and shows the agent workflow panel", async () => {
    vi.spyOn(api, "health").mockResolvedValue(healthFixture);
    vi.spyOn(api, "healthDetails").mockResolvedValue(healthDetailsReadyFixture);
    vi.spyOn(api, "supportOptions").mockResolvedValue(supportOptionsFixture);
    vi.spyOn(api, "savedPlans").mockResolvedValue(savedPlansFixture);
    vi.spyOn(api, "recommendation").mockResolvedValue(envelopeOkFixture);

    renderWithDistricts(["DIST-A"], <SupportsPage />);

    await waitFor(() => expect(screen.getByLabelText(/learner/i)).toBeInTheDocument());
    expect(screen.getByTestId("agent-workflow")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/learner/i), "LRN-0001");
    await userEvent.selectOptions(screen.getByLabelText(/category/i), "early-literacy");
    await userEvent.type(
      screen.getByLabelText(/concern text/i),
      "Letter-sound fluency behind pace.",
    );

    await userEvent.click(screen.getByRole("button", { name: /generate recommendation/i }));

    await waitFor(() =>
      expect(screen.getByTestId("completeness")).toHaveTextContent(/complete/i),
    );
    expect(screen.getByText(/Intensive support/i)).toBeInTheDocument();
    // Three agent rows visible.
    expect(screen.getByTestId("agent-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("agent-step-2")).toBeInTheDocument();
    expect(screen.getByTestId("agent-step-3")).toBeInTheDocument();
  });

  it("shows a provider-error state when the recommendation envelope reports a failure", async () => {
    vi.spyOn(api, "health").mockResolvedValue(healthFixture);
    vi.spyOn(api, "healthDetails").mockResolvedValue(healthDetailsReadyFixture);
    vi.spyOn(api, "supportOptions").mockResolvedValue(supportOptionsFixture);
    vi.spyOn(api, "savedPlans").mockResolvedValue(savedPlansFixture);
    vi.spyOn(api, "recommendation").mockResolvedValue(envelopeErrorFixture);

    renderWithDistricts(["DIST-A"], <SupportsPage />);

    await waitFor(() => expect(screen.getByLabelText(/learner/i)).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText(/learner/i), "LRN-0001");
    await userEvent.selectOptions(screen.getByLabelText(/category/i), "early-literacy");
    await userEvent.type(
      screen.getByLabelText(/concern text/i),
      "Letter-sound fluency behind pace.",
    );
    await userEvent.click(screen.getByRole("button", { name: /generate recommendation/i }));

    const alert = await screen.findByTestId("recommendation-error");
    expect(alert).toHaveTextContent(/blocked by content-safety/i);
    expect(screen.queryByTestId("completeness")).not.toBeInTheDocument();
  });

  it("sends the district the API offered rather than a hardcoded one", async () => {
    vi.spyOn(api, "health").mockResolvedValue(healthFixture);
    vi.spyOn(api, "healthDetails").mockResolvedValue(healthDetailsReadyFixture);
    vi.spyOn(api, "supportOptions").mockResolvedValue(supportOptionsFixture);
    vi.spyOn(api, "savedPlans").mockResolvedValue(savedPlansFixture);
    const recommendation = vi
      .spyOn(api, "recommendation")
      .mockResolvedValue(envelopeOkFixture);

    renderWithDistricts(["DIST-B"], <SupportsPage />);

    await waitFor(() => expect(screen.getByLabelText(/learner/i)).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText(/learner/i), "LRN-0001");
    await userEvent.selectOptions(screen.getByLabelText(/category/i), "early-literacy");
    await userEvent.type(
      screen.getByLabelText(/concern text/i),
      "Letter-sound fluency behind pace.",
    );
    await userEvent.click(screen.getByRole("button", { name: /generate recommendation/i }));

    await waitFor(() => expect(recommendation).toHaveBeenCalled());
    expect(recommendation.mock.calls[0][0]).toMatchObject({ district_id: "DIST-B" });
  });
});

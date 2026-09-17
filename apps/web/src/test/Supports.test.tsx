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

function renderWithDealerGroups(dealer_groups: string[], children: ReactNode) {
  vi.spyOn(api, "supportOptions").mockResolvedValue({
    ...supportOptionsFixture,
    dealer_groups,
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

    renderWithDealerGroups(["GROUP-A"], <SupportsPage />);

    await waitFor(() => expect(screen.getByLabelText(/dealership/i)).toBeInTheDocument());
    expect(screen.getByTestId("agent-workflow")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/dealership/i), "DLR-0001");
    await userEvent.selectOptions(screen.getByLabelText(/category/i), "lead-response");
    await userEvent.type(
      screen.getByLabelText(/concern text/i),
      "First response to online enquiries behind target.",
    );

    await userEvent.click(screen.getByRole("button", { name: /generate recommendation/i }));

    await waitFor(() =>
      expect(screen.getByTestId("completeness")).toHaveTextContent(/complete/i),
    );
    expect(screen.getByText(/Intensive/i)).toBeInTheDocument();
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

    renderWithDealerGroups(["GROUP-A"], <SupportsPage />);

    await waitFor(() => expect(screen.getByLabelText(/dealership/i)).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText(/dealership/i), "DLR-0001");
    await userEvent.selectOptions(screen.getByLabelText(/category/i), "lead-response");
    await userEvent.type(
      screen.getByLabelText(/concern text/i),
      "First response to online enquiries behind target.",
    );
    await userEvent.click(screen.getByRole("button", { name: /generate recommendation/i }));

    const alert = await screen.findByTestId("recommendation-error");
    expect(alert).toHaveTextContent(/blocked by content-safety/i);
    expect(screen.queryByTestId("completeness")).not.toBeInTheDocument();
  });

  it("sends the dealer group the API offered rather than a hardcoded one", async () => {
    vi.spyOn(api, "health").mockResolvedValue(healthFixture);
    vi.spyOn(api, "healthDetails").mockResolvedValue(healthDetailsReadyFixture);
    vi.spyOn(api, "supportOptions").mockResolvedValue(supportOptionsFixture);
    vi.spyOn(api, "savedPlans").mockResolvedValue(savedPlansFixture);
    const recommendation = vi
      .spyOn(api, "recommendation")
      .mockResolvedValue(envelopeOkFixture);

    renderWithDealerGroups(["GROUP-B"], <SupportsPage />);

    await waitFor(() => expect(screen.getByLabelText(/dealership/i)).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText(/dealership/i), "DLR-0001");
    await userEvent.selectOptions(screen.getByLabelText(/category/i), "lead-response");
    await userEvent.type(
      screen.getByLabelText(/concern text/i),
      "First response to online enquiries behind target.",
    );
    await userEvent.click(screen.getByRole("button", { name: /generate recommendation/i }));

    await waitFor(() => expect(recommendation).toHaveBeenCalled());
    expect(recommendation.mock.calls[0][0]).toMatchObject({ dealer_group_id: "GROUP-B" });
  });
});

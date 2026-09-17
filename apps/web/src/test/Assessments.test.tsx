import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AssessmentsPage } from "../pages/AssessmentsPage";
import { api } from "../api/client";
import { assessmentsFixture } from "./fixtures";

describe("AssessmentsPage", () => {
  it("refetches when a filter changes", async () => {
    const spy = vi.spyOn(api, "scoresSummary").mockResolvedValue(assessmentsFixture);

    render(
      <MemoryRouter>
        <AssessmentsPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy).toHaveBeenLastCalledWith({
      region: undefined,
      process_area: undefined,
      segment: undefined,
    });

    await userEvent.selectOptions(screen.getByLabelText(/region/i), "REG-002");

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy).toHaveBeenLastCalledWith({
      region: "REG-002",
      process_area: undefined,
      segment: undefined,
    });
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuditPage } from "../pages/AuditPage";
import { api } from "../api/client";

describe("API unavailable states", () => {
  it("shows the shared unavailable banner when the audit request fails", async () => {
    vi.spyOn(api, "audit").mockRejectedValue(new Error("boom"));

    render(
      <MemoryRouter>
        <AuditPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(/API unavailable - start the local backend\./i),
    ).toBeInTheDocument();
  });
});

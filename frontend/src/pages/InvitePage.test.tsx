import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { InvitePage } from "./InvitePage";

const establishSession = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ establishSession }) }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

describe("InvitePage link registration", () => {
  beforeEach(() => {
    sessionStorage.clear();
    establishSession.mockReset();
    vi.mocked(apiRequest).mockReset().mockImplementation(async (path, init) => {
      if (path === "/auth/invitations/exchange" && init?.method === "POST") return {
        label: "Family invite",
        expires_at: "2026-08-24T06:00:00Z",
        google_enabled: true,
        challenge_token: "challenge-abcdefghijklmnopqrstuvwxyz",
      };
      if (path === "/auth/invitations/accept" && init?.method === "POST") return {
        user: { id: 2, username: "family", email: "family@example.com", is_admin: false, email_verified: false, settings: { currency: "USD", timezone: "UTC", theme: "system", annual_gross_income: null, pay_frequency: null, advisor_enabled: true, advisor_share_merchants: false, advisor_share_planning_names: false, advisor_include_descriptions: false, advisor_store_history: true, onboarding_complete: false, onboarding_step: 0 } },
        csrf_token: "csrf-test",
      };
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("exchanges the raw link token and creates an account with the short-lived challenge", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/join/raw-invite-token-abcdefghijklmnopqrstuvwxyz"]}><Routes><Route path="/join/:token" element={<InvitePage />} /><Route path="/onboarding" element={<h1>First-time setup</h1>} /></Routes></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Welcome to Budget" })).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith("/auth/invitations/exchange", expect.objectContaining({ method: "POST" })));
    expect(await screen.findByText("Family invite")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Email"), "family@example.com");
    await user.type(screen.getByLabelText("Username"), "family");
    await user.type(screen.getByLabelText("Password", { exact: true }), "Family Password 123!");
    await user.type(screen.getByLabelText("Confirm password"), "Family Password 123!");
    await user.click(screen.getByRole("button", { name: "Create Budget account" }));

    await waitFor(() => expect(establishSession).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "First-time setup" })).toBeInTheDocument();
    expect(vi.mocked(apiRequest)).toHaveBeenCalledWith("/auth/invitations/accept", expect.objectContaining({
      body: expect.stringContaining('"challenge_token":"challenge-abcdefghijklmnopqrstuvwxyz"'),
    }));
  });
});

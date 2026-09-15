import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { SignupPage } from "./SignupPage";

const establishSession = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ establishSession }) }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

describe("SignupPage", () => {
  beforeEach(() => {
    establishSession.mockReset();
    vi.mocked(apiRequest).mockReset().mockResolvedValue({
      user: { id: 2, username: "new-owner", email: "new@example.com", is_admin: false, email_verified: false, settings: { currency: "USD", timezone: "UTC", theme: "system", annual_gross_income: null, pay_frequency: null, advisor_enabled: true, advisor_share_merchants: false, advisor_share_planning_names: false, advisor_include_descriptions: false, advisor_store_history: true, onboarding_complete: false, onboarding_step: 0 } },
      csrf_token: "csrf-test",
    } as never);
  });

  it("validates matching passwords before submitting", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><SignupPage googleEnabled={false} /></MemoryRouter>);
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Username"), "new-owner");
    await user.type(screen.getByLabelText("Password", { exact: true }), "A Long New Password 123!");
    await user.type(screen.getByLabelText("Confirm password"), "Different Password 123!");
    await user.click(screen.getByRole("button", { name: "Create Budget account" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Passwords do not match.");
    expect(apiRequest).not.toHaveBeenCalled();
  });

  it("creates an account and starts onboarding", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/signup"]}><Routes><Route path="/signup" element={<SignupPage googleEnabled={false} />} /><Route path="/onboarding" element={<h1>First-time setup</h1>} /></Routes></MemoryRouter>);
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Username"), "new-owner");
    await user.type(screen.getByLabelText("Password", { exact: true }), "A Long New Password 123!");
    await user.type(screen.getByLabelText("Confirm password"), "A Long New Password 123!");
    await user.click(screen.getByRole("button", { name: "Create Budget account" }));
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/auth/register", expect.objectContaining({ method: "POST" })));
    expect(establishSession).toHaveBeenCalledOnce();
    expect(await screen.findByRole("heading", { name: "First-time setup" })).toBeInTheDocument();
  });
});

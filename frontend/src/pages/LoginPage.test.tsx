import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import axe from "axe-core";
import { LoginPage } from "./LoginPage";

const login = vi.fn();
const demoLogin = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ login, demoLogin }) }));

const status = { initialized: true, demo_mode: true, bootstrap_required: false };

describe("LoginPage", () => {
  beforeEach(() => {
    login.mockReset().mockResolvedValue(undefined);
    demoLogin.mockReset().mockResolvedValue(undefined);
  });

  it("supports one-click demo login only when demo mode is enabled", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/login"]}><Routes><Route path="/login" element={<LoginPage setupStatus={status} />} /><Route path="/dashboard" element={<h1>Demo dashboard</h1>} /></Routes></MemoryRouter>);
    await user.click(screen.getByRole("button", { name: "Explore the demo" }));
    expect(demoLogin).toHaveBeenCalledOnce();
    expect(await screen.findByRole("heading", { name: "Demo dashboard" })).toBeInTheDocument();
  });

  it("submits identity and password and clears the password", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><LoginPage setupStatus={{ ...status, demo_mode: false }} /></MemoryRouter>);
    await user.type(screen.getByLabelText("Username or email"), "owner@example.test");
    const password = screen.getByLabelText("Password");
    await user.type(password, "legacy8");
    await user.click(screen.getByRole("button", { name: /Sign in/ }));
    expect(login).toHaveBeenCalledWith("owner@example.test", "legacy8");
    expect(password).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Explore the demo" })).not.toBeInTheDocument();
  });

  it("has no serious automated accessibility violations", async () => {
    const { container } = render(<MemoryRouter><LoginPage setupStatus={status} /></MemoryRouter>);
    const result = await axe.run(container);
    expect(result.violations.filter((violation) => ["critical", "serious"].includes(violation.impact ?? ""))).toEqual([]);
  });
});

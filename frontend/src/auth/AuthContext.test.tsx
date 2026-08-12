import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../theme/ThemeContext";
import { AuthProvider, useAuth } from "./AuthContext";

const session = {
  user: {
    id: 1,
    username: "owner",
    email: "owner@example.test",
    settings: { currency: "USD", timezone: "UTC", theme: "system", annual_gross_income: null, pay_frequency: null },
  },
  csrf_token: "csrf-value",
};

function AuthProbe() {
  const { status, logout, refresh } = useAuth();
  return <><output>{status}</output><button onClick={() => void logout().catch(() => undefined)}>Log out test</button><button onClick={() => void refresh()}>Retry session</button></>;
}

describe("AuthProvider private cache isolation", () => {
  it("removes authenticated queries when accepting a session and on logout", async () => {
    const client = new QueryClient();
    client.setQueryData(["dashboard", "2026-08"], { private: "previous-user" });
    client.setQueryData(["setup-status"], { initialized: true });
    const previousMutation = client.getMutationCache().build(client, {
      mutationFn: async (value: { annual_gross_income: string }) => value,
    });
    await previousMutation.execute({ annual_gross_income: "97500.0000" });
    expect(client.getMutationCache().getAll()).toHaveLength(1);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") return new Response(null, { status: 204 });
      return new Response(JSON.stringify(session), { status: 200, headers: { "content-type": "application/json" } });
    });

    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><ThemeProvider><AuthProvider><AuthProbe /></AuthProvider></ThemeProvider></QueryClientProvider>);
    await screen.findByText("authenticated");
    expect(client.getQueryData(["dashboard", "2026-08"])).toBeUndefined();
    expect(client.getQueryData(["setup-status"])).toEqual({ initialized: true });
    expect(client.getMutationCache().getAll()).toHaveLength(0);

    client.setQueryData(["accounts"], { private: "current-user" });
    const currentMutation = client.getMutationCache().build(client, {
      mutationFn: async (value: { category_keys: string[] }) => value,
    });
    await currentMutation.execute({ category_keys: ["groceries", "other"] });
    await user.click(screen.getByRole("button", { name: "Log out test" }));
    await waitFor(() => expect(screen.getByText("anonymous")).toBeInTheDocument());
    expect(client.getQueryData(["accounts"])).toBeUndefined();
    expect(client.getQueryData(["setup-status"])).toEqual({ initialized: true });
    expect(client.getMutationCache().getAll()).toHaveLength(0);
  });

  it("keeps the user authenticated when server-side logout cannot be confirmed", async () => {
    const client = new QueryClient();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") return new Response(JSON.stringify({ error: { message: "Logout unavailable" } }), { status: 503, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify(session), { status: 200, headers: { "content-type": "application/json" } });
    });
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><ThemeProvider><AuthProvider><AuthProbe /></AuthProvider></ThemeProvider></QueryClientProvider>);
    await screen.findByText("authenticated");
    client.setQueryData(["accounts"], { private: "still-active-session" });
    await user.click(screen.getByRole("button", { name: "Log out test" }));
    await waitFor(() => expect(screen.getByText("authenticated")).toBeInTheDocument());
    expect(client.getQueryData(["accounts"])).toEqual({ private: "still-active-session" });
  });

  it("does not misclassify a transient session-check failure as signed out", async () => {
    const client = new QueryClient();
    client.setQueryData(["dashboard", "2026-08"], { private: "hidden-until-verified" });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: "Temporary outage" } }), { status: 503, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(session), { status: 200, headers: { "content-type": "application/json" } }));
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><ThemeProvider><AuthProvider><AuthProbe /></AuthProvider></ThemeProvider></QueryClientProvider>);
    expect(await screen.findByText("unavailable")).toBeInTheDocument();
    expect(client.getQueryData(["dashboard", "2026-08"])).toEqual({ private: "hidden-until-verified" });
    await user.click(screen.getByRole("button", { name: "Retry session" }));
    expect(await screen.findByText("authenticated")).toBeInTheDocument();
    expect(client.getQueryData(["dashboard", "2026-08"])).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

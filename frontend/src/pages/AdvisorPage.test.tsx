import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiEventStream, apiRequest } from "../api/client";
import type { InsightItem } from "../api/types";
import { AdvisorPage } from "./AdvisorPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, apiRequest: vi.fn(), apiEventStream: vi.fn() };
});

const status = { available: true, enabled: true, store_history: true, provider: "openai", model: "gpt-5.6" };

function renderAdvisor(entry: string | { pathname: string; state?: unknown } = "/advisor") {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[entry]}><AdvisorPage /></MemoryRouter></QueryClientProvider>);
}

describe("AdvisorPage", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockImplementation(async (path, init) => {
      if (path === "/advisor/status") return status as never;
      if (path === "/advisor/conversations" && !init?.method) return { conversations: [] } as never;
      if (path === "/advisor/conversations" && init?.method === "POST") return { id: 7, title: "New conversation", created_at: "2026-08-13T12:00:00Z", updated_at: "2026-08-13T12:00:00Z" } as never;
      if (path === "/advisor/conversations/7") return { conversation: { id: 7, title: "New conversation", created_at: "2026-08-13T12:00:00Z", updated_at: "2026-08-13T12:00:00Z" }, messages: [] } as never;
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.mocked(apiEventStream).mockReset().mockImplementation(async (_path, _init, onEvent) => {
      onEvent({ event: "meta", data: { mode: "scenario", facts: [{ label: "Safe to spend", value: "USD 1200.0000", detail: "Calculated by Budget" }] } });
      onEvent({ event: "delta", data: { text: "Yes, " } });
      onEvent({ event: "delta", data: { text: "it fits." } });
      onEvent({ event: "done", data: { mode: "scenario", headline: "It fits your current plan", answer: "Yes, it fits.", confidence: "high", warnings: [], suggested_questions: ["What if it costs more?"], facts: [{ label: "Safe to spend", value: "USD 1200.0000", detail: "Calculated by Budget" }] } });
    });
  });

  it("streams an answer and renders deterministic fact cards", async () => {
    const user = userEvent.setup();
    renderAdvisor();
    const box = await screen.findByRole("textbox", { name: "Ask Budget" });
    await user.type(box, "Can I afford $100?");
    await user.click(screen.getByRole("button", { name: "Ask Budget" }));
    expect(await screen.findByRole("heading", { name: "It fits your current plan" })).toBeInTheDocument();
    expect(screen.getByText("USD 1200.0000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What if it costs more?" })).toBeInTheDocument();
  });


  it("formats escaped newlines and bold emphasis in advisor answers", async () => {
    vi.mocked(apiEventStream).mockImplementation(async (_path, _init, onEvent) => {
      onEvent({ event: "meta", data: { mode: "analysis", facts: [] } });
      onEvent({ event: "done", data: { mode: "analysis", headline: "Spending summary", answer: "First line\\n\\n**Housing:** USD 8700", confidence: "medium", warnings: [], suggested_questions: [], facts: [] } });
    });
    const user = userEvent.setup();
    renderAdvisor();
    await user.type(await screen.findByRole("textbox", { name: "Ask Budget" }), "Show me spending");
    await user.click(screen.getByRole("button", { name: "Ask Budget" }));
    expect(await screen.findByText("First line")).toBeInTheDocument();
    expect(screen.getByText("Housing:", { selector: "strong" })).toBeInTheDocument();
    expect(screen.queryByText(/\\n/)).not.toBeInTheDocument();
  });


  it("renders a deterministic action preview and applies it only after approval", async () => {
    const proposal = {
      id: 22,
      conversation_id: 7,
      status: "draft",
      title: "Free up monthly cash",
      summary: "Trim one category and increase savings.",
      currency: "USD",
      preview: { impacts: [{ label: "Safe to spend", before: "USD 1000.0000", after: "USD 1150.0000" }] },
      actions: [{ id: 1, action_type: "goal_monthly_contribution_set", label: "Set Emergency Fund monthly contribution", rationale: "Save faster.", before: { amount: "200.0000" }, after: { amount: "350.0000" } }],
      created_at: "2026-08-14T12:00:00Z",
      expires_at: "2026-08-15T12:00:00Z",
      applied_at: null,
      rejected_at: null,
      undone_at: null,
    };
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(apiRequest).mockImplementation(async (path, init) => {
      if (path === "/advisor/status") return status as never;
      if (path === "/advisor/conversations" && !init?.method) return { conversations: [] } as never;
      if (path === "/advisor/conversations" && init?.method === "POST") return { id: 7, title: "New conversation", created_at: "2026-08-13T12:00:00Z", updated_at: "2026-08-13T12:00:00Z" } as never;
      if (path === "/advisor/conversations/7") return { conversation: { id: 7, title: "New conversation", created_at: "2026-08-13T12:00:00Z", updated_at: "2026-08-13T12:00:00Z" }, messages: [] } as never;
      if (path === "/advisor/proposals/22" && !init?.method) return proposal as never;
      if (path === "/advisor/proposals/22/apply" && init?.method === "POST") return { ...proposal, status: "applied", applied_at: "2026-08-14T12:05:00Z" } as never;
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.mocked(apiEventStream).mockImplementation(async (_path, _init, onEvent) => {
      onEvent({ event: "meta", data: { mode: "analysis", facts: [] } });
      onEvent({ event: "done", data: { mode: "analysis", headline: "Here is a plan", answer: "Review it before applying.", confidence: "high", warnings: [], suggested_questions: [], facts: [], proposal_id: 22 } });
    });
    const user = userEvent.setup();
    renderAdvisor();
    await user.type(await screen.findByRole("textbox", { name: "Ask Budget" }), "Build me a plan");
    await user.click(screen.getByRole("button", { name: "Ask Budget" }));
    expect(await screen.findByRole("heading", { name: "Free up monthly cash" })).toBeInTheDocument();
    expect(screen.getByText("USD 1000.0000")).toBeInTheDocument();
    expect(screen.getByText("USD 1150.0000")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Apply changes" }));
    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledWith("/advisor/proposals/22/apply", expect.objectContaining({ method: "POST" })));
    expect(await screen.findByRole("button", { name: "Undo plan" })).toBeInTheDocument();
  });

  it("keeps a private answer on screen without loading conversation history", async () => {
    vi.mocked(apiRequest).mockImplementation(async (path, init) => {
      if (path === "/advisor/status") return { ...status, store_history: false } as never;
      if (path === "/advisor/conversations" && init?.method === "POST") return { id: 9, title: "New conversation", created_at: "2026-08-13T12:00:00Z", updated_at: "2026-08-13T12:00:00Z" } as never;
      throw new Error(`Unexpected request: ${path}`);
    });
    const user = userEvent.setup();
    renderAdvisor();
    await screen.findByRole("heading", { name: "Private session" });
    await user.type(screen.getByRole("textbox", { name: "Ask Budget" }), "What should I do?");
    await user.click(screen.getByRole("button", { name: "Ask Budget" }));
    expect(await screen.findByText("Yes, it fits.")).toBeInTheDocument();
    expect(vi.mocked(apiRequest)).not.toHaveBeenCalledWith("/advisor/conversations", expect.objectContaining({ method: undefined }));
  });

  it("sends an attached insight only with the next prompt", async () => {
    const insight: InsightItem = { id: 44, signal_type: "forecast_below_reserve", category: "forecast", priority: "important", score: 80, status: "active", title: "Forecast is tight", summary: "Your forecast dips below reserve.", recommendation: "Review spending.", evidence: [], action_route: "/plan", first_seen_at: "2026-08-13T12:00:00Z", last_seen_at: "2026-08-13T12:00:00Z", dismissed_at: null, resolved_at: null };
    const user = userEvent.setup();
    renderAdvisor({ pathname: "/advisor", state: { insight } });
    expect(await screen.findByText("Forecast is tight")).toBeInTheDocument();
    const box = screen.getByRole("textbox", { name: "Ask Budget" });
    expect((box as HTMLTextAreaElement).value).toContain("Explain this insight");
    await user.click(screen.getByRole("button", { name: "Ask Budget" }));
    await waitFor(() => expect(vi.mocked(apiEventStream)).toHaveBeenCalled());
    expect(JSON.parse(String(vi.mocked(apiEventStream).mock.calls[0][1].body)).insight_id).toBe(44);
    expect(screen.queryByText("Attached insight")).not.toBeInTheDocument();
  });
  it("prefills a build-plan prompt from an insight action", async () => {
    const insight: InsightItem = { id: 45, signal_type: "forecast_below_reserve", category: "forecast", priority: "important", score: 80, status: "active", title: "Forecast is tight", summary: "Your forecast dips below reserve.", recommendation: "Review spending.", evidence: [], action_route: "/plan", first_seen_at: "2026-08-13T12:00:00Z", last_seen_at: "2026-08-13T12:00:00Z", dismissed_at: null, resolved_at: null };
    renderAdvisor({ pathname: "/advisor", state: { insight, intent: "plan" } });
    const box = await screen.findByRole("textbox", { name: "Ask Budget" });
    expect((box as HTMLTextAreaElement).value).toContain("Build a practical action plan");
  });

});

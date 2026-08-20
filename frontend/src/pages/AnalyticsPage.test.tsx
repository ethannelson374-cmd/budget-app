import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AnalyticsPage } from "./AnalyticsPage";

vi.mock("./InsightsPage", () => ({ InsightsPage: () => <div>Insights workspace</div> }));
vi.mock("./TrendsPage", () => ({ TrendsPage: () => <div>Trends workspace</div> }));

describe("AnalyticsPage", () => {
  it("combines insights and trends behind one Analytics workspace", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/analytics?tab=insights"]}><AnalyticsPage /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    expect(screen.getByText("Insights workspace")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Trends" }));
    expect(screen.getByText("Trends workspace")).toBeInTheDocument();
  });
});

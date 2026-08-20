import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AdvisorWorkspacePage } from "./AdvisorWorkspacePage";

vi.mock("./AdvisorPage", () => ({ AdvisorPage: () => <div>Advisor workspace</div> }));
vi.mock("./ReportsPage", () => ({ ReportsPage: () => <div>Reports workspace</div> }));

describe("AdvisorWorkspacePage", () => {
  it("keeps reports inside Advisor instead of a separate navigation destination", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/advisor"]}><AdvisorWorkspacePage /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Advisor" })).toBeInTheDocument();
    expect(screen.getByText("Advisor workspace")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reports" }));
    expect(screen.getByText("Reports workspace")).toBeInTheDocument();
  });
});

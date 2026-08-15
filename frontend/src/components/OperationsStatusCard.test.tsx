import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import { OperationsStatusCard } from "./OperationsStatusCard";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: 1, username: "owner", email: "owner@example.test", is_admin: true } }),
}));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<{ apiRequest: typeof apiRequest }>();
  return { ...actual, apiRequest: vi.fn() };
});

const job = {
  status: "healthy" as const,
  last_started_at: "2026-08-15T08:00:00Z",
  last_finished_at: "2026-08-15T08:00:01Z",
  last_success_at: "2026-08-15T08:00:01Z",
  age_hours: 0.5,
  error_code: null,
  summary: {},
};

describe("OperationsStatusCard", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset().mockResolvedValue({
      generated_at: "2026-08-15T08:30:00Z",
      overall: "healthy",
      database: { status: "healthy" },
      migration: { status: "healthy", current: "20260815_0019", head: "20260815_0019" },
      jobs: {
        database_backup: job,
        backup_verify: job,
        report_snapshot: job,
        plaid_sync: job,
        notifications: job,
        maintenance: { ...job, summary: { report_exports_deleted: 2 } },
      },
      maintenance: {
        report_export_count: 12,
        report_export_bytes: 4096,
        export_retention_days: 90,
        export_max_per_user: 50,
        auth_retention_days: 7,
        audit_retention_days: 365,
        minimum_free_bytes: 2147483648,
      },
      backup_storage: {
        path: "/var/lib/budget-app/backups",
        archive_count: 8,
        archive_bytes: 8192,
        free_bytes: 10737418240,
      },
      attention: [],
    });
  });

  it("shows bounded maintenance and export storage to administrators", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <OperationsStatusCard />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "Database maintenance" })).toBeInTheDocument();
    expect(screen.getByText("Saved exports")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("4.00 KB")).toBeInTheDocument();
    expect(screen.getByText(/Exports: 90d/)).toBeInTheDocument();
    expect(screen.getAllByText("Database maintenance").length).toBeGreaterThanOrEqual(2);
  });
});

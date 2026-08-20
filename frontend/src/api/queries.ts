import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./client";
import type { SetupOptions, SetupStatus } from "./types";

export const queryKeys = {
  setup: ["setup-status"] as const,
  setupOptions: ["setup-options"] as const,
  dashboard: (month: string) => ["dashboard", month] as const,
  dashboardPreferences: ["dashboard-preferences"] as const,
  cashFlow: (search: string) => ["cash-flow", search] as const,
  trends: (range: string) => ["trends", range] as const,
  dashboardOnboarding: ["dashboard-onboarding"] as const,
  accounts: ["accounts"] as const,
  plaidConnections: ["plaid-connections"] as const,
  transactions: (search: string) => ["transactions", search] as const,
  settings: ["settings"] as const,
  categories: ["categories"] as const,
  transactionRules: ["transaction-rules"] as const,
  recurring: ["recurring"] as const,
  subscriptions: ["subscriptions"] as const,
  financialCalendar: (month: string) => ["financial-calendar", month] as const,
  budgetMonth: (month: string) => ["budget-month", month] as const,
  budgetYear: (year: number) => ["budget-year", year] as const,
  annualBudgetPlan: (year: number) => ["annual-budget-plan", year] as const,
  goals: ["planning-goals"] as const,
  debts: ["planning-debts"] as const,
  forecast: ["planning-forecast"] as const,
  insights: (status: string) => ["insights", status] as const,
  advisorStatus: ["advisor-status"] as const,
  advisorConversations: ["advisor-conversations"] as const,
  advisorConversation: (id: number) => ["advisor-conversation", id] as const,
  advisorProposal: (id: number) => ["advisor-proposal", id] as const,
  reportsOverview: (days: number) => ["reports-overview", days] as const,
  reportsSpending: (range: string) => ["reports-spending", range] as const,
  reportsBudget: (range: string) => ["reports-budget", range] as const,
  reportsGoalsDebt: (range: string) => ["reports-goals-debt", range] as const,
  savedReports: ["saved-reports"] as const,
  reportExports: ["report-exports"] as const,
  securityStatus: ["security-status"] as const,
  authSessions: ["auth-sessions"] as const,
  userInvitations: ["user-invitations"] as const,
  familyStatus: ["family-status"] as const,
  adminUsers: ["admin-users"] as const,
  operationsStatus: ["operations-status"] as const,
  notificationCount: ["notification-count"] as const,
  notifications: (status: string) => ["notifications", status] as const,
  notificationPreferences: ["notification-preferences"] as const,
};

export function useSetupStatus() {
  return useQuery({
    queryKey: queryKeys.setup,
    queryFn: () => apiRequest<SetupStatus>("/setup/status"),
    staleTime: 10_000,
  });
}

export function useSetupOptions(enabled = true) {
  return useQuery({
    queryKey: queryKeys.setupOptions,
    queryFn: () => apiRequest<SetupOptions>("/setup/options"),
    staleTime: Number.POSITIVE_INFINITY,
    enabled,
  });
}

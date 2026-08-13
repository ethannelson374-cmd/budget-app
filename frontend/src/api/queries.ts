import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./client";
import type { SetupOptions, SetupStatus } from "./types";

export const queryKeys = {
  setup: ["setup-status"] as const,
  setupOptions: ["setup-options"] as const,
  dashboard: (month: string) => ["dashboard", month] as const,
  accounts: ["accounts"] as const,
  plaidConnections: ["plaid-connections"] as const,
  transactions: (search: string) => ["transactions", search] as const,
  settings: ["settings"] as const,
  categories: ["categories"] as const,
  transactionRules: ["transaction-rules"] as const,
  recurring: ["recurring"] as const,
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

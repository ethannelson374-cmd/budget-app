import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { PlaidConnectionsResponse } from "../api/types";
import { Brand } from "../components/Brand";
import { ErrorState, PageLoading } from "../components/States";
import { clearPlaidLinkSession, createPlaidHandler, storedPlaidLinkSession } from "../lib/plaid";

export function PlaidOAuthPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [startupError, setStartupError] = useState<string | null>(null);
  const complete = useMutation({
    mutationFn: async ({ publicToken, metadata }: { publicToken: string | null; metadata: PlaidLinkSuccessMetadata }) => {
      const session = storedPlaidLinkSession();
      if (!session) throw new Error("This Plaid session has expired.");
      if (session.mode === "update") {
        if (session.connectionId === null) throw new Error("Budget lost track of the connection being updated.");
        return apiRequest<PlaidConnectionsResponse>(`/plaid/connections/${session.connectionId}/refresh`, { method: "POST" });
      }
      if (!publicToken) throw new Error("Plaid did not return a connection token.");
      return apiRequest<PlaidConnectionsResponse>("/plaid/exchange", {
        method: "POST",
        body: JSON.stringify({
          public_token: publicToken,
          institution_id: metadata.institution?.institution_id ?? null,
          accounts: metadata.accounts.map(({ name, mask }) => ({ name, mask })),
        }),
      });
    },
    onSuccess: async () => {
      const returnTo = storedPlaidLinkSession()?.returnTo ?? "/accounts";
      clearPlaidLinkSession();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.plaidConnections }),
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["transactions"] }),
      ]);
      navigate(returnTo, { replace: true });
    },
    onError: () => clearPlaidLinkSession(),
  });

  const completeLink = complete.mutate;

  useEffect(() => {
    const session = storedPlaidLinkSession();
    if (!session) {
      setStartupError("This Plaid session has expired. Return to Accounts and try again.");
      return;
    }
    let handler: PlaidHandler | undefined;
    try {
      handler = createPlaidHandler({
        token: session.token,
        receivedRedirectUri: window.location.href,
        onSuccess: (publicToken, metadata) => completeLink({ publicToken, metadata }),
        onExit: () => {
          clearPlaidLinkSession();
          navigate(session.returnTo ?? "/accounts", { replace: true });
        },
        onLoad: () => handler?.open(),
      });
    } catch (error) {
      clearPlaidLinkSession();
      setStartupError(error instanceof Error ? error.message : "Plaid Link could not be resumed.");
    }
    return () => handler?.destroy();
  }, [completeLink, navigate]);

  if (startupError) {
    return (
      <main className="centered-page error-page">
        <Brand linked={false} />
        <ErrorState title="Bank connection could not resume" message={startupError} onRetry={() => navigate("/accounts", { replace: true })} />
      </main>
    );
  }
  if (complete.isError) {
    return (
      <main className="centered-page error-page">
        <Brand linked={false} />
        <ErrorState title="Bank connection could not finish" message={complete.error.message} onRetry={() => navigate("/accounts", { replace: true })} />
      </main>
    );
  }
  return <PageLoading label="Finishing your bank connection" />;
}

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { PlaidConnectionsResponse } from "../api/types";
import { Brand } from "../components/Brand";
import { ErrorState, PageLoading } from "../components/States";
import { clearPlaidLinkToken, createPlaidHandler, storedPlaidLinkToken } from "../lib/plaid";

export function PlaidOAuthPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [startupError, setStartupError] = useState<string | null>(null);
  const exchange = useMutation({
    mutationFn: ({ publicToken, metadata }: { publicToken: string; metadata: PlaidLinkSuccessMetadata }) =>
      apiRequest<PlaidConnectionsResponse>("/plaid/exchange", {
        method: "POST",
        body: JSON.stringify({
          public_token: publicToken,
          institution_id: metadata.institution?.institution_id ?? null,
          accounts: metadata.accounts.map(({ name, mask }) => ({ name, mask })),
        }),
      }),
    onSuccess: async () => {
      clearPlaidLinkToken();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.plaidConnections }),
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ]);
      navigate("/accounts", { replace: true });
    },
    onError: () => clearPlaidLinkToken(),
  });

  const exchangePublicToken = exchange.mutate;

  useEffect(() => {
    const token = storedPlaidLinkToken();
    if (!token) {
      setStartupError("This Plaid session has expired. Return to Accounts and connect the bank again.");
      return;
    }
    let handler: PlaidHandler | undefined;
    try {
      handler = createPlaidHandler({
        token,
        receivedRedirectUri: window.location.href,
        onSuccess: (publicToken, metadata) => {
          if (!publicToken) {
            clearPlaidLinkToken();
            setStartupError("Plaid did not return a connection token.");
            return;
          }
          exchangePublicToken({ publicToken, metadata });
        },
        onExit: () => {
          clearPlaidLinkToken();
          navigate("/accounts", { replace: true });
        },
        onLoad: () => handler?.open(),
      });
    } catch (error) {
      clearPlaidLinkToken();
      setStartupError(error instanceof Error ? error.message : "Plaid Link could not be resumed.");
    }
    return () => handler?.destroy();
  }, [exchangePublicToken, navigate]);

  if (startupError) {
    return (
      <main className="centered-page error-page">
        <Brand linked={false} />
        <ErrorState title="Bank connection could not resume" message={startupError} onRetry={() => navigate("/accounts", { replace: true })} />
      </main>
    );
  }
  if (exchange.isError) {
    return (
      <main className="centered-page error-page">
        <Brand linked={false} />
        <ErrorState title="Bank connection could not finish" message={exchange.error.message} onRetry={() => navigate("/accounts", { replace: true })} />
      </main>
    );
  }
  return <PageLoading label="Finishing your bank connection" />;
}

const STORAGE_KEY = "budget.plaid.link_session";
const LEGACY_STORAGE_KEY = "budget.plaid.link_token";

export type PlaidLinkSession = {
  token: string;
  mode: "connect" | "update";
  connectionId: number | null;
};

export function rememberPlaidLinkSession(session: PlaidLinkSession): void {
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  window.sessionStorage.removeItem(LEGACY_STORAGE_KEY);
}

export function storedPlaidLinkSession(): PlaidLinkSession | null {
  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Partial<PlaidLinkSession>;
      if (
        typeof parsed.token === "string"
        && (parsed.mode === "connect" || parsed.mode === "update")
        && (parsed.connectionId === null || typeof parsed.connectionId === "number")
      ) {
        return { token: parsed.token, mode: parsed.mode, connectionId: parsed.connectionId ?? null };
      }
    } catch {
      // Fall through to the legacy token compatibility path.
    }
  }
  const legacy = window.sessionStorage.getItem(LEGACY_STORAGE_KEY);
  return legacy ? { token: legacy, mode: "connect", connectionId: null } : null;
}

export function clearPlaidLinkSession(): void {
  window.sessionStorage.removeItem(STORAGE_KEY);
  window.sessionStorage.removeItem(LEGACY_STORAGE_KEY);
}

// Compatibility helpers for older tests/callers. New code should persist the full
// session so OAuth redirects can distinguish a new connection from update mode.
export function rememberPlaidLinkToken(token: string): void {
  rememberPlaidLinkSession({ token, mode: "connect", connectionId: null });
}

export function storedPlaidLinkToken(): string | null {
  return storedPlaidLinkSession()?.token ?? null;
}

export function clearPlaidLinkToken(): void {
  clearPlaidLinkSession();
}

export function createPlaidHandler(options: PlaidLinkOptions): PlaidHandler {
  if (!window.Plaid) {
    throw new Error("Plaid Link could not be loaded. Check the connection and try again.");
  }
  return window.Plaid.create(options);
}

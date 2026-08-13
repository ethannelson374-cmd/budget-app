const STORAGE_KEY = "budget.plaid.link_token";

export function rememberPlaidLinkToken(token: string): void {
  window.sessionStorage.setItem(STORAGE_KEY, token);
}

export function storedPlaidLinkToken(): string | null {
  return window.sessionStorage.getItem(STORAGE_KEY);
}

export function clearPlaidLinkToken(): void {
  window.sessionStorage.removeItem(STORAGE_KEY);
}

export function createPlaidHandler(options: PlaidLinkOptions): PlaidHandler {
  if (!window.Plaid) {
    throw new Error("Plaid Link could not be loaded. Check the connection and try again.");
  }
  return window.Plaid.create(options);
}

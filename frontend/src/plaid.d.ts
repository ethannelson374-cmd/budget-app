export {};

declare global {
  interface PlaidHandler {
    open: () => void;
    exit: (options?: { force?: boolean }) => void;
    destroy: () => void;
  }

  interface PlaidLinkAccountMetadata {
    id: string;
    name: string;
    mask: string | null;
    type?: string;
    subtype?: string | null;
  }

  interface PlaidLinkSuccessMetadata {
    institution: {
      name: string;
      institution_id: string;
    } | null;
    accounts: PlaidLinkAccountMetadata[];
  }

  interface PlaidLinkOptions {
    token: string;
    receivedRedirectUri?: string;
    onSuccess: (publicToken: string | null, metadata: PlaidLinkSuccessMetadata) => void;
    onExit?: (error: unknown, metadata: unknown) => void;
    onLoad?: () => void;
    onEvent?: (eventName: string, metadata: unknown) => void;
  }

  interface Window {
    Plaid?: {
      create: (options: PlaidLinkOptions) => PlaidHandler;
    };
  }
}

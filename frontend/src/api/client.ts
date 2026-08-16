import type { ApiErrorPayload } from "./types";

let csrfToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly fields?: Record<string, string[]>;
  readonly retryAfter?: number;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      requestId?: string;
      fields?: Record<string, string[]>;
      retryAfter?: number;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code ?? "request_failed";
    this.requestId = options.requestId;
    this.fields = options.fields;
    this.retryAfter = options.retryAfter;
  }
}

export function setCsrfToken(value: string | null): void {
  csrfToken = value;
}

export function getCsrfTokenForTesting(): string | null {
  return csrfToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function apiUrl(path: string): string {
  if (path.startsWith("/api/")) return path;
  return `/api/v1${path.startsWith("/") ? path : `/${path}`}`;
}

async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return undefined;
  return response.json();
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();
  const isUnsafe = !["GET", "HEAD", "OPTIONS"].includes(method);

  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (isUnsafe && csrfToken && !headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  const payload = await parseResponse(response);

  if (!response.ok) {
    const errorPayload = (payload ?? {}) as ApiErrorPayload;
    const retryAfterHeader = response.headers.get("retry-after");
    const retryAfter = retryAfterHeader ? Number.parseInt(retryAfterHeader, 10) : undefined;
    if (response.status === 401) unauthorizedHandler?.();
    throw new ApiError(errorPayload.error?.message ?? "The request could not be completed.", {
      status: response.status,
      code: errorPayload.error?.code,
      requestId: errorPayload.error?.request_id ?? response.headers.get("x-request-id") ?? undefined,
      fields: errorPayload.error?.fields,
      retryAfter: Number.isFinite(retryAfter) ? retryAfter : undefined,
    });
  }

  return payload as T;
}

export function toSearchParams(values: Record<string, string | number | boolean | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const result = params.toString();
  return result ? `?${result}` : "";
}


export interface ApiStreamEvent { event: string; data: unknown; }

export async function apiEventStream(
  path: string,
  init: RequestInit,
  onEvent: (event: ApiStreamEvent) => void,
): Promise<void> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();
  headers.set("Accept", "text/event-stream");
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken && !headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", csrfToken);

  const response = await fetch(apiUrl(path), { ...init, headers, credentials: "include", cache: "no-store" });
  if (!response.ok) {
    const payload = (await parseResponse(response)) as ApiErrorPayload | undefined;
    const retryHeader = response.headers.get("retry-after");
    const retryAfter = retryHeader ? Number.parseInt(retryHeader, 10) : undefined;
    if (response.status === 401) unauthorizedHandler?.();
    throw new ApiError(payload?.error?.message ?? "The request could not be completed.", {
      status: response.status, code: payload?.error?.code,
      requestId: payload?.error?.request_id ?? response.headers.get("x-request-id") ?? undefined,
      retryAfter: Number.isFinite(retryAfter) ? retryAfter : undefined,
    });
  }
  if (!response.body) throw new ApiError("The response stream was unavailable.", { status: 503, code: "stream_unavailable" });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let split = buffer.indexOf("\n\n");
    while (split >= 0) {
      const block = buffer.slice(0, split).replaceAll("\r", "");
      buffer = buffer.slice(split + 2);
      let event = "message";
      const data: string[] = [];
      block.split("\n").forEach((line) => {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      });
      if (data.length) {
        const raw = data.join("\n");
        let parsed: unknown = raw;
        try { parsed = JSON.parse(raw); } catch { /* keep raw data */ }
        onEvent({ event, data: parsed });
      }
      split = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
}

export async function apiDownload(path: string): Promise<void> {
  const response = await fetch(apiUrl(path), { credentials: "include", cache: "no-store" });
  if (!response.ok) {
    let message = "The download could not be completed.";
    try {
      const payload = (await response.json()) as ApiErrorPayload;
      message = payload.error?.message ?? message;
    } catch { /* non-JSON response */ }
    if (response.status === 401) unauthorizedHandler?.();
    throw new ApiError(message, { status: response.status, code: "download_failed" });
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1] ?? "budget-download";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

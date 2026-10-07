import type { components } from "./types.gen";

export type QueryItem = components["schemas"]["QueryItem"];
type QueryList = components["schemas"]["QueryList"];
type ErrorDetail = components["schemas"]["ErrorDetail"];

export type ApiErrorKind =
  /** HTTP 503: the API is up but its data is missing or invalid (ARCHITECTURE.md D8, FU-23). */
  | "data_unavailable"
  /** Any other non-200 status, including the dev proxy's answer when the API is down. */
  | "http"
  /** The request never got a response. */
  | "network"
  /** A 200 whose body is not the contract's QueryList. */
  | "bad_response";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  /**
   * The server's ErrorDetail.detail. It can contain absolute file paths, so the UI never
   * shows it unless the user asks for it.
   */
  readonly detail: string | null;

  constructor(kind: ApiErrorKind, status: number | null = null, detail: string | null = null) {
    super(status === null ? kind : `${kind} (HTTP ${status})`);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isQueryItem(value: unknown): value is QueryItem {
  return isRecord(value) && typeof value.query_id === "string" && typeof value.query === "string";
}

function isQueryList(value: unknown): value is QueryList {
  return isRecord(value) && Array.isArray(value.items) && value.items.every(isQueryItem);
}

function isErrorDetail(value: unknown): value is ErrorDetail {
  return isRecord(value) && typeof value.detail === "string";
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

/** GET /api/queries: the validation queries in query_id order. Throws ApiError, or AbortError. */
export async function fetchQueries(signal?: AbortSignal): Promise<QueryItem[]> {
  let response: Response;
  try {
    response = await fetch("/api/queries", { headers: { Accept: "application/json" }, signal });
  } catch (error) {
    if (signal?.aborted) {
      throw error;
    }
    throw new ApiError("network");
  }
  const body = await readJson(response);
  if (response.status === 503) {
    throw new ApiError("data_unavailable", 503, isErrorDetail(body) ? body.detail : null);
  }
  if (response.status !== 200) {
    throw new ApiError("http", response.status);
  }
  if (!isQueryList(body)) {
    throw new ApiError("bad_response", 200);
  }
  return body.items;
}

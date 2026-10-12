import type { components } from "./types.gen";

export type QueryItem = components["schemas"]["QueryItem"];
export type RunAccepted = components["schemas"]["RunAccepted"];
export type RunDetail = components["schemas"]["RunDetail"];
export type ItemDetail = components["schemas"]["ItemDetail"];
export type DayPlan = components["schemas"]["DayPlan"];
export type StageEvent = components["schemas"]["StageEvent"];
export type StreamError = components["schemas"]["StreamError"];
export type Stage = StageEvent["stage"];
type QueryList = components["schemas"]["QueryList"];
type ErrorDetail = components["schemas"]["ErrorDetail"];
type RunConflict = components["schemas"]["RunConflict"];
type RunRequest = components["schemas"]["RunRequest"];

/** The web client status rules of ARCHITECTURE.md D8. */
export type ApiErrorKind =
  /** No response, or 502/504 (the dev proxy's answer when the API is down). */
  | "unreachable"
  /** HTTP 503: the data is unavailable or the run cannot start; `detail` is the API's message. */
  | "data_unavailable"
  /** HTTP 409: the model is busy; `activeRunId` names this server's job when there is one. */
  | "busy"
  /** HTTP 404. */
  | "not_found"
  /** Any other unexpected status. */
  | "http"
  /** A success status whose body is not what the contract says. */
  | "bad_response";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  /** The server's message for a 503 or 409. It holds no absolute path (D8, FU-35). */
  readonly detail: string | null;
  readonly activeRunId: string | null;

  constructor(
    kind: ApiErrorKind,
    status: number | null = null,
    detail: string | null = null,
    activeRunId: string | null = null,
  ) {
    super(status === null ? kind : `${kind} (HTTP ${status})`);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
    this.activeRunId = activeRunId;
  }
}

/** What a rejected client call was: its ApiError, or unreachable for anything else. */
export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError("unreachable");
}

const RUN_STATUSES: readonly string[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "interrupted",
] satisfies RunDetail["status"][];

export const STAGES = [
  "queued",
  "generating",
  "parsing",
  "evaluating",
  "done",
] as const satisfies readonly Stage[];

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

function isRunConflict(value: unknown): value is RunConflict {
  return (
    isErrorDetail(value) &&
    "active_run_id" in value &&
    (value.active_run_id === null || typeof value.active_run_id === "string")
  );
}

function isRunAccepted(value: unknown): value is RunAccepted {
  return isRecord(value) && typeof value.run_id === "string";
}

export function isStage(value: unknown): value is Stage {
  return (STAGES as readonly unknown[]).includes(value);
}

export function isRunDetail(value: unknown): value is RunDetail {
  return (
    isRecord(value) &&
    typeof value.run_id === "string" &&
    typeof value.status === "string" &&
    RUN_STATUSES.includes(value.status) &&
    (value.stage === null || isStage(value.stage)) &&
    (value.error === null || typeof value.error === "string") &&
    (value.item === null ||
      (isRecord(value.item) && (value.item.plan === null || Array.isArray(value.item.plan))))
  );
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function errorFor(status: number, body: unknown): ApiError {
  const detail = isErrorDetail(body) ? body.detail : null;
  switch (status) {
    case 502:
    case 504:
      return new ApiError("unreachable", status);
    case 503:
      return new ApiError("data_unavailable", status, detail);
    case 409:
      return new ApiError("busy", status, detail, isRunConflict(body) ? body.active_run_id : null);
    case 404:
      return new ApiError("not_found", status);
    default:
      return new ApiError("http", status);
  }
}

/** One JSON request. Resolves with the body of an `expected` status; throws ApiError, or AbortError. */
async function request(path: string, expected: number, init: RequestInit = {}): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...init.headers },
    });
  } catch (error) {
    if (init.signal?.aborted) {
      throw error;
    }
    throw new ApiError("unreachable");
  }
  const body = await readJson(response);
  if (response.status !== expected) {
    throw errorFor(response.status, body);
  }
  return body;
}

/** GET /api/queries: the validation queries in query_id order. */
export async function fetchQueries(signal?: AbortSignal): Promise<QueryItem[]> {
  const body = await request("/api/queries", 200, { signal });
  if (!isQueryList(body)) {
    throw new ApiError("bad_response", 200);
  }
  return body.items;
}

/** POST /api/runs: start a single run of one query with seed 0. */
export async function startRun(queryId: string): Promise<RunAccepted> {
  const payload: RunRequest = { query_id: queryId, seed: 0 };
  const body = await request("/api/runs", 202, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!isRunAccepted(body)) {
    throw new ApiError("bad_response", 202);
  }
  return body;
}

export function runPath(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}`;
}

/** GET /api/runs/{run_id}: the run as it is on disk now. */
export async function fetchRun(runId: string, signal?: AbortSignal): Promise<RunDetail> {
  const body = await request(runPath(runId), 200, { signal });
  if (!isRunDetail(body)) {
    throw new ApiError("bad_response", 200);
  }
  return body;
}

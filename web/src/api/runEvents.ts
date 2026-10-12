import {
  isRunDetail,
  isStage,
  runPath,
  type RunDetail,
  type Stage,
  type StageEvent,
  type StreamError,
} from "./client";

export interface RunEventHandlers {
  onSnapshot: (detail: RunDetail) => void;
  onStage: (stage: Stage) => void;
  /** The run succeeded; the stream is closed. */
  onDone: (detail: RunDetail) => void;
  /** The run failed or was interrupted; the stream is closed. */
  onError: (error: StreamError) => void;
  /** The connection failed or sent something unreadable; the stream is closed. Poll instead. */
  onStreamFailed: () => void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStageEvent(value: unknown): value is StageEvent {
  return isRecord(value) && isStage(value.stage);
}

function isStreamError(value: unknown): value is StreamError {
  return isRecord(value) && typeof value.message === "string";
}

function dataOf(event: Event): unknown {
  if (!(event instanceof MessageEvent) || typeof event.data !== "string") {
    return undefined;
  }
  try {
    return JSON.parse(event.data);
  } catch {
    return undefined;
  }
}

/**
 * Follows GET /api/runs/{run_id}/events (ARCHITECTURE.md D8) and returns a function that stops.
 * The source is closed after the final event and on any failure, so it never reconnects.
 */
export function followRun(runId: string, handlers: RunEventHandlers): () => void {
  const source = new EventSource(`${runPath(runId)}/events`);
  let open = true;
  const close = () => {
    open = false;
    source.close();
  };
  const listen = (type: string, handle: (data: unknown) => boolean) => {
    source.addEventListener(type, (event) => {
      if (open && !handle(dataOf(event))) {
        close();
        handlers.onStreamFailed();
      }
    });
  };

  listen("snapshot", (data) => {
    if (!isRunDetail(data)) {
      return false;
    }
    handlers.onSnapshot(data);
    return true;
  });
  listen("stage", (data) => {
    if (!isStageEvent(data)) {
      return false;
    }
    handlers.onStage(data.stage);
    return true;
  });
  listen("done", (data) => {
    if (!isRunDetail(data)) {
      return false;
    }
    close();
    handlers.onDone(data);
    return true;
  });
  // The server's `error` event carries data; a connection failure is a plain Event of the same type.
  listen("error", (data) => {
    if (!isStreamError(data)) {
      return false;
    }
    close();
    handlers.onError(data);
    return true;
  });

  return close;
}

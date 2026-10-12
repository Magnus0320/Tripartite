import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchRun,
  startRun,
  toApiError,
  type ApiError,
  type RunDetail,
  type Stage,
} from "../../api/client";
import { followRun } from "../../api/runEvents";

export const POLL_INTERVAL_MS = 1000;

export interface FollowedRun {
  runId: string;
  queryId: string;
  /** Null until the first snapshot or poll answers. */
  detail: RunDetail | null;
  /** The last stage reported. Stages can be skipped (ARCHITECTURE.md D8). */
  stage: Stage | null;
  /** `stream`: following the event stream; `polling`: the fallback; `ended`: nothing more to come. */
  live: "stream" | "polling" | "ended";
  /** Why polling stopped before the run finished. */
  followError: ApiError | null;
  /** The stream's `error` message, shown only if the run itself cannot be read afterwards. */
  streamMessage: string | null;
}

export interface RunState {
  starting: boolean;
  startError: ApiError | null;
  run: FollowedRun | null;
}

export function isTerminal(status: RunDetail["status"]): boolean {
  return status === "succeeded" || status === "failed" || status === "interrupted";
}

interface Follower {
  stop: () => void;
  poll: () => void;
}

/** W2: starts a single run and follows it by SSE, falling back to polling GET /api/runs/{id}. */
export function useRun(): RunState & { start: (queryId: string) => void; checkAgain: () => void } {
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<ApiError | null>(null);
  const [run, setRun] = useState<FollowedRun | null>(null);
  const follower = useRef<Follower | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      follower.current?.stop();
      follower.current = null;
    };
  }, []);

  const follow = useCallback((runId: string) => {
    follower.current?.stop();
    const controller = new AbortController();
    let timer: number | undefined;
    let stopped = false;
    const patch = (changes: Partial<FollowedRun>) => {
      if (!stopped) {
        setRun((current) => (current?.runId === runId ? { ...current, ...changes } : current));
      }
    };
    const show = (detail: RunDetail, changes: Partial<FollowedRun> = {}) => {
      patch({ detail, stage: detail.stage, followError: null, ...changes });
    };

    const poll = () => {
      patch({ live: "polling", followError: null });
      fetchRun(runId, controller.signal).then(
        (detail) => {
          if (isTerminal(detail.status)) {
            show(detail, { live: "ended" });
          } else {
            show(detail);
            timer = window.setTimeout(poll, POLL_INTERVAL_MS);
          }
        },
        (error: unknown) => {
          patch({ followError: toApiError(error) });
        },
      );
    };

    const stopStream = followRun(runId, {
      onSnapshot: show,
      onStage: (stage) => {
        patch({ stage });
      },
      onDone: (detail) => {
        show(detail, { live: "ended" });
      },
      onError: ({ message }) => {
        // RunDetail.error is what the UI shows; the stream's message is the fallback.
        patch({ streamMessage: message });
        fetchRun(runId, controller.signal).then(
          (detail) => {
            show(detail, { live: "ended" });
          },
          () => {
            patch({ live: "ended" });
          },
        );
      },
      onStreamFailed: poll,
    });

    follower.current = {
      poll,
      stop: () => {
        stopped = true;
        stopStream();
        window.clearTimeout(timer);
        controller.abort();
      },
    };
  }, []);

  const start = useCallback(
    (queryId: string) => {
      setStarting(true);
      setStartError(null);
      startRun(queryId).then(
        (accepted) => {
          if (!mounted.current) {
            return;
          }
          setStarting(false);
          setRun({
            runId: accepted.run_id,
            queryId,
            detail: null,
            stage: null,
            live: "stream",
            followError: null,
            streamMessage: null,
          });
          follow(accepted.run_id);
        },
        (error: unknown) => {
          // A refused start (409 above all) leaves the run being followed as it is.
          setStarting(false);
          setStartError(toApiError(error));
        },
      );
    },
    [follow],
  );

  const checkAgain = useCallback(() => {
    follower.current?.poll();
  }, []);

  return { starting, startError, run, start, checkAgain };
}

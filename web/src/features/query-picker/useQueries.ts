import { useCallback, useEffect, useState } from "react";

import { ApiError, fetchQueries, type QueryItem } from "../../api/client";

export type QueriesState =
  | { status: "loading" }
  | { status: "ready"; items: QueryItem[] }
  | { status: "error"; error: ApiError };

/** Loads GET /api/queries on mount and again on every reload(). */
export function useQueries(): { state: QueriesState; reload: () => void } {
  const [state, setState] = useState<QueriesState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchQueries(controller.signal).then(
      (items) => {
        setState({ status: "ready", items });
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: "error",
          error: error instanceof ApiError ? error : new ApiError("network"),
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  return { state, reload };
}

import type { ReactNode } from "react";

import type { ApiError } from "../api/client";

interface ApiErrorNoticeProps {
  error: ApiError;
  /** The heading of a 503, which means different things to different requests. */
  unavailableTitle: string;
  /** Buttons, such as Retry. */
  children?: ReactNode;
}

/** One failed API request, by the web client status rules of ARCHITECTURE.md D8. */
export function ApiErrorNotice({ error, unavailableTitle, children }: ApiErrorNoticeProps) {
  return (
    <div className="notice notice-error" role="alert">
      <Message error={error} unavailableTitle={unavailableTitle} />
      {children !== undefined && <div className="notice-actions">{children}</div>}
    </div>
  );
}

function Message({ error, unavailableTitle }: Omit<ApiErrorNoticeProps, "children">) {
  switch (error.kind) {
    case "unreachable":
      return (
        <>
          <h3>Can&rsquo;t reach the API</h3>
          <p>
            Start the API with <code>make api</code> and try again.
          </p>
        </>
      );
    case "data_unavailable":
      return (
        <>
          <h3>{unavailableTitle}</h3>
          <p className="notice-message">
            {error.detail ?? "The API answered 503 without a message."}
          </p>
        </>
      );
    case "busy":
      return (
        <>
          <h3>The model is busy</h3>
          <p>One job runs at a time. Try again when the current one has finished.</p>
          {error.activeRunId !== null && (
            <p>
              Active run: <span className="run-id">{error.activeRunId}</span>
            </p>
          )}
        </>
      );
    case "not_found":
      return (
        <>
          <h3>Not found</h3>
          <p>The API does not know what was asked for.</p>
        </>
      );
    case "bad_response":
      return (
        <>
          <h3>Unexpected response</h3>
          <p>The API answered, but not in the form its contract describes.</p>
        </>
      );
    case "http":
      return (
        <>
          <h3>The API returned an error</h3>
          <p>HTTP status {error.status}</p>
        </>
      );
  }
}

import { useState } from "react";

import type { ApiError } from "../../api/client";

interface LoadErrorProps {
  error: ApiError;
  onRetry: () => void;
}

/** Why the query list could not be loaded. The messages are fixed; see DataUnavailable. */
export function LoadError({ error, onRetry }: LoadErrorProps) {
  if (error.kind === "data_unavailable") {
    return <DataUnavailable detail={error.detail} onRetry={onRetry} />;
  }
  return (
    <div className="notice notice-error" role="alert">
      <h3>Can&rsquo;t reach the API</h3>
      <p>
        {error.kind === "bad_response"
          ? "The API answered, but not with a list of queries."
          : "The query list could not be loaded."}{" "}
        Start the API with <code>make api</code> and try again.
      </p>
      {error.status !== null && error.kind === "http" && (
        <p className="muted">HTTP status {error.status}</p>
      )}
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

/**
 * The 503 state. The server's detail text can contain absolute file paths, so it is not
 * rendered at all until the user asks for it.
 */
function DataUnavailable({ detail, onRetry }: { detail: string | null; onRetry: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="notice notice-error" role="alert">
      <h3>Query data is unavailable</h3>
      <p>
        The API is running but could not load the validation queries. Check the data set (
        <code>make data</code>, or <code>TRIPARTITE_DATA_DIR</code>) and try again.
      </p>
      <div className="notice-actions">
        <button type="button" onClick={onRetry}>
          Retry
        </button>
        {detail !== null && (
          <button
            type="button"
            className="button-quiet"
            aria-expanded={open}
            aria-controls="data-unavailable-detail"
            onClick={() => {
              setOpen((value) => !value);
            }}
          >
            {open ? "Hide details" : "Show details"}
          </button>
        )}
      </div>
      {detail !== null && open && (
        <pre id="data-unavailable-detail" className="notice-detail">
          {detail}
        </pre>
      )}
    </div>
  );
}

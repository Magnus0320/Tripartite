import type { ApiError } from "../../api/client";
import { ApiErrorNotice } from "../../components/ApiErrorNotice";

interface LoadErrorProps {
  error: ApiError;
  onRetry: () => void;
}

/** Why the query list could not be loaded, with a Retry button. */
export function LoadError({ error, onRetry }: LoadErrorProps) {
  return (
    <ApiErrorNotice error={error} unavailableTitle="Query data is unavailable">
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </ApiErrorNotice>
  );
}

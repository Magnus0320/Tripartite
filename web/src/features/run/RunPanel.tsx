import type { RunDetail } from "../../api/client";
import { ApiErrorNotice } from "../../components/ApiErrorNotice";
import { PlanCards } from "./PlanCards";
import { StageTrack } from "./StageTrack";
import { isTerminal, type FollowedRun, type RunState } from "./useRun";

const STATUS_TEXT: Record<RunDetail["status"], string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Finished",
  failed: "Failed",
  interrupted: "Interrupted",
};

interface RunPanelProps {
  state: RunState;
  onCheckAgain: () => void;
}

/** W2: the run that was started here — its live stage, then its plan or its error. */
export function RunPanel({ state, onCheckAgain }: RunPanelProps) {
  const { startError, run } = state;
  return (
    <section className="panel run" aria-labelledby="run-heading">
      <h2 id="run-heading">Run</h2>
      {startError !== null && (
        <ApiErrorNotice error={startError} unavailableTitle="The run can&rsquo;t start" />
      )}
      {run === null ? (
        startError === null && <p className="muted">No run yet. Select a query and press Run.</p>
      ) : (
        <FollowedRunView run={run} onCheckAgain={onCheckAgain} />
      )}
    </section>
  );
}

function FollowedRunView({ run, onCheckAgain }: { run: FollowedRun; onCheckAgain: () => void }) {
  const { detail } = run;
  const finished = detail !== null && isTerminal(detail.status);
  const stage = detail?.status === "succeeded" ? "done" : run.stage;
  const item = detail?.item ?? null;

  return (
    <>
      <p className="run-meta">
        <span className="query-id">{run.queryId}</span>
        <span className="run-id muted">{run.runId}</span>
      </p>
      <p className="run-status" role="status" data-status={detail?.status}>
        {detail === null ? "Starting…" : STATUS_TEXT[detail.status]}
      </p>
      <StageTrack stage={stage} active={!finished && run.live !== "ended"} />

      {run.live === "polling" && run.followError === null && (
        <p className="muted">The live stream stopped; checking the run every second.</p>
      )}
      {run.followError !== null && (
        <ApiErrorNotice error={run.followError} unavailableTitle="The run can&rsquo;t be read">
          <button type="button" onClick={onCheckAgain}>
            Check again
          </button>
        </ApiErrorNotice>
      )}

      {detail !== null && (detail.status === "failed" || detail.status === "interrupted") ? (
        <div className="notice notice-error" role="alert">
          <h3>{detail.status === "failed" ? "The run failed" : "The run was interrupted"}</h3>
          <p className="notice-message">
            {detail.error ?? run.streamMessage ?? "No error message was recorded."}
          </p>
        </div>
      ) : (
        run.live === "ended" &&
        run.streamMessage !== null && (
          <div className="notice notice-error" role="alert">
            <h3>The run ended with an error</h3>
            <p className="notice-message">{run.streamMessage}</p>
          </div>
        )
      )}

      {item !== null && !item.delivered && (
        <div className="notice" role="status">
          <h3>No plan was delivered</h3>
          <p className="notice-message">
            Reason: {item.failure_reason ?? "none was recorded"}
          </p>
        </div>
      )}
      {item !== null && item.plan !== null && <PlanCards plan={item.plan} />}
    </>
  );
}

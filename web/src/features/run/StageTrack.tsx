import { STAGES, type Stage } from "../../api/client";

const LABELS: Record<Stage, string> = {
  queued: "Queued",
  generating: "Generating",
  parsing: "Parsing",
  evaluating: "Evaluating",
  done: "Done",
};

interface StageTrackProps {
  /** The last stage reported, or null before the first one. */
  stage: Stage | null;
  /** False once the run has finished: no stage is "in progress" any more. */
  active: boolean;
}

/**
 * The five stages of a run (ARCHITECTURE.md D7). Every stage before the current one counts as
 * passed, whether or not it was reported: short stages are often skipped (D8).
 */
export function StageTrack({ stage, active }: StageTrackProps) {
  const current = stage === null ? -1 : STAGES.indexOf(stage);
  return (
    <ol className="stages" aria-label="Stage">
      {STAGES.map((name, index) => {
        const isCurrent = index === current;
        const state =
          index < current || (isCurrent && name === "done")
            ? "passed"
            : isCurrent
              ? active
                ? "current"
                : "stopped"
              : "pending";
        return (
          <li key={name} data-state={state} aria-current={isCurrent ? "step" : undefined}>
            {LABELS[name]}
          </li>
        );
      })}
    </ol>
  );
}

import { useState } from "react";

import type { QueryItem } from "./api/client";
import { QueryPicker } from "./features/query-picker/QueryPicker";
import { useQueries } from "./features/query-picker/useQueries";
import { RunPanel } from "./features/run/RunPanel";
import { useRun } from "./features/run/useRun";

export function App() {
  const { state, reload } = useQueries();
  const [selected, setSelected] = useState<QueryItem | null>(null);
  const { start, checkAgain, ...run } = useRun();

  return (
    <div className="page">
      <header className="page-header">
        <h1>Tripartite</h1>
        <p className="muted">A TravelPlanner sole-planning baseline on a local model.</p>
      </header>
      <main className="layout">
        <QueryPicker
          state={state}
          selectedId={selected?.query_id ?? null}
          onSelect={setSelected}
          onRetry={reload}
        />
        <div className="side">
          <section className="panel selected" aria-labelledby="selected-heading">
            <h2 id="selected-heading">Selected query</h2>
            {selected === null ? (
              <p className="muted">No query selected.</p>
            ) : (
              <>
                <p className="query-id">{selected.query_id}</p>
                <p className="selected-text">{selected.query}</p>
              </>
            )}
            {/* Enabled while a run is followed: the API decides whether the model is busy (409). */}
            <button
              type="button"
              className="run-button"
              disabled={selected === null || run.starting}
              onClick={() => {
                if (selected !== null) {
                  start(selected.query_id);
                }
              }}
            >
              {run.starting ? "Starting…" : "Run"}
            </button>
          </section>
          <RunPanel state={run} onCheckAgain={checkAgain} />
        </div>
      </main>
    </div>
  );
}

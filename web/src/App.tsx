import { useState } from "react";

import type { QueryItem } from "./api/client";
import { QueryPicker } from "./features/query-picker/QueryPicker";
import { useQueries } from "./features/query-picker/useQueries";

export function App() {
  const { state, reload } = useQueries();
  const [selected, setSelected] = useState<QueryItem | null>(null);

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
        </section>
      </main>
    </div>
  );
}

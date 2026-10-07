import { useId, useMemo, useState } from "react";

import type { QueryItem } from "../../api/client";
import { filterQueries } from "./filterQueries";
import { LoadError } from "./LoadError";
import type { QueriesState } from "./useQueries";

interface QueryPickerProps {
  state: QueriesState;
  selectedId: string | null;
  onSelect: (item: QueryItem) => void;
  onRetry: () => void;
}

/** W1: a searchable list of the validation queries. Selecting one only marks it. */
export function QueryPicker({ state, selectedId, onSelect, onRetry }: QueryPickerProps) {
  const [search, setSearch] = useState("");
  const searchId = useId();
  const items = state.status === "ready" ? state.items : null;
  const visible = useMemo(() => (items === null ? [] : filterQueries(items, search)), [items, search]);

  return (
    <section className="panel picker" aria-labelledby={`${searchId}-heading`}>
      <h2 id={`${searchId}-heading`}>Queries</h2>
      <div className="search">
        <label htmlFor={searchId}>Search queries</label>
        <input
          id={searchId}
          type="search"
          value={search}
          placeholder="Text or query id"
          autoComplete="off"
          spellCheck={false}
          disabled={items === null || items.length === 0}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
        />
      </div>

      {state.status === "loading" && (
        <p className="notice" role="status">
          Loading queries…
        </p>
      )}

      {state.status === "error" && <LoadError error={state.error} onRetry={onRetry} />}

      {items !== null && items.length === 0 && (
        <div className="notice" role="status">
          <h3>No queries available</h3>
          <p>The API returned an empty list.</p>
        </div>
      )}

      {items !== null && items.length > 0 && (
        <>
          <p className="count muted" role="status">
            {visible.length} of {items.length} queries
          </p>
          {visible.length === 0 ? (
            <div className="notice">
              <p>No queries match &ldquo;{search.trim()}&rdquo;.</p>
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                }}
              >
                Clear search
              </button>
            </div>
          ) : (
            <fieldset className="query-list">
              <legend className="visually-hidden">Choose a query</legend>
              {visible.map((item) => (
                <label key={item.query_id} className="query-row">
                  <input
                    type="radio"
                    name={`${searchId}-query`}
                    value={item.query_id}
                    checked={item.query_id === selectedId}
                    onChange={() => {
                      onSelect(item);
                    }}
                  />
                  <span className="query-id">{item.query_id}</span>
                  <span className="query-text">{item.query}</span>
                </label>
              ))}
            </fieldset>
          )}
        </>
      )}
    </section>
  );
}

import { describe, expect, it } from "vitest";

import { filterQueries } from "./filterQueries";

const items = [
  { query_id: "val-001", query: "Plan a 3-day trip from Austin to Denver." },
  { query_id: "val-002", query: "A week in Seattle for two people on a budget." },
  { query_id: "val-010", query: "Five days from Denver to Seattle with a pet." },
];

describe("filterQueries", () => {
  it("returns everything, in order, for blank text", () => {
    expect(filterQueries(items, "")).toEqual(items);
    expect(filterQueries(items, "  \t ")).toEqual(items);
  });

  it("ignores case and searches both query_id and query", () => {
    expect(filterQueries(items, "AUSTIN").map((item) => item.query_id)).toEqual(["val-001"]);
    expect(filterQueries(items, "VAL-01").map((item) => item.query_id)).toEqual(["val-010"]);
  });

  it("requires every word to match, and returns [] when nothing does", () => {
    expect(filterQueries(items, " seattle  denver ").map((item) => item.query_id)).toEqual([
      "val-010",
    ]);
    expect(filterQueries(items, "seattle paris")).toEqual([]);
  });
});

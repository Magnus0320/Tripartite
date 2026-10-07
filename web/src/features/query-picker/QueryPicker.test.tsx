import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "../../App";

const CITIES = ["Austin", "Denver", "Seattle", "Boston", "Miami", "Chicago"];

/** 180 items shaped like the API's QueryList; "Austin" occurs in 30 of them. */
function queryList() {
  return {
    items: Array.from({ length: 180 }, (_, i) => ({
      query_id: `val-${String(i + 1).padStart(3, "0")}`,
      query: `Plan trip number ${i + 1} to ${CITIES[i % CITIES.length]}.`,
    })),
  };
}

function stubFetch(...responses: (() => Response | Promise<Response>)[]) {
  const fetchMock = vi.fn(() => {
    const next = responses.length > 1 ? responses.shift() : responses[0];
    if (next === undefined) {
      throw new Error("no response stubbed");
    }
    return Promise.resolve().then(next);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const ok = () => Response.json(queryList());
const search = () => screen.getByRole("searchbox", { name: "Search queries" });

describe("QueryPicker", () => {
  it("shows a loading status, then all 180 queries with only query_id and query", async () => {
    stubFetch(ok);
    render(<App />);

    expect(screen.getByText("Loading queries…")).toBeTruthy();
    expect(search()).toHaveProperty("disabled", true);

    const radios = await screen.findAllByRole("radio");
    expect(radios).toHaveLength(180);
    expect(screen.getByText("180 of 180 queries")).toBeTruthy();
    expect(screen.queryByText("Loading queries…")).toBeNull();

    const first = screen.getByRole("radio", { name: /^val-001/ }).closest("label");
    expect(first?.textContent).toBe("val-001Plan trip number 1 to Austin.");
  });

  it("filters the list as the user types and updates the count", async () => {
    stubFetch(ok);
    render(<App />);
    await screen.findAllByRole("radio");

    fireEvent.change(search(), { target: { value: "austin" } });

    expect(screen.getAllByRole("radio")).toHaveLength(30);
    expect(screen.getByText("30 of 180 queries")).toBeTruthy();

    fireEvent.change(search(), { target: { value: "val-180" } });
    expect(screen.getAllByRole("radio")).toHaveLength(1);
  });

  it("says when nothing matches, and Clear search brings the list back", async () => {
    stubFetch(ok);
    render(<App />);
    await screen.findAllByRole("radio");

    fireEvent.change(search(), { target: { value: "zanzibar" } });

    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(screen.getByText("No queries match “zanzibar”.")).toBeTruthy();
    expect(screen.getByText("0 of 180 queries")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getAllByRole("radio")).toHaveLength(180);
  });

  it("marks the chosen query as selected and keeps it when the search hides it", async () => {
    stubFetch(ok);
    render(<App />);
    await screen.findAllByRole("radio");
    const panel = within(screen.getByRole("region", { name: "Selected query" }));
    expect(panel.getByText("No query selected.")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: /^val-002/ }));

    expect(screen.getByRole("radio", { name: /^val-002/ })).toHaveProperty("checked", true);
    expect(screen.getAllByRole("radio", { checked: true })).toHaveLength(1);
    expect(panel.getByText("val-002")).toBeTruthy();
    expect(panel.getByText("Plan trip number 2 to Denver.")).toBeTruthy();

    fireEvent.change(search(), { target: { value: "austin" } });
    expect(screen.queryByRole("radio", { name: /^val-002/ })).toBeNull();
    expect(panel.getByText("val-002")).toBeTruthy();
  });

  it("shows a fixed message for a 503 and keeps the detail out of the page until asked", async () => {
    const detail = "validation.csv not found: /Users/x/data/raw/validation.csv";
    stubFetch(() => Response.json({ detail }, { status: 503 }));
    render(<App />);

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { name: "Query data is unavailable" })).toBeTruthy();
    expect(document.body.textContent).not.toContain("/Users/x");
    expect(screen.queryAllByRole("radio")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Show details" }));
    expect(within(alert).getByText(detail)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Hide details" }));
    expect(document.body.textContent).not.toContain("/Users/x");
  });

  it("loads the list when Retry succeeds after a 503", async () => {
    const fetchMock = stubFetch(() => Response.json({ detail: "gone" }, { status: 503 }), ok);
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    expect(await screen.findAllByRole("radio")).toHaveLength(180);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows the empty state for an empty list", async () => {
    stubFetch(() => Response.json({ items: [] }));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "No queries available" })).toBeTruthy();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    expect(search()).toHaveProperty("disabled", true);
  });

  it("shows that the API is unreachable when the request fails", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    render(<App />);

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { name: "Can’t reach the API" })).toBeTruthy();
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});

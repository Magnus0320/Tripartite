import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DayPlan, ItemDetail, RunDetail } from "../../api/client";
import { App } from "../../App";
import { stubEventSource } from "../../test/fakeEventSource";

const RUN_ID = "20261012T100000Z-single-abcd1234-0001";
const QUERIES = { items: [{ query_id: "val-001", query: "A three-day trip." }] };

function day(n: number, changes: Partial<DayPlan> = {}): DayPlan {
  return {
    day: n,
    current_city: `from Austin to City ${n}`,
    transportation: `Flight F${n}`,
    breakfast: `Breakfast place ${n}`,
    attraction: `Museum ${n};Park ${n};`,
    attractions: [`Museum ${n}`, `Park ${n}`],
    lunch: `Lunch place ${n}`,
    dinner: `Dinner place ${n}`,
    accommodation: `Hotel ${n}`,
    ...changes,
  };
}

function item(changes: Partial<ItemDetail> = {}): ItemDetail {
  return {
    query_id: "val-001",
    seed: 0,
    query: "A three-day trip.",
    delivered: true,
    failure_reason: null,
    plan: [day(1), day(2, { attraction: "-", attractions: [] })],
    constraints: [
      { group: "hard", key: "budget", label: "Within budget", message: "over by 40", status: "fail" },
    ],
    commonsense_pass: true,
    hard_pass: false,
    final_pass: false,
    usage: {
      input_tokens: 31337,
      output_tokens: 4242,
      thinking_tokens: 0,
      load_ms: null,
      prefill_ms: null,
      generation_ms: null,
      total_ms: null,
      wall_ms: 98765,
    },
    raw_output: "RAW-OUTPUT-TEXT",
    ...changes,
  };
}

function run(changes: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: RUN_ID,
    kind: "single",
    status: "running",
    stage: "generating",
    created_at: "2026-10-12T10:00:00Z",
    finished_at: null,
    config_hash: "abcd1234",
    model: { tag: "fake", digest: "0" },
    prompt_version: "v1",
    error: null,
    item: null,
    summary: null,
    ...changes,
  };
}

const succeeded = (changes: Partial<ItemDetail> = {}) =>
  run({ status: "succeeded", stage: "done", finished_at: "2026-10-12T10:01:00Z", item: item(changes) });

type Respond = () => Response | Promise<Response>;

/** Stubs fetch: the query list, POST /api/runs, and GET /api/runs/{id} answered in order. */
function stubApi(post: Respond, ...gets: Respond[]) {
  const posts: unknown[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/queries") {
      return Response.json(QUERIES);
    }
    if (url === "/api/runs" && init?.method === "POST") {
      posts.push(JSON.parse(String(init.body)));
      return post();
    }
    if (url === `/api/runs/${RUN_ID}`) {
      const next = gets.length > 1 ? gets.shift() : gets[0];
      if (next !== undefined) {
        return next();
      }
    }
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { posts, fetchMock };
}

const accepted: Respond = () => Response.json({ run_id: RUN_ID, status: "queued" }, { status: 202 });
const runButton = () => screen.getByRole("button", { name: "Run" });
const panel = () => within(screen.getByRole("region", { name: "Run" }));
const stageNow = () => panel().getByRole("list", { name: "Stage" }).querySelector("[aria-current]");

/** Renders the app, selects val-001 and presses Run; resolves once the POST has been answered. */
async function pressRun() {
  const latest = stubEventSource();
  const view = render(<App />);
  fireEvent.click(await screen.findByRole("radio", { name: /^val-001/ }));
  fireEvent.click(runButton());
  await waitFor(() => {
    expect(runButton()).toHaveProperty("disabled", false);
  });
  return { latest, view };
}

describe("Run", () => {
  it("is disabled until a query is selected", async () => {
    stubApi(accepted);
    stubEventSource();
    render(<App />);
    await screen.findByRole("radio", { name: /^val-001/ });

    expect(runButton()).toHaveProperty("disabled", true);
    expect(panel().getByText("No run yet. Select a query and press Run.")).toBeTruthy();
  });

  it("posts the query with seed 0, follows the stream and shows the plan cards on done", async () => {
    const { posts, fetchMock } = stubApi(accepted);
    const { latest } = await pressRun();
    const source = latest();

    expect(posts).toEqual([{ query_id: "val-001", seed: 0 }]);
    expect(source.url).toBe(`/api/runs/${RUN_ID}/events`);
    expect(panel().getByText(RUN_ID)).toBeTruthy();
    expect(panel().getByRole("status").textContent).toBe("Starting…");

    act(() => {
      source.emit("snapshot", run({ status: "queued", stage: "queued" }));
    });
    expect(panel().getByRole("status").textContent).toBe("Queued");
    expect(stageNow()?.textContent).toBe("Queued");

    act(() => {
      source.emit("snapshot", run());
    });
    expect(panel().getByRole("status").textContent).toBe("Running");
    expect(stageNow()?.textContent).toBe("Generating");

    // `parsing` is never sent: the client must not wait for it.
    act(() => {
      source.emit("stage", { stage: "evaluating" });
    });
    expect(stageNow()?.textContent).toBe("Evaluating");
    expect(panel().queryByRole("list", { name: "Plan" })).toBeNull();

    act(() => {
      source.emit("done", succeeded());
    });
    expect(panel().getByRole("status").textContent).toBe("Finished");
    expect(stageNow()?.textContent).toBe("Done");
    expect(source.closed).toBe(true);

    const cards = panel().getAllByRole("article");
    expect(cards).toHaveLength(2);
    const first = within(cards[0] as HTMLElement);
    expect(first.getByRole("heading", { name: "Day 1" })).toBeTruthy();
    for (const text of [
      "from Austin to City 1",
      "Flight F1",
      "Breakfast place 1",
      "Lunch place 1",
      "Dinner place 1",
      "Hotel 1",
    ]) {
      expect(first.getByText(text)).toBeTruthy();
    }
    expect(first.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Museum 1", "Park 1"]);
    expect(within(cards[1] as HTMLElement).queryAllByRole("listitem")).toHaveLength(0);

    // The stream alone was enough, and W3/W4 are not here yet.
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith("/api/runs/"))).toEqual([]);
    for (const hidden of ["Within budget", "over by 40", "31337", "98765", "RAW-OUTPUT-TEXT"]) {
      expect(document.body.textContent).not.toContain(hidden);
    }
  });

  it("falls back to polling when the stream fails, until the run is finished", async () => {
    const { fetchMock } = stubApi(
      accepted,
      () => Response.json(run({ stage: "evaluating" })),
      () => Response.json(succeeded()),
    );
    const { latest } = await pressRun();
    const source = latest();
    act(() => {
      source.emit("snapshot", run());
      source.fail();
    });

    expect(source.closed).toBe(true);
    expect(await panel().findByText("The live stream stopped; checking the run every second.")).toBeTruthy();
    await waitFor(() => {
      expect(stageNow()?.textContent).toBe("Evaluating");
    });

    await waitFor(
      () => {
        expect(panel().getByRole("status").textContent).toBe("Finished");
      },
      { timeout: 3000 },
    );
    expect(panel().getAllByRole("article")).toHaveLength(2);
    expect(panel().queryByText(/checking the run every second/)).toBeNull();
    const polls = () =>
      fetchMock.mock.calls.filter(([url]) => String(url) === `/api/runs/${RUN_ID}`).length;
    expect(polls()).toBe(2);

    // A finished run is not polled again.
    await new Promise((resolve) => setTimeout(resolve, 1200));
    expect(polls()).toBe(2);
  });

  it("stops polling on an API error and resumes with Check again", async () => {
    stubApi(
      accepted,
      () => new Response("", { status: 502 }),
      () => Response.json(succeeded()),
    );
    const { latest } = await pressRun();
    act(() => {
      latest().fail();
    });

    const alert = await panel().findByRole("alert");
    expect(within(alert).getByRole("heading", { name: "Can’t reach the API" })).toBeTruthy();

    fireEvent.click(within(alert).getByRole("button", { name: "Check again" }));

    expect(await panel().findAllByRole("article")).toHaveLength(2);
    expect(panel().queryByRole("alert")).toBeNull();
  });

  it.each([
    ["failed", "The run failed", "ValueError: unknown level in raw/validation.csv"],
    ["interrupted", "The run was interrupted", "Interrupted: the API server stopped"],
  ] as const)("shows RunDetail.error for a %s run", async (status, heading, error) => {
    stubApi(accepted, () =>
      Response.json(run({ status, stage: "evaluating", finished_at: "2026-10-12T10:01:00Z", error })),
    );
    const { latest } = await pressRun();
    const source = latest();
    act(() => {
      source.emit("snapshot", run({ stage: "evaluating" }));
      source.emit("error", { message: "the stream's own wording" });
    });

    const alert = await panel().findByRole("alert");
    expect(within(alert).getByRole("heading", { name: heading })).toBeTruthy();
    expect(within(alert).getByText(error)).toBeTruthy();
    expect(source.closed).toBe(true);
    expect(stageNow()?.getAttribute("data-state")).toBe("stopped");
    expect(document.body.textContent).not.toContain("the stream's own wording");
    expect(panel().queryAllByRole("article")).toHaveLength(0);
  });

  it("shows the stream's error message when the run cannot be read afterwards", async () => {
    stubApi(accepted, () => new Response("", { status: 502 }));
    const { latest } = await pressRun();
    act(() => {
      latest().emit("error", { message: "LLMError: no answer" });
    });

    const alert = await panel().findByRole("alert");
    expect(within(alert).getByRole("heading", { name: "The run ended with an error" })).toBeTruthy();
    expect(within(alert).getByText("LLMError: no answer")).toBeTruthy();
  });

  it("shows the failure reason of a plan that was not delivered", async () => {
    stubApi(accepted);
    const { latest } = await pressRun();
    act(() => {
      latest().emit("done", succeeded({ delivered: false, failure_reason: "day_count_mismatch", plan: null }));
    });

    expect(panel().getByRole("heading", { name: "No plan was delivered" })).toBeTruthy();
    expect(panel().getByText("Reason: day_count_mismatch")).toBeTruthy();
    expect(panel().queryAllByRole("article")).toHaveLength(0);
  });

  it("closes the stream when the page goes away", async () => {
    stubApi(accepted);
    const { latest, view } = await pressRun();

    view.unmount();

    expect(latest().closed).toBe(true);
  });
});

describe("Run status rules", () => {
  async function startError(post: Respond) {
    stubApi(post);
    await pressRun();
    return within(await panel().findByRole("alert"));
  }

  it("409 with an active run: the model is busy, naming the run", async () => {
    const alert = await startError(() =>
      Response.json({ detail: "run r-active is in progress", active_run_id: "r-active" }, { status: 409 }),
    );

    expect(alert.getByRole("heading", { name: "The model is busy" })).toBeTruthy();
    expect(alert.getByText("r-active")).toBeTruthy();
  });

  it("409 without an active run: the model is busy, naming none", async () => {
    const alert = await startError(() =>
      Response.json({ detail: "the model lock is held", active_run_id: null }, { status: 409 }),
    );

    expect(alert.getByRole("heading", { name: "The model is busy" })).toBeTruthy();
    expect(alert.queryByText(/Active run/)).toBeNull();
  });

  it("503: the API's message", async () => {
    const detail = "the run cannot start: FakeModeRealDataError: set TRIPARTITE_DATA_DIR";
    const alert = await startError(() => Response.json({ detail }, { status: 503 }));

    expect(alert.getByRole("heading", { name: "The run can’t start" })).toBeTruthy();
    expect(alert.getByText(detail)).toBeTruthy();
  });

  it("404: not found", async () => {
    const alert = await startError(() => Response.json({ detail: "val-001" }, { status: 404 }));

    expect(alert.getByRole("heading", { name: "Not found" })).toBeTruthy();
  });

  it.each([
    ["502", () => new Response("", { status: 502 })],
    ["504", () => new Response("", { status: 504 })],
    ["a network failure", () => Promise.reject(new TypeError("Failed to fetch"))],
  ])("%s: the API is unreachable", async (_name, post) => {
    const alert = await startError(post);

    expect(alert.getByRole("heading", { name: "Can’t reach the API" })).toBeTruthy();
  });

  it("anything else: a generic error with its status", async () => {
    const alert = await startError(() => Response.json({ detail: "boom" }, { status: 500 }));

    expect(alert.getByRole("heading", { name: "The API returned an error" })).toBeTruthy();
    expect(alert.getByText("HTTP status 500")).toBeTruthy();
    expect(document.body.textContent).not.toContain("boom");
  });

  it("a 409 leaves the run being followed on the page, still live", async () => {
    let first = true;
    stubApi(() => {
      if (first) {
        first = false;
        return accepted();
      }
      return Response.json({ detail: "busy", active_run_id: RUN_ID }, { status: 409 });
    });
    const { latest } = await pressRun();
    const source = latest();
    act(() => {
      source.emit("snapshot", run());
    });

    fireEvent.click(runButton());

    const alert = within(await panel().findByRole("alert"));
    expect(alert.getByRole("heading", { name: "The model is busy" })).toBeTruthy();
    expect(source.closed).toBe(false);

    act(() => {
      source.emit("done", succeeded());
    });
    expect(panel().getAllByRole("article")).toHaveLength(2);
  });
});

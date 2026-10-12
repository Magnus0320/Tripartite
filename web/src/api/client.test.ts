import { describe, expect, it, vi } from "vitest";

import { ApiError, fetchQueries, fetchRun, startRun } from "./client";

function stubFetch(response: Response | Error) {
  const fetchMock = vi.fn<typeof fetch>(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function failure(call: Promise<unknown> = fetchQueries()): Promise<ApiError> {
  const error: unknown = await call.then(
    () => new Error("the call resolved"),
    (reason: unknown) => reason,
  );
  if (!(error instanceof ApiError)) {
    throw new Error(`expected an ApiError, got ${String(error)}`);
  }
  return error;
}

describe("fetchQueries", () => {
  it("returns the items of a 200 from /api/queries", async () => {
    const items = [{ query_id: "val-001", query: "A trip." }];
    const fetchMock = stubFetch(Response.json({ items }));

    await expect(fetchQueries()).resolves.toEqual(items);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/queries");
  });

  it("maps a 503 ErrorDetail to data_unavailable and keeps the detail", async () => {
    stubFetch(Response.json({ detail: "no data at /srv/data" }, { status: 503 }));

    const error = await failure();
    expect(error.kind).toBe("data_unavailable");
    expect(error.detail).toBe("no data at /srv/data");
  });

  it("maps a 503 without a JSON body to data_unavailable with no detail", async () => {
    stubFetch(new Response("<html>Service Unavailable</html>", { status: 503 }));

    const error = await failure();
    expect(error.kind).toBe("data_unavailable");
    expect(error.detail).toBeNull();
  });

  it("maps any other status to http with that status, and drops the body", async () => {
    stubFetch(Response.json({ detail: "boom" }, { status: 500 }));

    const error = await failure();
    expect(error.kind).toBe("http");
    expect(error.status).toBe(500);
    expect(error.detail).toBeNull();
  });

  it("maps a rejected fetch to unreachable", async () => {
    stubFetch(new TypeError("Failed to fetch"));

    const error = await failure();
    expect(error.kind).toBe("unreachable");
    expect(error.status).toBeNull();
  });

  it("maps a 200 with the wrong shape to bad_response", async () => {
    stubFetch(Response.json({ items: [{ query_id: "val-001" }] }));

    expect((await failure()).kind).toBe("bad_response");
  });
});

describe("startRun", () => {
  it("posts the query_id with seed 0 and returns the 202 body", async () => {
    const accepted = { run_id: "20261012T100000Z-single-abcd1234-0001", status: "queued" };
    const fetchMock = stubFetch(Response.json(accepted, { status: 202 }));

    await expect(startRun("val-001")).resolves.toEqual(accepted);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/runs");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ query_id: "val-001", seed: 0 });
  });

  it("maps a 409 to busy with the active run id", async () => {
    stubFetch(Response.json({ detail: "run r1 is in progress", active_run_id: "r1" }, { status: 409 }));

    const error = await failure(startRun("val-001"));
    expect(error.kind).toBe("busy");
    expect(error.activeRunId).toBe("r1");
  });

  it("maps a 409 whose active_run_id is null to busy without one", async () => {
    stubFetch(Response.json({ detail: "the lock is held", active_run_id: null }, { status: 409 }));

    const error = await failure(startRun("val-001"));
    expect(error.kind).toBe("busy");
    expect(error.activeRunId).toBeNull();
  });

  it.each([
    [502, "unreachable"],
    [504, "unreachable"],
    [503, "data_unavailable"],
    [404, "not_found"],
    [422, "http"],
    [500, "http"],
    [200, "http"],
  ])("maps a %i to %s", async (status, kind) => {
    stubFetch(Response.json({ detail: "why" }, { status }));

    const error = await failure(startRun("val-001"));
    expect(error.kind).toBe(kind);
    expect(error.status).toBe(status);
    expect(error.detail).toBe(status === 503 ? "why" : null);
  });

  it("maps a 202 with the wrong shape to bad_response", async () => {
    stubFetch(Response.json({ status: "queued" }, { status: 202 }));

    expect((await failure(startRun("val-001"))).kind).toBe("bad_response");
  });
});

describe("fetchRun", () => {
  it("gets the run by its escaped id", async () => {
    const detail = { run_id: "a/b", status: "running", stage: "generating", error: null, item: null };
    const fetchMock = stubFetch(Response.json(detail));

    await expect(fetchRun("a/b")).resolves.toEqual(detail);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/runs/a%2Fb");
  });

  it("maps a 404 to not_found and an unknown status value to bad_response", async () => {
    stubFetch(Response.json({ detail: "unknown run" }, { status: 404 }));
    expect((await failure(fetchRun("r1"))).kind).toBe("not_found");

    stubFetch(Response.json({ run_id: "r1", status: "paused", stage: null, error: null, item: null }));
    expect((await failure(fetchRun("r1"))).kind).toBe("bad_response");
  });
});

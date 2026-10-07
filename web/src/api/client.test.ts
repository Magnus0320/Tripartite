import { describe, expect, it, vi } from "vitest";

import { ApiError, fetchQueries } from "./client";

function stubFetch(response: Response | Error) {
  const fetchMock = vi.fn<typeof fetch>(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function failure(): Promise<ApiError> {
  const error: unknown = await fetchQueries().then(
    () => new Error("fetchQueries resolved"),
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

  it("maps a rejected fetch to network", async () => {
    stubFetch(new TypeError("Failed to fetch"));

    expect((await failure()).kind).toBe("network");
  });

  it("maps a 200 with the wrong shape to bad_response", async () => {
    stubFetch(Response.json({ items: [{ query_id: "val-001" }] }));

    expect((await failure()).kind).toBe("bad_response");
  });
});

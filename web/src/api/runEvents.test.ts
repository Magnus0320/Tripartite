import { describe, expect, it, vi } from "vitest";

import { stubEventSource } from "../test/fakeEventSource";
import { followRun, type RunEventHandlers } from "./runEvents";

const detail = { run_id: "r1", status: "running", stage: "generating", error: null, item: null };

function follow() {
  const latest = stubEventSource();
  const handlers = {
    onSnapshot: vi.fn(),
    onStage: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
    onStreamFailed: vi.fn(),
  } satisfies RunEventHandlers;
  const stop = followRun("r1", handlers);
  return { source: latest(), handlers, stop };
}

describe("followRun", () => {
  it("opens the run's event stream and passes on snapshot, stage and done", () => {
    const { source, handlers } = follow();
    expect(source.url).toBe("/api/runs/r1/events");

    source.emit("snapshot", detail);
    source.emit("stage", { stage: "evaluating" });
    expect(handlers.onSnapshot).toHaveBeenCalledWith(detail);
    expect(handlers.onStage).toHaveBeenCalledWith("evaluating");
    expect(source.closed).toBe(false);

    const done = { ...detail, status: "succeeded", stage: "done" };
    source.emit("done", done);
    expect(handlers.onDone).toHaveBeenCalledWith(done);
    expect(source.closed).toBe(true);
    expect(handlers.onStreamFailed).not.toHaveBeenCalled();
  });

  it("tells the server's error event from a connection failure", () => {
    const first = follow();
    first.source.emit("error", { message: "LLMError: no answer" });
    expect(first.handlers.onError).toHaveBeenCalledWith({ message: "LLMError: no answer" });
    expect(first.handlers.onStreamFailed).not.toHaveBeenCalled();
    expect(first.source.closed).toBe(true);

    const second = follow();
    second.source.fail();
    expect(second.handlers.onStreamFailed).toHaveBeenCalledOnce();
    expect(second.handlers.onError).not.toHaveBeenCalled();
    expect(second.source.closed).toBe(true);
  });

  it.each([
    ["snapshot", "not json"],
    ["stage", JSON.stringify({ stage: "napping" })],
    ["done", JSON.stringify({ run_id: "r1" })],
  ])("treats an unreadable %s as a stream failure, once", (type, data) => {
    const { source, handlers } = follow();

    source.emitRaw(type, data);
    source.fail();

    expect(handlers.onStreamFailed).toHaveBeenCalledOnce();
    expect(source.closed).toBe(true);
  });

  it("ignores everything after it is stopped", () => {
    const { source, handlers, stop } = follow();

    stop();
    source.emit("snapshot", detail);
    source.fail();

    expect(source.closed).toBe(true);
    expect(handlers.onSnapshot).not.toHaveBeenCalled();
    expect(handlers.onStreamFailed).not.toHaveBeenCalled();
  });
});

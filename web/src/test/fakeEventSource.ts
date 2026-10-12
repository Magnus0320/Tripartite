import { vi } from "vitest";

/** A stand-in for the browser's EventSource: tests send its events by hand. */
export class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  closed = false;

  constructor(url: string) {
    super();
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  /** A named server-sent event with JSON data. */
  emit(type: string, data: unknown) {
    this.emitRaw(type, JSON.stringify(data));
  }

  emitRaw(type: string, data: string) {
    this.dispatchEvent(new MessageEvent(type, { data }));
  }

  /** A connection failure: a plain `error` event without data. */
  fail() {
    this.dispatchEvent(new Event("error"));
  }
}

/** Replaces the global EventSource; returns a function giving the most recent source. */
export function stubEventSource(): () => FakeEventSource {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  return () => {
    const source = FakeEventSource.instances.at(-1);
    if (source === undefined) {
      throw new Error("no EventSource was opened");
    }
    return source;
  };
}

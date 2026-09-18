import type { TokenomicsEvent } from "./types.js";

export interface Sink { emit(event: TokenomicsEvent): void | Promise<void> }

export class MemorySink implements Sink {
  readonly events: TokenomicsEvent[] = [];
  emit(event: TokenomicsEvent): void { this.events.push(event); }
}

export class MultiSink implements Sink {
  constructor(readonly sinks: readonly Sink[]) {}
  async emit(event: TokenomicsEvent): Promise<void> {
    for (const sink of this.sinks) await sink.emit(event);
  }
}

export class Recorder {
  constructor(readonly sink: Sink) {}
  async record(event: TokenomicsEvent): Promise<TokenomicsEvent> {
    await this.sink.emit(event);
    return event;
  }
}

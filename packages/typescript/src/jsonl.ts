import { appendFile } from "node:fs/promises";
import { dirname } from "node:path";
import { mkdir } from "node:fs/promises";
import type { Sink } from "./recorder.js";
import type { TokenomicsEvent } from "./types.js";

export class JsonlSink implements Sink {
  constructor(readonly path: string) {}
  async emit(event: TokenomicsEvent): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    await appendFile(this.path, `${JSON.stringify(event)}\n`, { encoding: "utf8", mode: 0o600 });
  }
}

export function newTraceId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

export function newSpanId(): string {
  const bytes = new Uint8Array(8);
  do {
    crypto.getRandomValues(bytes);
  } while (bytes.every(v => v === 0));
  return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
}

export function newEventId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

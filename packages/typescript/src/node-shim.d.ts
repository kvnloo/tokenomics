declare module "node:crypto" {
  export function createHash(algorithm: string): {
    update(data: string): { digest(encoding: "hex"): string };
    digest(encoding: "hex"): string;
  };
}
declare module "node:fs/promises" {
  export function appendFile(path: string, data: string, options?: unknown): Promise<void>;
  export function mkdir(path: string, options?: unknown): Promise<void>;
  export function readFile(path: string, options?: unknown): Promise<string>;
}
declare module "node:path" {
  export function dirname(path: string): string;
}
declare module "node:assert/strict" {
  const assert: {
    equal(actual: unknown, expected: unknown): void;
    match(actual: string, expected: RegExp): void;
  };
  export default assert;
}
declare module "node:test" {
  export function test(name: string, fn: () => void | Promise<void>): void;
}

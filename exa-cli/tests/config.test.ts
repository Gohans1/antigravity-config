import { describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defaultConfigPath, effectiveKeys, loadConfig } from "../src/config";

const KEY_1 = "11111111-aaaa-4bbb-8ccc-000000000001";
const KEY_2 = "22222222-aaaa-4bbb-8ccc-000000000002";
const KEY_3 = "33333333-aaaa-4bbb-8ccc-000000000003";

function withConfigFile(contents: unknown, run: (path: string) => void) {
  const dir = mkdtempSync(join(tmpdir(), "exa-cfg-"));
  try {
    const path = join(dir, "config.json");
    writeFileSync(path, JSON.stringify(contents));
    run(path);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

describe("defaultConfigPath", () => {
  test("prefers EXA_CONFIG_PATH", () => {
    expect(defaultConfigPath({ EXA_CONFIG_PATH: "/custom/exa.json" }, "/home/u")).toBe(
      "/custom/exa.json",
    );
  });

  test("uses XDG_CONFIG_HOME, then ~/.config", () => {
    expect(defaultConfigPath({ XDG_CONFIG_HOME: "/xdg" }, "/home/u")).toBe("/xdg/exa/config.json");
    expect(defaultConfigPath({}, "/home/u")).toBe("/home/u/.config/exa/config.json");
  });
});

describe("loadConfig", () => {
  test("returns {} when the file does not exist", () => {
    expect(loadConfig("/nonexistent/exa/config.json")).toEqual({});
  });

  test("keeps keys in file order", () => {
    withConfigFile(
      { keys: [{ label: "primary", value: KEY_1 }, { label: "backup", value: KEY_2 }] },
      (path) => {
        expect(loadConfig(path).keys).toEqual([
          { label: "primary", value: KEY_1 },
          { label: "backup", value: KEY_2 },
        ]);
      },
    );
  });

  test("rejects duplicate keys", () => {
    withConfigFile(
      { keys: [{ label: "a", value: KEY_1 }, { label: "b", value: KEY_1 }] },
      (path) => expect(() => loadConfig(path)).toThrow(/invalid exa configuration/i),
    );
  });

  test("rejects values that are not Exa keys", () => {
    withConfigFile({ keys: [{ label: "bad", value: "tvly-not-an-exa-key" }] }, (path) =>
      expect(() => loadConfig(path)).toThrow(/invalid exa configuration/i),
    );
  });

  test("rejects empty labels and labels that contain a key", () => {
    withConfigFile({ keys: [{ label: "", value: KEY_1 }] }, (path) =>
      expect(() => loadConfig(path)).toThrow(/invalid exa configuration/i),
    );
    withConfigFile({ keys: [{ label: `backup ${KEY_2}`, value: KEY_2 }] }, (path) =>
      expect(() => loadConfig(path)).toThrow(/invalid exa configuration/i),
    );
  });

  test("rejects symlinked config files", () => {
    const dir = mkdtempSync(join(tmpdir(), "exa-sym-"));
    try {
      const target = join(dir, "real.json");
      const link = join(dir, "link.json");
      writeFileSync(target, "{}");
      symlinkSync(target, link);
      expect(() => loadConfig(link)).toThrow(/symlink/i);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("effectiveKeys", () => {
  test("falls back to EXA_API_KEYS, then EXA_API_KEY, when the config has no keys", () => {
    expect(effectiveKeys({}, { EXA_API_KEYS: ` ${KEY_1} , ${KEY_2} ` })).toEqual([KEY_1, KEY_2]);
    expect(effectiveKeys({}, { EXA_API_KEY: KEY_3 })).toEqual([KEY_3]);
    expect(effectiveKeys({}, {})).toEqual([]);
  });

  test("ignores the environment when the config defines keys", () => {
    const env = { EXA_API_KEYS: KEY_1 };
    expect(effectiveKeys({ keys: [{ label: "only", value: KEY_3 }] }, env)).toEqual([KEY_3]);
  });
});

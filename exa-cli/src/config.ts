import { lstatSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export interface KeyEntry {
  label: string;
  value: string;
}

export interface Config {
  keys?: KeyEntry[];
}

const KEY_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

const validKey = (value: unknown): value is string =>
  typeof value === "string" && new RegExp(`^${KEY_PATTERN.source}$`, "i").test(value);

const validLabel = (value: unknown): value is string =>
  typeof value === "string" &&
  value.trim().length > 0 &&
  value.length <= 80 &&
  !/[\x00-\x1f\x7f-\x9f]/.test(value) &&
  !KEY_PATTERN.test(value);

const INVALID = "Invalid Exa configuration. Check labeled API keys.";

export function defaultConfigPath(
  env: Record<string, string | undefined> = process.env,
  home?: string,
): string {
  if (env.EXA_CONFIG_PATH?.trim()) return env.EXA_CONFIG_PATH.trim();
  const base = env.XDG_CONFIG_HOME?.trim() || join(home ?? homedir(), ".config");
  const userPath = join(base, "exa", "config.json");
  if (home === undefined && !env.XDG_CONFIG_HOME?.trim() && !checkFile(userPath)) {
    const bundled = join(import.meta.dir, "..", "config.json");
    if (checkFile(bundled)) return bundled;
  }
  return userPath;
}

function checkFile(path: string): boolean {
  try {
    if (!lstatSync(path).isFile()) {
      throw new Error("Exa configuration must be a regular file, not a symlink.");
    }
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

function validate(raw: unknown): Config {
  const c = raw as Record<string, unknown> | null;
  if (!c || typeof c !== "object" || Array.isArray(c)) throw new Error(INVALID);
  if (c.keys === undefined) return {};
  const keys = c.keys as KeyEntry[];
  if (
    !Array.isArray(keys) ||
    keys.some((k) => !k || typeof k !== "object" || !validLabel(k.label) || !validKey(k.value)) ||
    new Set(keys.map((k) => k.value)).size !== keys.length
  ) {
    throw new Error(INVALID);
  }
  return { keys: keys.map((k) => ({ label: k.label, value: k.value })) };
}

export function loadConfig(path: string): Config {
  if (!checkFile(path)) return {};
  let raw: unknown;
  try {
    raw = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new Error("Invalid Exa configuration. Cannot read settings JSON.");
  }
  return validate(raw);
}

export function effectiveKeys(config: Config, env: Record<string, string | undefined>): string[] {
  if (config.keys !== undefined) return config.keys.map((k) => k.value);
  const list = env.EXA_API_KEYS ?? env.EXA_API_KEY;
  if (!list) return [];
  return list
    .split(",")
    .map((key) => key.trim())
    .filter(Boolean);
}

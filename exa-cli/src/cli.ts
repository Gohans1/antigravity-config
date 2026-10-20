import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { defaultConfigPath, effectiveKeys, loadConfig, type Config } from "./config";
import {
  callWithFailover,
  type ContentsResultItem,
  type ContentsStatus,
  DEFAULT_BASE_URL,
  fetchDirectMarkdown,
  fetchedNothing,
  formatContents,
  formatSearchSections,
  FULL_HIGHLIGHT_RESULTS,
  SEPARATOR,
} from "./core";

export interface CliRuntime {
  env?: Record<string, string | undefined>;
  fetchImpl?: (url: string, init?: RequestInit) => Promise<Response>;
  out?: (msg: string) => void;
  err?: (msg: string) => void;
}

const DEFAULT_MAX_OUTPUT = 26000;
const DEFAULT_MAX_RESULTS = 10;
const SEARCH_TYPES = ["auto", "fast", "instant"];

const HELP = `Usage: exa <command> [options]

Commands:
  search <query>            Web search; each result includes the passages most relevant to the query
      -n <${FULL_HIGHLIGHT_RESULTS}-${DEFAULT_MAX_RESULTS}>                 How many results include highlights (default: ${FULL_HIGHLIGHT_RESULTS}; all ${DEFAULT_MAX_RESULTS} titles + URLs are always shown)
      --include-domains <d1,d2>   --exclude-domains <d1,d2>
  fetch <url...>            Full page as markdown
  status                    Show configured keys and config path

Global options:
  --json                    Raw API response; never truncated, fails with a hint past ${DEFAULT_MAX_OUTPUT} chars
  -o, --output <file>       Save full output to <file>, print a one-line summary

Defaults: type=fast (~0.5s), ${DEFAULT_MAX_RESULTS} results (first ${FULL_HIGHLIGHT_RESULTS} with highlights, rest title + URL; use -n ${FULL_HIGHLIGHT_RESULTS}-${DEFAULT_MAX_RESULTS} to adjust highlights).
Highlights are excerpts that can cut text mid-word with " ... "; run 'exa fetch <url>' before copying code or exact wording.
For a large page past the ${DEFAULT_MAX_OUTPUT}-char fetch cap, save it with -o <file> and grep the file.
Describe the page you want instead of listing keywords.

Examples:
  exa search "Hono JWT middleware reading the token from a cookie"
  exa search "Durable Objects alarm retries" --include-domains developers.cloudflare.com
  exa fetch https://hono.dev/docs/middleware/builtin/jwt https://github.com/honojs/hono/blob/main/src/middleware/jwt/jwt.ts
  exa fetch https://hono.dev/docs/middleware/builtin/jwt -o /tmp/hono-jwt.md`;

function formatStatus(config: Config, env: Record<string, string | undefined>, configPath: string, asJson: boolean) {
  const keys = effectiveKeys(config, env);
  const source = config.keys === undefined ? "environment" : "saved";
  const labels = config.keys?.map((k) => k.label) ?? [];
  if (asJson) return JSON.stringify({ keyCount: keys.length, source, configPath, labels }, null, 2);
  return [
    `Exa CLI: ${keys.length} key(s) (${source}) [${configPath}]`,
    ...labels.map((label, i) => `  ${i + 1}. ${label}`),
  ].join("\n");
}

function readFlagValue(tokens: string[], index: number, flagName: string): string {
  const val = tokens[index];
  if (!val || val.startsWith("-")) throw new Error(`Missing value for ${flagName}`);
  return val;
}

const splitList = (val: string) =>
  val
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

// Exa shortens long excerpts by cutting words out mid-line and leaving " ... ".
const ELIDED = /[^\s.] \.\.\. [^\s.]/;
const ELISION_NOTE = "Note: some excerpts elide text with \" ... \"; run 'exa fetch <url>' for exact code or wording.";

interface OutputOptions {
  maxOutput: number;
  outputFile?: string;
  json?: boolean;
  sections?: string[];
}

// How many leading results fit whole inside the cap.
function wholeResultsWithin(sections: string[], maxOutput: number): number {
  let used = 0;
  for (const [i, section] of sections.entries()) {
    used += (i ? SEPARATOR.length : 0) + section.length;
    if (used > maxOutput) return i;
  }
  return sections.length;
}

const sectionHeading = (s: string) =>
  s
    .split("\n", 2)
    .filter((l, i) => i === 0 || l.startsWith("URL: "))
    .join("\n");

function finalizeOutput(text: string, { maxOutput, outputFile, json, sections }: OutputOptions): string {
  if (outputFile) {
    mkdirSync(dirname(outputFile), { recursive: true });
    writeFileSync(outputFile, text, "utf8");
    const lineCount = text.length === 0 ? 0 : text.split("\n").length;
    return `Saved ${text.length} chars (${lineCount} lines) to ${outputFile}`;
  }
  if (text.length <= maxOutput) return text;
  // Cutting JSON would hand a parser invalid JSON, so refuse on stderr instead.
  if (json) throw new Error(`JSON output is ${text.length} chars (cap ${maxOutput}); use -o <file> to save all.`);
  if (sections && sections.length > 1) {
    const total = sections.length;
    const whole = wholeResultsWithin(sections, maxOutput);
    if (whole < total) {
      const before = sections.slice(0, whole).join(SEPARATOR);
      const head = sectionHeading(sections[whole]!);
      const hiddenUrls = sections.slice(whole).map(sectionHeading).join("\n");
      const tail = hiddenUrls ? `\n${hiddenUrls}` : "";
      if (whole > 0 && maxOutput <= before.length + SEPARATOR.length + head.length + 1) {
        const hidden = `${total - whole} hidden by the ${maxOutput}-char cap`;
        return `${before}\n... [truncated: showing ${whole} of ${total} results, ${before.length} of ${text.length} chars (${hidden}); use -o <file> to save all]${tail}`;
      }
      const moreHidden = total - whole - 1;
      const cut = `cut inside result ${whole + 1} of ${total}${moreHidden > 0 ? ` (${moreHidden} more hidden)` : ""}`;
      return `${text.slice(0, maxOutput)}\n... [truncated: showing ${maxOutput} of ${text.length} chars, ${cut}; use -o <file> to save all]${tail}`;
    }
  }
  return `${text.slice(0, maxOutput)}\n... [truncated: showing ${maxOutput} of ${text.length} chars; use -o <file> to save all]`;
}

export async function runCli(rawArgv: string[], runtime: CliRuntime = {}): Promise<number> {
  const env = runtime.env ?? process.env;
  const out = runtime.out ?? ((msg: string) => console.log(msg));
  const err = runtime.err ?? ((msg: string) => console.error(msg));
  const fetchImpl = runtime.fetchImpl ?? fetch;
  const configPath = defaultConfigPath(env);

  try {
    let asJson = false;
    let maxOutput: number | undefined;
    let outputFile: string | undefined;
    const argv: string[] = [];
    for (let i = 0; i < rawArgv.length; i++) {
      const token = rawArgv[i]!;
      if (token === "--json") {
        asJson = true;
      } else if (token === "--max-output") {
        maxOutput = Number(readFlagValue(rawArgv, ++i, token));
        if (!Number.isInteger(maxOutput) || maxOutput < 1) {
          throw new Error("--max-output must be a positive integer");
        }
      } else if (token === "-o" || token === "--output") {
        outputFile = readFlagValue(rawArgv, ++i, token);
      } else {
        argv.push(token);
      }
    }

    if (argv.length === 0 || argv.includes("-h") || argv.includes("--help") || argv[0] === "help") {
      out(HELP);
      return 0;
    }

    const cmd = argv[0]!;
    if (cmd === "status") {
      if (argv.length > 1) throw new Error(`Unknown option '${argv[1]}'. Run 'exa --help' for usage.`);
      out(formatStatus(loadConfig(configPath), env, configPath, asJson));
      return 0;
    }

    const loadKeys = () => effectiveKeys(loadConfig(configPath), env);

    if (cmd === "fetch") {
      const urls = argv.slice(1);
      const option = urls.find((u) => u.startsWith("-"));
      if (option) throw new Error(`Unknown option '${option}'. Run 'exa --help' for usage.`);
      if (urls.length === 0) throw new Error("Usage: exa fetch <url...>. Run 'exa --help' for options.");

      if (asJson) {
        const body = await callWithFailover(`${DEFAULT_BASE_URL}/contents`, { urls, text: true }, loadKeys(), fetchImpl);
        out(finalizeOutput(body, { maxOutput: maxOutput ?? DEFAULT_MAX_OUTPUT, outputFile, json: true }));
        return fetchedNothing(body) ? 1 : 0;
      }

      const direct = await Promise.all(urls.map((u) => fetchDirectMarkdown(u, fetchImpl)));
      const remaining = urls.filter((_, i) => !direct[i]);
      const parsed: { results?: ContentsResultItem[]; statuses?: ContentsStatus[] } = remaining.length
        ? JSON.parse(
            await callWithFailover(`${DEFAULT_BASE_URL}/contents`, { urls: remaining, text: true }, loadKeys(), fetchImpl),
          )
        : {};
      const byUrl = new Map((parsed.results ?? []).map((r) => [r.url, r]));
      const results = urls
        .flatMap((u, i) => {
          const item = direct[i] ?? byUrl.get(u);
          byUrl.delete(u);
          return item ? [item] : [];
        })
        .concat([...byUrl.values()]);
      const { text, sections } = formatContents(results, parsed.statuses);
      out(finalizeOutput(text, { maxOutput: maxOutput ?? DEFAULT_MAX_OUTPUT, outputFile, sections }));
      return results.length === 0 ? 1 : 0;
    }

    if (cmd !== "search") {
      throw new Error(`Unknown command '${cmd}'. Commands: search, fetch, status. Run 'exa --help' for usage.`);
    }

    const tokens = argv.slice(1);
    const queryParts: string[] = [];
    const includeDomains: string[] = [];
    const excludeDomains: string[] = [];
    let type = "fast";
    let highlightResults = FULL_HIGHLIGHT_RESULTS;
    for (let i = 0; i < tokens.length; i++) {
      const arg = tokens[i]!;
      if (arg === "-n" || arg === "--max-results" || arg === "--num-results") {
        highlightResults = Number(readFlagValue(tokens, ++i, "-n"));
        if (
          !Number.isInteger(highlightResults) ||
          highlightResults < FULL_HIGHLIGHT_RESULTS ||
          highlightResults > DEFAULT_MAX_RESULTS
        ) {
          throw new Error(`-n must be an integer between ${FULL_HIGHLIGHT_RESULTS} and ${DEFAULT_MAX_RESULTS}`);
        }
      } else if (arg === "-t" || arg === "--type") {
        type = readFlagValue(tokens, ++i, "--type");
        if (!SEARCH_TYPES.includes(type)) {
          throw new Error(`--type must be one of: ${SEARCH_TYPES.join(", ")}`);
        }
      } else if (arg === "--include-domains") {
        includeDomains.push(...splitList(readFlagValue(tokens, ++i, arg)));
      } else if (arg === "--exclude-domains") {
        excludeDomains.push(...splitList(readFlagValue(tokens, ++i, arg)));
      } else if (arg.startsWith("-")) {
        throw new Error(`Unknown option '${arg}'. Run 'exa --help' for usage.`);
      } else {
        queryParts.push(arg);
      }
    }

    const query = queryParts.join(" ").trim();
    if (!query) throw new Error("Usage: exa search <query> [options]. Run 'exa --help' for options.");

    const payload: Record<string, unknown> = {
      query,
      type,
      numResults: DEFAULT_MAX_RESULTS,
      contents: { highlights: true },
    };
    if (includeDomains.length) payload.includeDomains = includeDomains;
    if (excludeDomains.length) payload.excludeDomains = excludeDomains;

    const body = await callWithFailover(`${DEFAULT_BASE_URL}/search`, payload, loadKeys(), fetchImpl);
    if (asJson) {
      out(finalizeOutput(body, { maxOutput: maxOutput ?? DEFAULT_MAX_OUTPUT, outputFile, json: true }));
      return 0;
    }
    const filtered = includeDomains.length > 0 || excludeDomains.length > 0;
    const sections = formatSearchSections(
      body,
      `Describe the page you want instead of listing keywords${filtered ? ", or drop --include-domains/--exclude-domains" : ""}.`,
      highlightResults,
    );
    const text = sections.join(SEPARATOR);
    const shown = finalizeOutput(text, { maxOutput: maxOutput ?? Infinity, outputFile, sections });
    out(ELIDED.test(text) ? `${shown}\n${ELISION_NOTE}` : shown);
    return 0;
  } catch (error) {
    err(error instanceof Error ? error.message : String(error));
    return 1;
  }
}

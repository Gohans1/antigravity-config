import { Defuddle } from "defuddle/node";
import { parseHTML } from "linkedom";

export const DEFAULT_BASE_URL = "https://api.exa.ai";

export interface SearchResultItem {
  title?: string | null;
  url?: string;
  publishedDate?: string | null;
  highlights?: string[];
}

export interface ContentsResultItem {
  title?: string | null;
  url?: string;
  text?: string;
}

export interface ContentsStatus {
  id?: string;
  status?: string;
  error?: { tag?: string; httpStatusCode?: number | null } | null;
}

// Failures tied to one key, so the next key may still work. Any other error would repeat on every key.
const RETRYABLE: Record<number, string> = { 401: "invalid key", 402: "out of credits", 429: "rate limited" };

const redact = (text: string, keys: string[]) =>
  keys.reduce((out, key) => (key ? out.replaceAll(key, "[REDACTED]") : out), text);

async function parseErrorMessage(response: Response): Promise<string | undefined> {
  try {
    const raw = (await response.json()) as { error?: unknown };
    return typeof raw.error === "string" ? raw.error : undefined;
  } catch {
    return undefined;
  }
}

export async function callWithFailover(
  url: string,
  body: Record<string, unknown>,
  keys: string[],
  fetchImpl: (url: string, init?: RequestInit) => Promise<Response> = fetch,
): Promise<string> {
  if (keys.length === 0) {
    throw new Error(
      "Exa: no API key configured. Add keys to the config file shown by 'exa status', or set EXA_API_KEYS / EXA_API_KEY.",
    );
  }

  const bodyStr = JSON.stringify(body);
  const failures: string[] = [];

  for (const [index, key] of keys.entries()) {
    let response: Response;
    try {
      response = await fetchImpl(url, {
        method: "POST",
        headers: { "x-api-key": key, "Content-Type": "application/json" },
        body: bodyStr,
      });
    } catch {
      throw new Error("Exa: network request failed.");
    }

    if (response.ok) {
      let text: string;
      try {
        text = await response.text();
      } catch {
        throw new Error("Exa: response could not be read.");
      }
      return redact(text, keys);
    }

    if (!RETRYABLE[response.status]) {
      const message = await parseErrorMessage(response);
      const fallback =
        response.status === 503 ? "temporarily unavailable, try again." : "request failed.";
      throw new Error(`Exa ${response.status}: ${redact(message ?? fallback, keys)}`);
    }
    failures.push(`key #${index + 1} -> ${response.status} ${RETRYABLE[response.status]}`);
  }

  throw new Error(`Exa: every key failed (${failures.join(", ")}).`);
}

export const SEPARATOR = "\n\n---\n\n";

const heading = (idx: number, item: { title?: string | null; url?: string }, chars?: number) => [
  `${idx + 1}. ${item.title?.trim() || item.url || "Untitled"}`,
  ...(item.url ? [`URL: ${item.url}${chars === undefined ? "" : ` (${chars} chars)`}`] : []),
];

export const FULL_HIGHLIGHT_RESULTS = 5;

// One string per result, so a size cap can cut between results instead of inside one.
export function formatSearchSections(
  body: string,
  emptyHint = "",
  highlightResults = FULL_HIGHLIGHT_RESULTS,
): string[] {
  let parsed: { results?: SearchResultItem[] };
  try {
    parsed = JSON.parse(body);
  } catch {
    return [body];
  }

  const results = parsed.results ?? [];
  if (results.length === 0) return [emptyHint ? `No results found. ${emptyHint}` : "No results found."];

  return results.map((item, idx) => {
    const lines = heading(idx, item);
    if (idx < highlightResults) {
      if (item.publishedDate) lines.push(`Published: ${item.publishedDate.slice(0, 10)}`);
      const highlights = (item.highlights ?? []).map((h) => h.trim()).filter(Boolean);
      if (highlights.length) lines.push(highlights.join("\n...\n"));
    }
    return lines.join("\n");
  });
}

const PROSE_LANG_CLASSES = ["markdown", "md", "js", "c", "cs", "sh", "shell", "html", "xml", "markup", "atom"];
const CODE_LANG_RE = /(?:^|\s)(?:language-|lang-|highlight-source-|mw-highlight-lang-|highlight-|type-)([\w+-]+)/i;
const normLang = (raw: string) => raw.toLowerCase().replace(/^python3$/, "python");
let silenceDepth = 0;
let savedConsole: { error: typeof console.error; warn: typeof console.warn; log: typeof console.log } | undefined;

export async function fetchDirectMarkdown(
  url: string,
  fetchImpl: (url: string, init?: RequestInit) => Promise<Response> = fetch,
): Promise<ContentsResultItem | undefined> {
  try {
    const reqHost = new URL(url).hostname;
    const isGitHub = /(?:^|\.)github\.com$/i.test(reqHost);
    const isXStatus = (u: string) => /^https?:\/\/(?:www\.)?(?:x|twitter)\.com\/[^/]+\/(?:status|article)\/\d+/i.test(u);
    if (/(?:^|\.)(?:x|twitter)\.com$/i.test(reqHost) && !isXStatus(url)) return undefined;

    const headers: Record<string, string> = { Accept: "text/markdown, text/html;q=0.9" };
    if (isGitHub) headers["User-Agent"] = "Mozilla/5.0 (compatible; Defuddle/1.0; +https://defuddle.md) bot";

    const res = await fetchImpl(url, { headers });
    if (!res.ok) return undefined;
    const finalUrl = res.url || url;
    const isX = isXStatus(finalUrl);
    if (/(?:^|\.)(?:x|twitter)\.com$/i.test(new URL(finalUrl).hostname) && !isX) return undefined;

    const ct = res.headers.get("content-type") ?? "";
    const body = await res.text();

    if (/^text\/(markdown|plain)\b/i.test(ct) && !/^\s*<(?:!doctype\s+html|html)\b/i.test(body)) {
      const text = body.trim().replace(/^(`{3,}[\w-]+)\{[^}\n]+\}/gm, "$1");
      if (!text) return undefined;
      const fm = text.match(/^---\r?\n(?:[\s\S]*?\r?\n)?title:\s*["']?(.+?)["']?\r?\n[\s\S]*?---/);
      const h1 = text.match(/^#\s+(.+)$/m);
      return { url, title: (fm?.[1] ?? h1?.[1])?.trim() || url, text };
    }

    if (!/(?:text\/html|application\/xhtml\+xml)\b/i.test(ct) && !isX) return undefined;

    if (isGitHub && /\/blob\//i.test(finalUrl)) {
      for (const m of body.matchAll(/<script[^>]*data-target="react-app\.embeddedData"[^>]*>([\s\S]*?)<\/script>/gi)) {
        try {
          const payload = JSON.parse(m[1] ?? "").payload;
          const rawLines = payload?.["codeViewBlobLayoutRoute.StyledBlob"]?.rawLines ?? payload?.blob?.rawLines;
          if (Array.isArray(rawLines) && rawLines.length > 0) {
            const ext = new URL(finalUrl).pathname.split(".").pop()?.toLowerCase() ?? "";
            const t = body.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]?.replace(/\s*·\s*GitHub\s*$/i, "").trim();
            return { url, title: t || url, text: `\`\`\`${ext}\n${rawLines.join("\n")}\n\`\`\`` };
          }
        } catch {}
      }
    }

    const { document } = parseHTML(body || "<!DOCTYPE html><html><head></head><body></body></html>");
    const doc = document as unknown as Parameters<typeof Defuddle>[0] & {
      styleSheets?: unknown[];
      defaultView?: { getComputedStyle?: () => { display: string } };
      URL?: string;
      querySelectorAll: (s: string) => Iterable<any>;
      createTextNode: (t: string) => any;
    };
    doc.styleSheets ??= [];
    if (doc.defaultView) doc.defaultView.getComputedStyle ??= () => ({ display: "" });
    doc.URL = finalUrl;

    for (const el of doc.querySelectorAll("html, body, main, article, section, div")) {
      if (el.tagName === "DIV" && !el.querySelector("p, h1, h2, h3, article, section")) continue;
      for (const cls of PROSE_LANG_CLASSES) el.classList?.remove(cls);
    }
    for (const tbl of doc.querySelectorAll("table.highlighttable, table.t-dcl-begin")) {
      const pre = tbl.querySelector("td.code pre, pre");
      if (pre) tbl.replaceWith(pre);
    }
    for (const el of doc.querySelectorAll(
      ".sr-only, .hideme, #copy-path, h1 button, h2 button, h3 button, h4 button, h5 button, h6 button, a.anchor, a.heading-anchor, a.permalink, a.playground-link, .blob-num, .js-line-number, .lineno, .lnt, .linenos, [class*='codeLineNumber']:not(pre, code, [data-line], :has(pre, code)), [class*='line-number']:not(pre, code, [data-line], :has(pre, code)), .twoslash-popup-container, .hover-info, .hover-container",
    )) {
      el.remove();
    }
    for (const a of doc.querySelectorAll("h1 a[href^='#'], h2 a[href^='#'], h3 a[href^='#'], h4 a[href^='#'], h5 a[href^='#'], h6 a[href^='#']")) {
      if (/^[#¶§🔗\uFEFF]*$/.test(a.textContent?.trim() ?? "")) a.remove();
      else a.removeAttribute("href");
    }
    for (const code of doc.querySelectorAll("h1 code, h2 code, h3 code, h4 code, h5 code, h6 code")) {
      code.replaceWith(doc.createTextNode(`\uE000${code.textContent ?? ""}\uE001`));
    }
    for (const el of doc.querySelectorAll("[class*='alert--']")) {
      for (const c of Array.from<string>(el.classList ?? [])) {
        if (c.startsWith("alert--")) {
          el.classList.remove(c);
          el.classList.add(`alert-${c.slice(7)}`);
        }
      }
      for (const h of el.querySelectorAll("[class*='admonitionHeading']")) h.remove();
    }
    for (const el of doc.querySelectorAll(".ec-line, .token-line, .code-line, .cm-line, .js-file-line")) {
      el.setAttribute("data-line", "");
    }
    for (const el of doc.querySelectorAll(".mw-highlight[style*='float']")) {
      el.removeAttribute("style");
    }
    for (const el of doc.querySelectorAll("[data-tagsearch-lang], .blob-wrapper[class*='type-'], [class*='highlight-'], [class*='mw-highlight-lang-'], pre, code")) {
      const tagLang = el.getAttribute?.("data-tagsearch-lang") || el.getAttribute?.("class")?.match(CODE_LANG_RE)?.[1];
      if (tagLang) {
        const lang = normLang(tagLang);
        if (!el.getAttribute("data-lang")) el.setAttribute("data-lang", lang);
        for (const inner of el.querySelectorAll?.("pre, code, table.highlight") ?? []) {
          if (!inner.getAttribute("data-lang")) inner.setAttribute("data-lang", lang);
        }
      }
    }
    for (const pre of doc.querySelectorAll("pre")) {
      const langEl = pre.querySelector(".language-id");
      if (langEl) {
        const lang = langEl.textContent?.trim();
        if (lang && !pre.getAttribute("data-lang")) pre.setAttribute("data-lang", normLang(lang));
        langEl.remove();
      }
      for (const w of pre.querySelectorAll("div.where")) {
        w.textContent = `\n${w.textContent ?? ""}\n`;
      }
    }

    if (silenceDepth++ === 0) {
      savedConsole = { error: console.error, warn: console.warn, log: console.log };
      console.error = () => {};
      console.warn = () => {};
      console.log = () => {};
    }
    let parsed: Awaited<ReturnType<typeof Defuddle>>;
    try {
      parsed = await Defuddle(doc, finalUrl, {
        markdown: true,
        useAsync: isX,
        fetch: fetchImpl as typeof fetch,
      });
    } finally {
      if (--silenceDepth === 0 && savedConsole) {
        console.error = savedConsole.error;
        console.warn = savedConsole.warn;
        console.log = savedConsole.log;
        savedConsole = undefined;
      }
    }

    const text = parsed.content
      ?.replace(/\uE000([\s\S]*?)\uE001/g, (_, c: string) => `\`${c.replace(/\\([<>[\]*_`~\\])/g, "$1")}\``)
      .trim();
    if (!text || text.startsWith("Partial conversion completed with errors.")) return undefined;
    return { url, title: parsed.title?.trim() || url, text };
  } catch {
    return undefined;
  }
}

export function formatContents(
  results: ContentsResultItem[],
  statuses: ContentsStatus[] = [],
): { text: string; sections: string[] } {
  const sections = results.map((item, idx) => {
    const body = (item.text ?? "").trim();
    return [...heading(idx, item, body.length), body].join("\n");
  });
  const blocks = [sections.length ? sections.join(SEPARATOR) : "No content fetched."];
  const failed = statuses.filter((s) => s.status === "error");
  if (failed.length) {
    const lines = failed.map((f) => {
      const code = f.error?.httpStatusCode ? ` (${f.error.httpStatusCode})` : "";
      return `- ${f.id ?? "unknown"}: ${f.error?.tag ?? "error"}${code}`;
    });
    blocks.push(`Failed URLs:\n${lines.join("\n")}`);
  }
  return { text: blocks.join("\n\n"), sections };
}

export function fetchedNothing(body: string): boolean {
  try {
    return ((JSON.parse(body) as { results?: unknown[] }).results?.length ?? 0) === 0;
  } catch {
    return false;
  }
}

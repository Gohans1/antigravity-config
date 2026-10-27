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

const heading = (idx: number, item: { title?: string | null; url?: string }, chars?: number) => {
  const title = typeof item.title === "string" ? item.title.trim() : "";
  const url = typeof item.url === "string" ? item.url : "";
  return [
    `${idx + 1}. ${title || url || "Untitled"}`,
    ...(url ? [`URL: ${url}${chars === undefined ? "" : ` (${chars} chars)`}`] : []),
  ];
};

export const FULL_HIGHLIGHT_RESULTS = 5;

const TRACKING_PARAMS = new Set([
  "fbclid",
  "gclid",
  "dclid",
  "msclkid",
  "mc_cid",
  "mc_eid",
  "igshid",
  "ref_src",
  "ref_url",
]);
const YT_ID_RE = /^[A-Za-z0-9_-]{11}$/;

function canonicalUrlKey(rawUrl?: string): string | undefined {
  if (typeof rawUrl !== "string") return undefined;
  const trimmed = rawUrl.trim();
  if (!trimmed) return undefined;
  try {
    const u = new URL(trimmed);
    if (u.protocol !== "http:" && u.protocol !== "https:") return `raw:${trimmed}`;
    const pathname = u.pathname;
    let end = pathname.length;
    while (end > 1 && pathname.charCodeAt(end - 1) === 47) end--;
    const path = (end === pathname.length ? pathname : pathname.slice(0, end)) || "/";
    const rawHost = u.hostname.toLowerCase();
    if (rawHost === "youtu.be") {
      const id = path.slice(1);
      if (YT_ID_RE.test(id)) return `yt:${id}`;
    } else if (/^(?:(?:www|m|music|gaming)\.)?youtube(?:-nocookie)?\.com$/.test(rawHost)) {
      const id =
        path === "/watch"
          ? (u.searchParams.get("v") ?? "")
          : (path.match(/^\/(?:shorts|embed|v|live)\/([^/]+)$/)?.[1] ?? "");
      if (id !== "videoseries" && id !== "live_stream" && YT_ID_RE.test(id)) return `yt:${id}`;
    } else if (/^(?:(?:www|mobile)\.)?(?:x|twitter)\.com$/.test(rawHost)) {
      const statusId = path.match(/^\/(?:[^/]+|i\/web)\/(?:status|article)\/(\d+)(?:\/|$)/i)?.[1];
      if (statusId) return `x:${statusId}`;
    }

    let host = rawHost.replace(/^www\./, "");
    if (host === "twitter.com" || host === "mobile.twitter.com" || host === "mobile.x.com") host = "x.com";
    const port = u.port ? `:${u.port}` : "";
    const params = [...u.searchParams.entries()]
      .filter(([k]) => {
        const key = k.toLowerCase();
        return !key.startsWith("utm_") && !TRACKING_PARAMS.has(key);
      })
      .sort(([ak, av], [bk, bv]) => (ak < bk ? -1 : ak > bk ? 1 : av < bv ? -1 : av > bv ? 1 : 0));
    const qs = new URLSearchParams(params).toString();
    return `url:${host}${port}${path}${qs ? `?${qs}` : ""}${u.hash}`;
  } catch {
    return `raw:${trimmed}`;
  }
}

const refLabel = (ref: { num: number; url?: string }) => {
  const u = typeof ref.url === "string" ? ref.url.replace(/[\x00-\x1f\x7f-\x9f]+/g, "").trim() : "";
  return u ? `#${ref.num} (${u})` : `#${ref.num}`;
};

// One string per result, so a size cap can cut between results instead of inside one.
export function formatSearchSections(
  body: string,
  emptyHint = "",
  highlightResults = FULL_HIGHLIGHT_RESULTS,
): string[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return [body];
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return [body];
  const rawResults = (parsed as { results?: unknown }).results;
  if (rawResults != null && !Array.isArray(rawResults)) return [body];

  const results = (rawResults ?? []).filter(
    (r): r is SearchResultItem => Boolean(r) && typeof r === "object" && !Array.isArray(r),
  );
  if (results.length === 0) return [emptyHint ? `No results found. ${emptyHint}` : "No results found."];

  const seenUrls = new Map<string, { num: number; url?: string; reservedSlot: boolean; hasHighlights: boolean }>();
  const seenHighlights = new Map<string, { num: number; url?: string; shown: boolean }>();
  let slotsUsed = 0;

  return results.map((item, idx) => {
    const num = idx + 1;
    const lines = heading(idx, item);
    const url = typeof item.url === "string" ? item.url : undefined;
    const pub =
      typeof item.publishedDate === "string" && item.publishedDate
        ? `Published: ${item.publishedDate.slice(0, 10)}`
        : "";
    const highlights = (Array.isArray(item.highlights) ? item.highlights : [])
      .filter((h): h is string => typeof h === "string")
      .map((h) => h.trim())
      .filter(Boolean);
    const joined = highlights.join("\n...\n");
    const norm = joined ? joined.replace(/\s+/g, " ") : "";
    const urlKey = canonicalUrlKey(url);
    const inBudget = slotsUsed < highlightResults;
    const urlDup = urlKey ? seenUrls.get(urlKey) : undefined;
    const contentDup = norm ? seenHighlights.get(norm) : undefined;

    if (urlDup) {
      if ((urlDup.reservedSlot || inBudget) && !urlDup.hasHighlights && highlights.length > 0) {
        if (pub) lines.push(pub);
        if (contentDup?.shown) {
          if (urlDup.reservedSlot) {
            slotsUsed--;
            urlDup.reservedSlot = false;
          }
          lines.push(`[same URL as ${refLabel(urlDup)}; duplicate of ${refLabel(contentDup)}: identical highlights omitted]`);
        } else {
          if (!urlDup.reservedSlot) slotsUsed++;
          urlDup.reservedSlot = false;
          lines.push(`[same URL as ${refLabel(urlDup)}]`, joined);
          seenHighlights.set(norm, { num, url, shown: true });
        }
        urlDup.num = num;
        urlDup.url = url;
        urlDup.hasHighlights = true;
      } else {
        if (inBudget && pub) lines.push(pub);
        const omitted = inBudget && highlights.length > 0 ? "; highlights omitted" : "";
        lines.push(`[duplicate of ${refLabel(urlDup)}: same URL${omitted}]`);
      }
      return lines.join("\n");
    }

    if (contentDup && (contentDup.shown || !inBudget)) {
      if (inBudget && pub) lines.push(pub);
      lines.push(`[duplicate of ${refLabel(contentDup)}: identical highlights${inBudget ? " omitted" : ""}]`);
      if (urlKey) seenUrls.set(urlKey, { num, url, reservedSlot: false, hasHighlights: contentDup.shown });
      return lines.join("\n");
    }

    const shown = inBudget && highlights.length > 0;
    if (inBudget) {
      slotsUsed++;
      if (pub) lines.push(pub);
      if (highlights.length) lines.push(joined);
    }
    if (urlKey) seenUrls.set(urlKey, { num, url, reservedSlot: inBudget && !shown, hasHighlights: shown });
    if (norm) seenHighlights.set(norm, { num, url, shown });
    return lines.join("\n");
  });
}

const MIN_HTML_CHARS = 200;
const STRUCTURED_EXT_RE = /\.(?:ya?ml|json[lc]?|toml)$/i;
const STRUCTURED_MIMES = new Set([
  "application/json",
  "text/json",
  "application/jsonl",
  "application/x-ndjson",
  "application/ndjson",
  "application/jsonlines",
  "application/jsonc",
  "application/yaml",
  "application/x-yaml",
  "text/yaml",
  "text/x-yaml",
  "text/vnd.yaml",
  "application/toml",
  "application/x-toml",
  "text/toml",
  "text/x-toml",
]);
const RAW_FALLBACK_MIMES = new Set(["", "text/plain", "application/octet-stream", "binary/octet-stream"]);
const isStructuredMime = (mime: string) =>
  STRUCTURED_MIMES.has(mime) || mime.endsWith("+json") || mime.endsWith("+yaml");
const hasStructuredExt = (u: string) => {
  try {
    return STRUCTURED_EXT_RE.test(new URL(u).pathname);
  } catch {
    return false;
  }
};
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

    const headers: Record<string, string> = { Accept: "text/markdown, text/html;q=0.9, */*;q=0.8" };
    if (isGitHub) headers["User-Agent"] = "Mozilla/5.0 (compatible; Defuddle/1.0; +https://defuddle.md) bot";

    const res = await fetchImpl(url, { headers });
    if (!res.ok) return undefined;
    const finalUrl = res.url || url;
    const isX = isXStatus(finalUrl);
    if (/(?:^|\.)(?:x|twitter)\.com$/i.test(new URL(finalUrl).hostname) && !isX) return undefined;

    const mime = (res.headers.get("content-type") ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
    const structured =
      isStructuredMime(mime) ||
      (RAW_FALLBACK_MIMES.has(mime) && (hasStructuredExt(finalUrl) || hasStructuredExt(url)));
    const directText = mime === "text/markdown" || mime === "text/plain";
    const isHtml = mime === "text/html" || mime === "application/xhtml+xml";
    if (!structured && !directText && !isHtml && !isX) {
      res.body?.cancel().catch(() => {});
      return undefined;
    }

    const body = await res.text();
    const notHtmlOrBinary = !/^\s*<(?:!doctype\s+html|html)\b/i.test(body) && !body.includes("\0");

    if (structured && notHtmlOrBinary) {
      const text = body.trim();
      return text ? { url, title: url, text } : undefined;
    }

    if (directText && notHtmlOrBinary) {
      const text = body.trim().replace(/^(`{3,}[\w-]+)\{[^}\n]+\}/gm, "$1");
      if (!text) return undefined;
      const fm = text.match(/^---\r?\n(?:[\s\S]*?\r?\n)?title:\s*["']?(.+?)["']?\r?\n[\s\S]*?---/);
      const h1 = text.match(/^#\s+(.+)$/m);
      return { url, title: (fm?.[1] ?? h1?.[1])?.trim() || url, text };
    }

    if (!isHtml && !isX) return undefined;

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
    if (!isX && text.length < MIN_HTML_CHARS) return undefined;
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

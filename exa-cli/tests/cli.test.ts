import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runCli } from "../src/cli";

const KEY_1 = "11111111-aaaa-4bbb-8ccc-000000000001";
const KEY_2 = "22222222-aaaa-4bbb-8ccc-000000000002";
const ENV_KEYS = { EXA_CONFIG_PATH: "/nonexistent/exa.json", EXA_API_KEYS: KEY_1 };

interface Recorded {
  url: string;
  key: string;
  body: Record<string, unknown>;
}

// Fake Exa /search and /contents endpoint that records what the CLI sent.
function fakeExa(response: unknown, statusByKey: Record<string, number> = {}) {
  const requests: Recorded[] = [];
  const fetchImpl = async (url: string, init?: RequestInit) => {
    if (!url.startsWith("https://api.exa.ai/")) {
      return new Response("<html></html>", { headers: { "content-type": "text/html" } });
    }
    const key = (init?.headers as Record<string, string>)["x-api-key"] ?? "";
    requests.push({ url, key, body: JSON.parse(String(init?.body)) });
    const status = statusByKey[key] ?? 200;
    return new Response(JSON.stringify(status === 200 ? response : { error: "No more credits" }), { status });
  };
  return { requests, fetchImpl };
}

async function run(
  argv: string[],
  env: Record<string, string | undefined>,
  fetchImpl?: (url: string, init?: RequestInit) => Promise<Response>,
) {
  const out: string[] = [];
  const err: string[] = [];
  const code = await runCli(argv, {
    env,
    fetchImpl: fetchImpl ?? (async () => new Response("{}", { status: 500 })),
    out: (m) => out.push(m),
    err: (m) => err.push(m),
  });
  return { code, out: out.join("\n"), err: err.join("\n") };
}

function withConfig(keys: { label: string; value: string }[], use: (path: string) => Promise<void>) {
  const dir = mkdtempSync(join(tmpdir(), "exa-cli-"));
  const path = join(dir, "config.json");
  writeFileSync(path, JSON.stringify({ keys }));
  return use(path).finally(() => rmSync(dir, { recursive: true, force: true }));
}

const HONO = {
  results: [
    {
      title: "JWT Auth Middleware",
      url: "https://hono.dev/docs/middleware/builtin/jwt",
      highlights: ["The JWT Auth Middleware provides authentication by verifying the token with JWT."],
    },
  ],
};

describe("exa status", () => {
  test("lists key labels and the config path without printing key values", async () => {
    await withConfig(
      [
        { label: "primary", value: KEY_1 },
        { label: "backup", value: KEY_2 },
      ],
      async (path) => {
        const { code, out } = await run(["status"], { EXA_CONFIG_PATH: path });

        expect(code).toBe(0);
        expect(out).toBe(`Exa CLI: 2 key(s) (saved) [${path}]\n  1. primary\n  2. backup`);
      },
    );
  });
});

describe("exa search", () => {
  test("sends ten fast search results with bare highlights and fails over when credits run out", async () => {
    await withConfig(
      [
        { label: "empty", value: KEY_1 },
        { label: "full", value: KEY_2 },
      ],
      async (path) => {
        const exa = fakeExa(HONO, { [KEY_1]: 402 });

        const { code, out } = await run(["search", "hono", "jwt", "middleware"], { EXA_CONFIG_PATH: path }, exa.fetchImpl);

        expect(code).toBe(0);
        expect(exa.requests.at(-1)).toEqual({
          url: "https://api.exa.ai/search",
          key: KEY_2,
          body: {
            query: "hono jwt middleware",
            type: "fast",
            numResults: 10,
            contents: { highlights: true },
          },
        });
        expect(out).toBe(
          "1. JWT Auth Middleware\nURL: https://hono.dev/docs/middleware/builtin/jwt\nThe JWT Auth Middleware provides authentication by verifying the token with JWT.",
        );
      },
    );
  });

  test("passes search type and domain filters to Exa while -n controls how many of the 10 results show highlights", async () => {
    const tenResults = {
      results: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => ({
        title: `Doc ${n}`,
        url: `https://developers.cloudflare.com/${n}`,
        publishedDate: "2026-10-10T00:00:00.000Z",
        highlights: [`Passage ${n}`],
      })),
    };
    const exa = fakeExa(tenResults);

    const { code, out } = await run(
      ["search", "durable objects alarms", "-n", "7", "-t", "auto", "--include-domains", "developers.cloudflare.com,github.com", "--exclude-domains", "medium.com"],
      ENV_KEYS,
      exa.fetchImpl,
    );

    expect(code).toBe(0);
    expect(exa.requests[0]!.body).toEqual({
      query: "durable objects alarms",
      type: "auto",
      numResults: 10,
      contents: { highlights: true },
      includeDomains: ["developers.cloudflare.com", "github.com"],
      excludeDomains: ["medium.com"],
    });
    const sections = out.split("\n\n---\n\n");
    expect(sections).toHaveLength(10);
    expect(sections[0]).toBe("1. Doc 1\nURL: https://developers.cloudflare.com/1\nPublished: 2026-10-10\nPassage 1");
    expect(sections[6]).toBe("7. Doc 7\nURL: https://developers.cloudflare.com/7\nPublished: 2026-10-10\nPassage 7");
    expect(sections[7]).toBe("8. Doc 8\nURL: https://developers.cloudflare.com/8");
    expect(sections[9]).toBe("10. Doc 10\nURL: https://developers.cloudflare.com/10");
  });

  test("accepts --num-results and --max-results as aliases for -n (5-10)", async () => {
    const tenResults = {
      results: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => ({
        title: `Doc ${n}`,
        url: `https://bun.sh/${n}`,
        highlights: [`Highlight ${n}`],
      })),
    };

    for (const flag of ["--num-results", "--max-results"]) {
      const exa = fakeExa(tenResults);
      const { code, out, err } = await run(["search", "bun", flag, "6"], ENV_KEYS, exa.fetchImpl);

      expect(code).toBe(0);
      expect(err).toBe("");
      expect(exa.requests).toHaveLength(1);
      expect(exa.requests[0]!.body).toEqual({
        query: "bun",
        type: "fast",
        numResults: 10,
        contents: { highlights: true },
      });
      const sections = out.split("\n\n---\n\n");
      expect(sections).toHaveLength(10);
      expect(sections[5]).toBe("6. Doc 6\nURL: https://bun.sh/6\nHighlight 6");
      expect(sections[6]).toBe("7. Doc 7\nURL: https://bun.sh/7");
    }
  });

  test("rejects an unknown search type before calling Exa", async () => {
    const exa = fakeExa(HONO);

    const { code, err } = await run(["search", "bun", "-t", "deep"], ENV_KEYS, exa.fetchImpl);

    expect(code).toBe(1);
    expect(err).toBe("--type must be one of: auto, fast, instant");
    expect(exa.requests).toHaveLength(0);
  });

  test("rejects a highlight count outside 5-10 for every alias", async () => {
    const exa = fakeExa(HONO);

    for (const flag of ["-n", "--max-results", "--num-results"]) {
      for (const n of ["0", "1", "4", "11", "101", "5.5", "abc"]) {
        const { code, err } = await run(["search", "bun", flag, n], ENV_KEYS, exa.fetchImpl);
        expect(code).toBe(1);
        expect(err).toBe("-n must be an integer between 5 and 10");
      }
    }
    expect(exa.requests).toHaveLength(0);
  });

  test("shows usage when the query is missing", async () => {
    const { code, err } = await run(["search"], ENV_KEYS);

    expect(code).toBe(1);
    expect(err).toBe("Usage: exa search <query> [options]. Run 'exa --help' for options.");
  });

  test("rejects unknown options", async () => {
    const { code, err } = await run(["search", "bun", "--depth", "advanced"], ENV_KEYS);

    expect(code).toBe(1);
    expect(err).toBe("Unknown option '--depth'. Run 'exa --help' for usage.");
  });

test("adds a note pointing to exa fetch when an excerpt elides text", async () => {
    const elided = { results: [{ title: "JWT", url: "https://hono.dev/jwt", highlights: ["jwt({ alg: 'HS2 ... 6' })"] }] };

    const { out } = await run(["search", "hono jwt"], ENV_KEYS, fakeExa(elided).fetchImpl);

    expect(out).toEndWith(
      "\nNote: some excerpts elide text with \" ... \"; run 'exa fetch <url>' for exact code or wording.",
    );
  });

  test("keeps --json output as Exa's raw response even when excerpts are elided", async () => {
    const elided = { results: [{ title: "JWT", url: "https://hono.dev/jwt", highlights: ["alg: 'HS2 ... 6'"] }] };

    const { out } = await run(["search", "hono jwt", "--json"], ENV_KEYS, fakeExa(elided).fetchImpl);

    expect(JSON.parse(out)).toEqual(elided);
  });

  test("suggests describing the page when nothing is found", async () => {
    const { code, out } = await run(["search", "frobnicate qwzx"], ENV_KEYS, fakeExa({ results: [] }).fetchImpl);

    expect(code).toBe(0);
    expect(out).toBe("No results found. Describe the page you want instead of listing keywords.");
  });

  test("also suggests dropping domain filters when they were used and nothing is found", async () => {
    const { out } = await run(
      ["search", "durable objects", "--include-domains", "example.invalid"],
      ENV_KEYS,
      fakeExa({ results: [] }).fetchImpl,
    );

    expect(out).toBe(
      "No results found. Describe the page you want instead of listing keywords, or drop --include-domains/--exclude-domains.",
    );
  });

  test("prints Exa's raw response with --json", async () => {
    const exa = fakeExa(HONO);

    const { out } = await run(["search", "hono jwt", "--json"], ENV_KEYS, exa.fetchImpl);

    expect(JSON.parse(out)).toEqual(HONO);
  });
});

describe("exa fetch", () => {
  const PAGE = {
    url: "https://hono.dev/docs/middleware/builtin/jwt",
    title: "JWT Auth Middleware",
    text: "app.use('/auth/*', jwt({ secret: 'it-is-very-secret', alg: 'HS256' }))",
  };

  test("asks /contents for the full text of every URL and prints each page", async () => {
    const exa = fakeExa({
      results: [PAGE, { url: "https://bun.com/blog", title: "Bun Blog", text: "Bun v1.4.3" }],
      statuses: [
        { id: PAGE.url, status: "success" },
        { id: "https://bun.com/blog", status: "success" },
      ],
    });

    const { code, out } = await run(["fetch", PAGE.url, "https://bun.com/blog"], ENV_KEYS, exa.fetchImpl);

    expect(code).toBe(0);
    expect(exa.requests[0]).toEqual({
      url: "https://api.exa.ai/contents",
      key: KEY_1,
      body: { urls: [PAGE.url, "https://bun.com/blog"], text: true },
    });
    expect(out).toBe(
      [
        "1. JWT Auth Middleware",
        `URL: ${PAGE.url} (${PAGE.text.length} chars)`,
        PAGE.text,
        "",
        "---",
        "",
        "2. Bun Blog",
        "URL: https://bun.com/blog (10 chars)",
        "Bun v1.4.3",
      ].join("\n"),
    );
  });

  test("lists the URLs Exa could not fetch next to the pages it did fetch", async () => {
    const exa = fakeExa({
      results: [PAGE],
      statuses: [
        { id: PAGE.url, status: "success" },
        { id: "https://hono.dev/missing", status: "error", error: { tag: "CRAWL_NOT_FOUND", httpStatusCode: 404 } },
      ],
    });

    const { code, out } = await run(["fetch", PAGE.url, "https://hono.dev/missing"], ENV_KEYS, exa.fetchImpl);

    expect(code).toBe(0);
    expect(out).toEndWith("\n\nFailed URLs:\n- https://hono.dev/missing: CRAWL_NOT_FOUND (404)");
  });

  test("exits 1 when no page could be fetched", async () => {
    const exa = fakeExa({
      results: [],
      statuses: [{ id: "https://intranet.local", status: "error", error: { tag: "SOURCE_NOT_AVAILABLE", httpStatusCode: 403 } }],
    });

    const { code, out } = await run(["fetch", "https://intranet.local"], ENV_KEYS, exa.fetchImpl);

    expect(code).toBe(1);
    expect(out).toBe("No content fetched.\n\nFailed URLs:\n- https://intranet.local: SOURCE_NOT_AVAILABLE (403)");
  });

  test("shows usage when no URL is given", async () => {
    const { code, err } = await run(["fetch"], ENV_KEYS);

    expect(code).toBe(1);
    expect(err).toBe("Usage: exa fetch <url...>. Run 'exa --help' for options.");
  });

  test("fetches markdown directly when the origin serves text/markdown or text/plain, preserving <...> and headings without calling Exa", async () => {
    const headersSeen: Record<string, string>[] = [];
    const md = "# JavaScript SDK\n\n## Locate something with `box`\n\nUse `<delivered>` and `SystemOneResult<Q>`.";
    const fetchImpl = async (url: string, init?: RequestInit) => {
      headersSeen.push((init?.headers ?? {}) as Record<string, string>);
      if (url === "https://docs.typesafe.ai/sdk/javascript") {
        return new Response(md, { headers: { "content-type": "text/markdown; charset=utf-8" } });
      }
      throw new Error(`Unexpected call to ${url}`);
    };

    const { code, out, err } = await run(["fetch", "https://docs.typesafe.ai/sdk/javascript"], {}, fetchImpl);

    expect(code).toBe(0);
    expect(err).toBe("");
    expect(headersSeen[0]?.Accept).toContain("text/markdown");
    expect(out).toBe(`1. JavaScript SDK\nURL: https://docs.typesafe.ai/sdk/javascript (${md.length} chars)\n${md}`);
  });

  test("falls back to Exa /contents only for URLs that do not return markdown or plain text, keeping input order", async () => {
    const exa = fakeExa({
      results: [PAGE],
      statuses: [{ id: PAGE.url, status: "success" }],
    });
    const fetchImpl = async (url: string, init?: RequestInit) => {
      if (url === "https://raw.dev/guide.md") {
        return new Response('---\ntitle: "Raw Guide"\n---\nBody with <T>.', {
          headers: { "content-type": "text/plain; charset=utf-8" },
        });
      }
      return exa.fetchImpl(url, init);
    };

    const { code, out } = await run(["fetch", "https://raw.dev/guide.md", PAGE.url], ENV_KEYS, fetchImpl);

    expect(code).toBe(0);
    expect(exa.requests).toEqual([
      {
        url: "https://api.exa.ai/contents",
        key: KEY_1,
        body: { urls: [PAGE.url], text: true },
      },
    ]);
    expect(out).toBe(
      [
        "1. Raw Guide",
        "URL: https://raw.dev/guide.md (41 chars)",
        '---\ntitle: "Raw Guide"\n---\nBody with <T>.',
        "",
        "---",
        "",
        "2. JWT Auth Middleware",
        `URL: ${PAGE.url} (${PAGE.text.length} chars)`,
        PAGE.text,
      ].join("\n"),
    );
  });

  test("extracts clean markdown locally with Defuddle when the origin serves HTML, preserving <Type> generics and code blocks without calling Exa", async () => {
    const html = `<!DOCTYPE html><html><head><title>Utility Types</title></head><body>
      <nav><a href="/">Sidebar menu</a></nav>
      <main><article class="markdown">
        <h1>Utility Types</h1>
        <h2><a class="anchor" href="#awaited"></a><code>Awaited&#x3C;Type></code></h2>
        <p>This type models operations like <code>await</code> in <code>async</code> functions, nested <code>Record&lt;string, Promise&lt;Array&lt;User&gt;&gt;&gt;</code>, JSX <code>&lt;Suspense fallback={&lt;Spinner /&gt;}&gt;</code>, and arrow <code>&lt;T extends Record&lt;string, unknown&gt;&gt;(x: T) =&gt; T</code>:</p>
        <ul>
          <li>First item with <code>ReadonlyArray&lt;T&gt;</code> and <code>Map&lt;K, V&gt;</code>.</li>
          <li>Second item with <code>Extract&lt;Union, { type: "a" }&gt;</code>.</li>
        </ul>
        <blockquote><p>Always prefer <code>Promise&lt;unknown&gt;</code> over <code>Promise&lt;any&gt;</code> when parsing external payloads.</p></blockquote>
        <table>
          <thead><tr><th>Utility</th><th>Signature</th></tr></thead>
          <tbody>
            <tr><td>Awaited</td><td><code>Awaited&lt;Type&gt;</code></td></tr>
            <tr><td>Record</td><td><code>Record&lt;Keys, Type&gt;</code></td></tr>
          </tbody>
        </table>
        <pre class="shiki twoslash lsp"><div class="language-id">ts</div><div class="code-container"><code><div class="line">type A = Awaited&lt;Promise&lt;string&gt;&gt;;</div></code></div><a class="playground-link" href="https://www.typescriptlang.org/play">Try</a></pre>
        <pre><code>plainCodeWithoutLang(&lt;T&gt;);</code></pre>
      </article></main>
      <footer>Copyright 2026</footer>
    </body></html>`;
    const fetchImpl = async (url: string) => {
      if (url === "https://www.typescriptlang.org/docs/handbook/utility-types.html") {
        return new Response(html, { headers: { "content-type": "text/html; charset=utf-8" } });
      }
      throw new Error(`Unexpected call to ${url}`);
    };

    const { code, out, err } = await run(
      ["fetch", "https://www.typescriptlang.org/docs/handbook/utility-types.html"],
      {},
      fetchImpl,
    );

    expect(code).toBe(0);
    expect(err).toBe("");
    expect(out).toMatch(/^1\. Utility Types\nURL: https:\/\/www\.typescriptlang\.org\/docs\/handbook\/utility-types\.html \(\d+ chars\)\n/);
    expect(out).toContain("## `Awaited<Type>`");
    expect(out).toContain("`Record<string, Promise<Array<User>>>`");
    expect(out).toContain("`<Suspense fallback={<Spinner />}>`");
    expect(out).toContain("`<T extends Record<string, unknown>>(x: T) => T`");
    expect(out).toContain("- First item with `ReadonlyArray<T>` and `Map<K, V>`.");
    expect(out).toContain("- Second item with `Extract<Union, { type: \"a\" }>`.");
    expect(out).toContain("> Always prefer `Promise<unknown>` over `Promise<any>`");
    expect(out).toContain("| Awaited | `Awaited<Type>` |");
    expect(out).toContain("```ts\ntype A = Awaited<Promise<string>>;\n```");
    expect(out).toContain("```\nplainCodeWithoutLang(<T>);\n```");
    expect(out).not.toContain("```markdown");
    expect(out).not.toContain("tstype A");
    expect(out).not.toContain("Try");
    expect(out).not.toContain("Sidebar menu");
  });

  test("handles Fumadocs headings, Expressive Code/Docusaurus/Gist/Sphinx/Rehype Pretty Code/Prism/CSS blocks, GitHub blobs, bad JSON-LD, and X profile fallback", async () => {
    const exa = fakeExa({
      results: [{ url: "https://x.com/oven_sh", title: "Bun (@oven_sh)", text: "Exa profile fallback." }],
      statuses: [{ id: "https://x.com/oven_sh", status: "success" }],
    });
    const tortureHtml = `<!DOCTYPE html><html class="js"><head>
      <title>Torture Doc</title>
      <script type="application/ld+json">{bad json</script>
    </head><body><main><article>
      <h1>Torture Doc</h1>
      <h2 id="usage"><a href="#usage">Usage with <code>&lt;script setup&gt;</code></a><button type="button"><span class="sr-only">Copy Anchor Link</span></button></h2>
      <p>Here is a complete guide to configuring all supported syntax highlighters and generic type signatures in modern documentation sites.</p>
      <div class="expressive-code"><pre data-language="ts"><code><div class="ec-line"><div class="code">const a = 1;</div></div>\n      <div class="ec-line"><div class="code">const b = 2;</div></div></code></pre></div>
      <div class="language-ts codeBlockContainer_x"><pre class="prism-code language-ts"><code><span class="token-line"><span class="codeLineNumber_a">1</span><span class="codeLineContent_b">const docusaurus = true;</span><br></span>\n      <span class="token-line"><span class="codeLineNumber_a">2</span><span class="codeLineContent_b">export default docusaurus;</span><br></span></code></pre></div>
      <div class="highlight" data-tagsearch-lang="Python"><table class="highlight js-file-line-container"><tr><td class="blob-num js-line-number" data-line-number="1"></td><td class="blob-code js-file-line">def gist():</td></tr>\n      <tr><td class="blob-num js-line-number" data-line-number="2"></td><td class="blob-code js-file-line">    return 42</td></tr></table></div>
      <div class="highlight-python3 notranslate"><div class="highlight"><pre><code>x: list[int] = [1, 2]</code></pre></div></div>
      <div class="highlight highlight-source-ts"><pre><code>type G&lt;T&gt; = Promise&lt;T&gt;;</code></pre></div>
      <figure data-rehype-pretty-code-figure=""><pre class="no-scrollbar has-data-line-numbers:px-0 has-[[data-line-numbers]]:px-0" data-language="tsx"><code data-language="tsx"><span data-line="" class="group-data-[line-numbers]:pl-4">import { Button } from &quot;@/components/ui/button&quot;;</span></code></pre></figure>
      <pre class="line-numbers language-ts"><code class="language-ts">const prism = 1;<span aria-hidden="true" class="line-numbers-rows"><span>1</span></span></code></pre>
      <pre><code class="language-css">.btn { color: red; }</code></pre>
      <div class="alert alert--info"><div class="admonitionHeading_x">info</div><p>Docusaurus callout body.</p></div>
    </article></main></body></html>`;
    const blobHtml = `<!DOCTYPE html><html><head><title>hono/src/hono.ts at main · honojs/hono</title></head><body>
      <script type="application/json" data-target="react-app.embeddedData">${JSON.stringify({
        payload: {
          "codeViewBlobLayoutRoute.StyledBlob": {
            rawLines: ["export class Hono<E extends Env = BlankEnv> {", "  readonly router = new SmartRouter();", "}"],
          },
        },
      })}</script>
      <div class="react-line-numbers"><div>1</div><div>2</div><div>3</div></div>
    </body></html>`;

    const fetchImpl = async (url: string, init?: RequestInit) => {
      if (url === "https://fumadocs.dev/docs/ui/components/codeblock") {
        return new Response(tortureHtml, { headers: { "content-type": "text/html; charset=utf-8" } });
      }
      if (url === "https://github.com/honojs/hono/blob/main/src/hono.ts") {
        return new Response(blobHtml, { headers: { "content-type": "text/html; charset=utf-8" } });
      }
      if (url === "https://x.com/oven_sh") {
        return new Response("<!DOCTYPE html><html><body><p>Don't miss what's happening. Log in Sign up to X Corp.</p></body></html>", {
          headers: { "content-type": "text/html; charset=utf-8" },
        });
      }
      return exa.fetchImpl(url, init);
    };

    const { code, out, err } = await run(
      [
        "fetch",
        "https://fumadocs.dev/docs/ui/components/codeblock",
        "https://github.com/honojs/hono/blob/main/src/hono.ts",
        "https://x.com/oven_sh",
      ],
      ENV_KEYS,
      fetchImpl,
    );

    expect(code).toBe(0);
    expect(err).toBe("");
    expect(out).toContain("## Usage with `<script setup>`");
    expect(out).not.toContain("Copy Anchor Link");
    expect(out).toContain("```ts\nconst a = 1;\nconst b = 2;\n```");
    expect(out).toContain("```ts\nconst docusaurus = true;\nexport default docusaurus;\n```");
    expect(out).toContain("```python\ndef gist():\n    return 42\n```");
    expect(out).toContain("```python\nx: list[int] = [1, 2]\n```");
    expect(out).toContain("```ts\ntype G<T> = Promise<T>;\n```");
    expect(out).toContain('```tsx\nimport { Button } from "@/components/ui/button";\n```');
    expect(out).toContain("```ts\nconst prism = 1;\n```");
    expect(out).toContain("```css\n.btn { color: red; }\n```");
    expect(out).toContain("> [!info]");
    expect(out).not.toContain("[!-info]");
    expect(out).toContain("```ts\nexport class Hono<E extends Env = BlankEnv> {\n  readonly router = new SmartRouter();\n}\n```");
    expect(out).toContain("3. Bun (@oven_sh)\nURL: https://x.com/oven_sh (21 chars)\nExa profile fallback.");
  });

  test("uses Defuddle async extractor for X/Twitter status URLs and bot User-Agent for GitHub", async () => {
    const seen: { url: string; ua?: string }[] = [];
    const fetchImpl = async (url: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      seen.push({ url, ua: headers["User-Agent"] });
      if (url === "https://x.com/kepano/status/2078550254027477399") {
        return new Response("<!DOCTYPE html><html><body></body></html>", {
          headers: { "content-type": "text/html; charset=utf-8" },
        });
      }
      if (url === "https://api.fxtwitter.com/kepano/status/2078550254027477399") {
        return new Response(
          JSON.stringify({
            code: 200,
            tweet: {
              text: "Shipping Defuddle CLI today.",
              author: { name: "Steph Ango", screen_name: "kepano" },
              created_timestamp: 1752600000,
            },
          }),
          { headers: { "content-type": "application/json" } },
        );
      }
      if (url === "https://x.com/kepano/status/2078550254027477400") {
        return new Response("<!DOCTYPE html><html><body></body></html>", {
          headers: { "content-type": "text/html; charset=utf-8" },
        });
      }
      if (url === "https://api.fxtwitter.com/kepano/status/2078550254027477400") {
        await new Promise((r) => setTimeout(r, 15));
        return new Response(
          JSON.stringify({
            code: 200,
            tweet: {
              text: "Second tweet.",
              author: { name: "Steph Ango", screen_name: "kepano" },
              created_timestamp: 1752600001,
            },
          }),
          { headers: { "content-type": "application/json" } },
        );
      }
      if (url === "https://github.com/kepano/defuddle/issues/61") {
        return new Response(
          `<!DOCTYPE html><html><head><title>Issue 61</title></head><body><main><article><h1>Issue 61</h1><p>Full SSR issue body.</p></article></main></body></html>`,
          { headers: { "content-type": "text/html; charset=utf-8" } },
        );
      }
      throw new Error(`Unexpected call to ${url}`);
    };

    const realErr = console.error;
    const { code, out, err } = await run(
      [
        "fetch",
        "https://x.com/kepano/status/2078550254027477399",
        "https://x.com/kepano/status/2078550254027477400",
        "https://github.com/kepano/defuddle/issues/61",
      ],
      {},
      fetchImpl,
    );

    expect(code).toBe(0);
    expect(err).toBe("");
    expect(console.error).toBe(realErr);
    expect(seen.find((s) => s.url.includes("github.com"))?.ua).toContain("Defuddle");
    expect(out).toContain("Shipping Defuddle CLI today.");
    expect(out).toContain("Second tweet.");
    expect(out).toContain("Full SSR issue body.");
  });

  test("rejects options fetch does not support", async () => {
    const { code, err } = await run(["fetch", PAGE.url, "-q", "cookie"], ENV_KEYS);

    expect(code).toBe(1);
    expect(err).toBe("Unknown option '-q'. Run 'exa --help' for usage.");
  });
});

describe("exa output limits", () => {
  const LONG = { results: [{ title: "Long", url: "https://a.dev", highlights: ["x".repeat(30000)] }] };

  test("keeps search text whole by default even past 26000 chars since highlights are already limited to the first 5 results", async () => {
    const { out } = await run(["search", "long page"], ENV_KEYS, fakeExa(LONG).fetchImpl);

    expect(out).toBe(`1. Long\nURL: https://a.dev\n${"x".repeat(30000)}`);
  });

  test("points fetch output past the cap to -o only", async () => {
    const page = { url: "https://a.dev", title: "Long", text: "y".repeat(30000) };
    const exa = fakeExa({ results: [page], statuses: [{ id: page.url, status: "success" }] });

    const { out } = await run(["fetch", page.url], ENV_KEYS, exa.fetchImpl);

    expect(out.split("\n... ")[1]).toMatch(/^\[truncated: showing 26000 of 300\d\d chars; use -o <file> to save all\]$/);
  });

  test("refuses to cut --json output past the cap and says how to get all of it", async () => {
    const { code, out, err } = await run(["search", "long page", "--json"], ENV_KEYS, fakeExa(LONG).fetchImpl);

    expect(code).toBe(1);
    expect(out).toBe("");
    expect(err).toBe(
      `JSON output is ${JSON.stringify(LONG).length} chars (cap 26000); use -o <file> to save all.`,
    );
  });

  test("refuses to cut fetch --json output past the cap too", async () => {
    const page = { url: "https://a.dev", title: "Long", text: "y".repeat(30000) };
    const response = { results: [page], statuses: [{ id: page.url, status: "success" }] };

    const { code, err } = await run(["fetch", page.url, "--json"], ENV_KEYS, fakeExa(response).fetchImpl);

    expect(code).toBe(1);
    expect(err).toBe(`JSON output is ${JSON.stringify(response).length} chars (cap 26000); use -o <file> to save all.`);
  });

  test("keeps responses between 16000 and 26000 chars whole in text and JSON", async () => {
    const response = { results: [{ title: "Medium", url: "https://a.dev", highlights: ["x".repeat(22000)] }] };

    for (const flags of [[], ["--json"]]) {
      const { code, out, err } = await run(["search", "medium page", ...flags], ENV_KEYS, fakeExa(response).fetchImpl);

      expect(code).toBe(0);
      expect(err).toBe("");
      if (flags.length) {
        expect(JSON.parse(out)).toEqual(response);
      } else {
        expect(out).toBe(`1. Medium\nURL: https://a.dev\n${"x".repeat(22000)}`);
      }
    }
  });

  test("still allows a smaller --max-output cap", async () => {
    const { code, out } = await run(["search", "long page", "--max-output", "80"], ENV_KEYS, fakeExa(LONG).fetchImpl);

    expect(code).toBe(0);
    expect(out.split("\n... ")[0]).toHaveLength(80);
    expect(out).toContain("[truncated: showing 80 of ");
  });

  test("fills the cap across results and lists the title and URL of both the cut result and any hidden results", async () => {
    const results = [1, 2, 3, 4, 5].map((n) => ({ title: `R${n}`, url: `https://a.dev/${n}`, highlights: ["x".repeat(1000)] }));

    const { code, out } = await run(["search", "five pages", "--max-output", "2500"], ENV_KEYS, fakeExa({ results }).fetchImpl);

    const [shown = "", note] = out.split("\n... ");
    expect(code).toBe(0);
    expect(shown).toHaveLength(2500);
    expect(shown).toContain("3. R3\nURL: https://a.dev/3\nxxx");
    expect(note).toBe(
      [
        "[truncated: showing 2500 of 5163 chars, cut inside result 3 of 5 (2 more hidden); use -o <file> to save all]",
        "3. R3\nURL: https://a.dev/3",
        "4. R4\nURL: https://a.dev/4",
        "5. R5\nURL: https://a.dev/5",
      ].join("\n"),
    );
  });

  test("fills the 26000-char fetch cap when a short page is followed by a huge page, instead of hiding the huge page's body", async () => {
    const pages = [
      { url: "https://a.dev/short", title: "Short", text: "s".repeat(3400) },
      { url: "https://a.dev/huge", title: "Huge", text: "h".repeat(38000) },
    ];
    const exa = fakeExa({
      results: pages,
      statuses: pages.map((p) => ({ id: p.url, status: "success" })),
    });

    const { code, out } = await run(
      ["fetch", ...pages.map((p) => p.url)],
      ENV_KEYS,
      exa.fetchImpl,
    );

    const [shown = "", note] = out.split("\n... ");
    expect(code).toBe(0);
    expect(shown).toHaveLength(26000);
    expect(shown).toContain("1. Short\nURL: https://a.dev/short (3400 chars)\n" + "s".repeat(3400));
    expect(shown).toContain("2. Huge\nURL: https://a.dev/huge (38000 chars)\nhhhhhhhhhh");
    expect(note).toBe(
      [
        `[truncated: showing 26000 of 41500 chars, cut inside result 2 of 2; use -o <file> to save all]`,
        "2. Huge\nURL: https://a.dev/huge (38000 chars)",
      ].join("\n"),
    );
  });

  test("truncates cleanly without crashing when all fetched sections fit the cap and the Failed URLs footer pushes text past it", async () => {
    const pages = [
      { url: "https://a.dev/1", title: "P1", text: "a".repeat(12900) },
      { url: "https://a.dev/2", title: "P2", text: "b".repeat(13000) },
    ];
    const exa = fakeExa({
      results: pages,
      statuses: [
        { id: "https://a.dev/1", status: "success" },
        { id: "https://a.dev/2", status: "success" },
        { id: "https://a.dev/missing", status: "error", error: { tag: "CRAWL_NOT_FOUND", httpStatusCode: 404 } },
      ],
    });

    const { code, out, err } = await run(
      ["fetch", "https://a.dev/1", "https://a.dev/2", "https://a.dev/missing"],
      ENV_KEYS,
      exa.fetchImpl,
    );

    expect(code).toBe(0);
    expect(err).toBe("");
    expect(out.split("\n... ")[1]).toBe("[truncated: showing 26000 of 26050 chars; use -o <file> to save all]");
  });

  test("keeps every result when they fit the cap exactly and avoids cutting inside the separator or next heading when no body fits", async () => {
    const results = [
      { title: "A", url: "https://a.dev/1", highlights: ["x".repeat(100)] },
      { title: "B", url: "https://a.dev/2", highlights: ["y".repeat(100)] },
    ];
    const first = `1. A\nURL: https://a.dev/1\n${"x".repeat(100)}`;
    const secondHead = `2. B\nURL: https://a.dev/2`;
    const whole = `${first}\n\n---\n\n${secondHead}\n${"y".repeat(100)}`;

    const fits = await run(["search", "two pages", "--max-output", String(whole.length)], ENV_KEYS, fakeExa({ results }).fetchImpl);
    const inHeader = await run(
      ["search", "two pages", "--max-output", String(first.length + 7 + secondHead.length + 1)],
      ENV_KEYS,
      fakeExa({ results }).fetchImpl,
    );

    expect(fits.out).toBe(whole);
    expect(inHeader.out).toBe(
      `${first}\n... [truncated: showing 1 of 2 results, 126 of ${whole.length} chars (1 hidden by the ${first.length + 7 + secondHead.length + 1}-char cap); use -o <file> to save all]\n2. B\nURL: https://a.dev/2`,
    );
  });

  test("cuts inside the first result when it alone passes the cap, and lists both the cut result and hidden results", async () => {
    const results = [
      { title: "Big", url: "https://a.dev/1", highlights: ["x".repeat(3000)] },
      { title: "Small", url: "https://a.dev/2", highlights: ["y"] },
    ];

    const { out } = await run(["search", "big first", "--max-output", "1000"], ENV_KEYS, fakeExa({ results }).fetchImpl);

    const [shown, note] = out.split("\n... ");
    expect(shown).toHaveLength(1000);
    expect(note).toMatch(
      /^\[truncated: showing 1000 of 3\d+ chars, cut inside result 1 of 2 \(1 more hidden\); use -o <file> to save all\]\n1\. Big\nURL: https:\/\/a\.dev\/1\n2\. Small\nURL: https:\/\/a\.dev\/2$/,
    );
  });

  test("prints long --json output whole when --max-output allows it", async () => {
    const { code, out } = await run(["search", "long page", "--json", "--max-output", "50000"], ENV_KEYS, fakeExa(LONG).fetchImpl);

    expect(code).toBe(0);
    expect(JSON.parse(out)).toEqual(LONG);
  });

  test("saves long --json output whole with -o", async () => {
    const dir = mkdtempSync(join(tmpdir(), "exa-json-"));
    try {
      const file = join(dir, "result.json");

      const { code } = await run(["search", "long page", "--json", "-o", file], ENV_KEYS, fakeExa(LONG).fetchImpl);

      expect(code).toBe(0);
      expect(JSON.parse(readFileSync(file, "utf8"))).toEqual(LONG);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("saves the full output with -o and prints a one-line summary", async () => {
    const dir = mkdtempSync(join(tmpdir(), "exa-out-"));
    try {
      const file = join(dir, "nested", "result.md");

      const { out } = await run(["search", "long page", "-o", file], ENV_KEYS, fakeExa(LONG).fetchImpl);

      const saved = readFileSync(file, "utf8");
      expect(saved).toContain("x".repeat(30000));
      expect(out).toBe(`Saved ${saved.length} chars (3 lines) to ${file}`);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("exa help and commands", () => {
  test("prints help for --help and for no arguments", async () => {
    for (const argv of [["--help"], []]) {
      const { code, out } = await run(argv, ENV_KEYS);
      expect(code).toBe(0);
      expect(out).toStartWith("Usage: exa <command> [options]");
      expect(out).toContain("search <query>");
      expect(out).toContain(
        "-n <5-10>                 How many results include highlights (default: 5; all 10 titles + URLs are always shown)",
      );
      expect(out).toContain("--include-domains <d1,d2>   --exclude-domains <d1,d2>");
      expect(out).toContain("fetch <url...>");
      expect(out).toContain(
        "Defaults: type=fast (~0.5s), 10 results (first 5 with highlights, rest title + URL; use -n 5-10 to adjust highlights).\n",
      );
      expect(out).not.toContain("--type");
      expect(out).not.toContain(" -t");
      expect(out).not.toContain("--max-output");
      expect(out).not.toContain("--max-results");
      expect(out).not.toContain("--num-results");
      expect(out).toContain("status");
    }
  });

  test("warns that highlights can cut text mid-word and points to exa fetch for exact content", async () => {
    const { out } = await run(["--help"], ENV_KEYS);

    expect(out).toContain('Highlights are excerpts that can cut text mid-word with " ... "; run \'exa fetch <url>\' before copying code or exact wording.');
  });

  test("describes fetch simply as full page as markdown", async () => {
    const { out } = await run(["--help"], ENV_KEYS);

    expect(out).toContain("fetch <url...>            Full page as markdown\n");
    expect(out).not.toContain("inline code can lose");
  });

  test("tells agents to save large pages past the fetch cap with -o and grep the file", async () => {
    const { out } = await run(["--help"], ENV_KEYS);

    expect(out).toContain("For a large page past the 26000-char fetch cap, save it with -o <file> and grep the file.");
  });

  test("says --json is never truncated", async () => {
    const { out } = await run(["--help"], ENV_KEYS);

    expect(out).toContain("--json                    Raw API response; never truncated, fails with a hint past 26000 chars");
  });

  test("rejects unknown commands with the list of commands", async () => {
    const { code, err } = await run(["hono jwt"], ENV_KEYS);

    expect(code).toBe(1);
    expect(err).toBe("Unknown command 'hono jwt'. Commands: search, fetch, status. Run 'exa --help' for usage.");
  });
});

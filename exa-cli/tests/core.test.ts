import { describe, expect, test } from "bun:test";
import { callWithFailover, formatSearchSections } from "../src/core";

const KEY_1 = "11111111-aaaa-4bbb-8ccc-000000000001";
const KEY_2 = "22222222-aaaa-4bbb-8ccc-000000000002";
const KEY_3 = "33333333-aaaa-4bbb-8ccc-000000000003";
const KEY_4 = "44444444-aaaa-4bbb-8ccc-000000000004";
const URL = "https://api.exa.ai/search";

// Fake Exa server: answers each key with a fixed status, like the real API does per key.
function fakeExa(statusByKey: Record<string, number>, body: (key: string) => unknown) {
  return async (_url: string, init?: RequestInit) => {
    const key = (init?.headers as Record<string, string>)["x-api-key"] ?? "";
    const status = statusByKey[key] ?? 401;
    return new Response(JSON.stringify(body(key)), { status });
  };
}

describe("callWithFailover", () => {
  test("moves past keys that are invalid (401), out of credits (402), or rate limited (429)", async () => {
    const fetchImpl = fakeExa(
      { [KEY_1]: 401, [KEY_2]: 402, [KEY_3]: 429, [KEY_4]: 200 },
      (key) => ({ servedBy: key }),
    );

    const body = await callWithFailover(URL, { query: "bun" }, [KEY_1, KEY_2, KEY_3, KEY_4], fetchImpl);

    expect(JSON.parse(body)).toEqual({ servedBy: "[REDACTED]" });
  });

  test("stops at a 403 and reports Exa's message with keys redacted", async () => {
    const fetchImpl = fakeExa({ [KEY_1]: 403, [KEY_2]: 200 }, (key) => ({
      error: `Feature disabled for ${key}`,
      tag: "FEATURE_DISABLED",
    }));

    await expect(callWithFailover(URL, { query: "bun" }, [KEY_1, KEY_2], fetchImpl)).rejects.toThrow(
      "Exa 403: Feature disabled for [REDACTED]",
    );
  });

  test("lists the status of every key when all of them fail", async () => {
    const fetchImpl = fakeExa({ [KEY_1]: 402, [KEY_2]: 429 }, () => ({ error: "nope" }));

    await expect(callWithFailover(URL, { query: "bun" }, [KEY_1, KEY_2], fetchImpl)).rejects.toThrow(
      "Exa: every key failed (key #1 -> 402 out of credits, key #2 -> 429 rate limited).",
    );
  });

  test("explains where to put keys when none are configured", async () => {
    await expect(callWithFailover(URL, { query: "bun" }, [], fetch)).rejects.toThrow(
      /no API key configured.*exa status.*EXA_API_KEYS/,
    );
  });

  test("reports a network failure without trying other keys", async () => {
    const fetchImpl = async () => {
      throw new TypeError("fetch failed");
    };

    await expect(callWithFailover(URL, { query: "bun" }, [KEY_1, KEY_2], fetchImpl)).rejects.toThrow(
      "Exa: network request failed.",
    );
  });

  test("says to retry when Exa is overloaded and returns no error body", async () => {
    const fetchImpl = async () => new Response("<html>overloaded</html>", { status: 503 });

    await expect(callWithFailover(URL, { query: "bun" }, [KEY_1], fetchImpl)).rejects.toThrow(
      "Exa 503: temporarily unavailable, try again.",
    );
  });
});

describe("formatSearchSections", () => {
  test("shows each result's title, URL, publish date, and highlights", () => {
    const body = JSON.stringify({
      results: [
        {
          title: "JWT Auth Middleware",
          url: "https://hono.dev/docs/middleware/builtin/jwt",
          publishedDate: "2026-10-10T03:18:05.000Z",
          highlights: ["The JWT Auth Middleware provides authentication.", "app.use('/auth/*', jwt(...))"],
        },
        { title: "jwt.ts", url: "https://github.com/honojs/hono/blob/main/src/middleware/jwt/jwt.ts", highlights: [] },
      ],
    });

    expect(formatSearchSections(body)).toEqual([
      [
        "1. JWT Auth Middleware",
        "URL: https://hono.dev/docs/middleware/builtin/jwt",
        "Published: 2026-10-10",
        "The JWT Auth Middleware provides authentication.",
        "...",
        "app.use('/auth/*', jwt(...))",
      ].join("\n"),
      "2. jwt.ts\nURL: https://github.com/honojs/hono/blob/main/src/middleware/jwt/jwt.ts",
    ]);
  });

  test("uses the URL as the heading when a result has no title", () => {
    const body = JSON.stringify({ results: [{ url: "https://bun.com/blog", highlights: ["Bun v1.4.3"] }] });

    expect(formatSearchSections(body)[0]).toStartWith("1. https://bun.com/blog\nURL: https://bun.com/blog\n");
  });

  test("shows full highlights for the first 5 results and only title and URL from result 6 onward", () => {
    const body = JSON.stringify({
      results: [1, 2, 3, 4, 5, 6, 7].map((n) => ({
        title: `Title ${n}`,
        url: `https://example.com/${n}`,
        publishedDate: "2026-10-10T00:00:00.000Z",
        highlights: [`Highlight ${n}`],
      })),
    });

    const sections = formatSearchSections(body);

    expect(sections).toHaveLength(7);
    expect(sections[4]).toBe("5. Title 5\nURL: https://example.com/5\nPublished: 2026-10-10\nHighlight 5");
    expect(sections[5]).toBe("6. Title 6\nURL: https://example.com/6");
    expect(sections[6]).toBe("7. Title 7\nURL: https://example.com/7");
  });

  test("lets caller override how many leading results include highlights while still listing every title and URL", () => {
    const body = JSON.stringify({
      results: [1, 2, 3, 4, 5].map((n) => ({
        title: `Title ${n}`,
        url: `https://example.com/${n}`,
        publishedDate: "2026-10-10T00:00:00.000Z",
        highlights: [`Highlight ${n}`],
      })),
    });

    const sections = formatSearchSections(body, "", 3);

    expect(sections).toEqual([
      "1. Title 1\nURL: https://example.com/1\nPublished: 2026-10-10\nHighlight 1",
      "2. Title 2\nURL: https://example.com/2\nPublished: 2026-10-10\nHighlight 2",
      "3. Title 3\nURL: https://example.com/3\nPublished: 2026-10-10\nHighlight 3",
      "4. Title 4\nURL: https://example.com/4",
      "5. Title 5\nURL: https://example.com/5",
    ]);
  });

  test("says so when there are no results", () => {
    expect(formatSearchSections(JSON.stringify({ results: [] }))).toEqual(["No results found."]);
  });
});

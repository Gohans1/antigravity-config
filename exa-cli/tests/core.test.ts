import { describe, expect, test } from "bun:test";
import { callWithFailover, fetchDirectMarkdown, formatSearchSections } from "../src/core";

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
      results: [1, 2, 3, 4, 5, 6, 7].map((n) => ({
        title: `Title ${n}`,
        url: `https://example.com/${n}`,
        publishedDate: "2026-10-10T00:00:00.000Z",
        highlights: [`Highlight ${n}`],
      })),
    });

    const sections = formatSearchSections(body, "", 6);

    expect(sections).toEqual([
      "1. Title 1\nURL: https://example.com/1\nPublished: 2026-10-10\nHighlight 1",
      "2. Title 2\nURL: https://example.com/2\nPublished: 2026-10-10\nHighlight 2",
      "3. Title 3\nURL: https://example.com/3\nPublished: 2026-10-10\nHighlight 3",
      "4. Title 4\nURL: https://example.com/4\nPublished: 2026-10-10\nHighlight 4",
      "5. Title 5\nURL: https://example.com/5\nPublished: 2026-10-10\nHighlight 5",
      "6. Title 6\nURL: https://example.com/6\nPublished: 2026-10-10\nHighlight 6",
      "7. Title 7\nURL: https://example.com/7",
    ]);
  });

  test("says so when there are no results", () => {
    expect(formatSearchSections(JSON.stringify({ results: [] }))).toEqual(["No results found."]);
  });

  test("omits duplicate highlights for canonical URL aliases while reporting the matched result and promoting unique results", () => {
    const body = JSON.stringify({
      results: [
        {
          title: "Running Minecraft Until It Beats Itself",
          url: "https://youtu.be/9t2fV52jMA8",
          highlights: ["After an insane number of simulated years, this world killed the Ender Dragon."],
        },
        {
          title: "Running Minecraft Until It Beats Itself",
          url: "https://www.youtube.com/watch?v=9t2fV52jMA8&t=30s",
          publishedDate: "2026-09-26T00:00:00.000Z",
          highlights: ["After an insane number of simulated years"],
        },
        {
          title: "Tweet 1",
          url: "https://x.com/kepano/status/2078550254027477399",
          highlights: ["Shipping Defuddle CLI today."],
        },
        {
          title: "Tweet 1 mirror",
          url: "https://twitter.com/kepano/status/2078550254027477399?utm_source=share",
          highlights: ["Shipping Defuddle CLI today."],
        },
        {
          title: "Hono JWT",
          url: "http://www.hono.dev/docs/jwt/?utm_source=newsletter",
          highlights: ["Verify tokens with HS256."],
        },
        {
          title: "Hono JWT canonical",
          url: "https://hono.dev/docs/jwt",
          highlights: ["Verify tokens with HS256."],
        },
        { title: "Unique 4", url: "https://example.com/4", highlights: ["Fourth unique highlight."] },
        { title: "Unique 5", url: "https://example.com/5", highlights: ["Fifth unique highlight."] },
        {
          title: "Tail Shorts Alias",
          url: "https://www.youtube.com/shorts/9t2fV52jMA8",
          publishedDate: "2026-09-26T00:00:00.000Z",
          highlights: ["Ignored tail."],
        },
      ],
    });

    expect(formatSearchSections(body)).toEqual([
      "1. Running Minecraft Until It Beats Itself\nURL: https://youtu.be/9t2fV52jMA8\nAfter an insane number of simulated years, this world killed the Ender Dragon.",
      "2. Running Minecraft Until It Beats Itself\nURL: https://www.youtube.com/watch?v=9t2fV52jMA8&t=30s\nPublished: 2026-09-26\n[duplicate of #1 (https://youtu.be/9t2fV52jMA8): same URL; highlights omitted]",
      "3. Tweet 1\nURL: https://x.com/kepano/status/2078550254027477399\nShipping Defuddle CLI today.",
      "4. Tweet 1 mirror\nURL: https://twitter.com/kepano/status/2078550254027477399?utm_source=share\n[duplicate of #3 (https://x.com/kepano/status/2078550254027477399): same URL; highlights omitted]",
      "5. Hono JWT\nURL: http://www.hono.dev/docs/jwt/?utm_source=newsletter\nVerify tokens with HS256.",
      "6. Hono JWT canonical\nURL: https://hono.dev/docs/jwt\n[duplicate of #5 (http://www.hono.dev/docs/jwt/?utm_source=newsletter): same URL; highlights omitted]",
      "7. Unique 4\nURL: https://example.com/4\nFourth unique highlight.",
      "8. Unique 5\nURL: https://example.com/5\nFifth unique highlight.",
      "9. Tail Shorts Alias\nURL: https://www.youtube.com/shorts/9t2fV52jMA8\n[duplicate of #1 (https://youtu.be/9t2fV52jMA8): same URL]",
    ]);
  });

  test("omits identical highlights across multi-locale or syndicated URLs while reporting the earlier result and promoting the next unique result", () => {
    const body = JSON.stringify({
      results: [
        { title: "Doc 1", url: "https://example.com/1", highlights: ["Highlight 1"] },
        { title: "Doc 2", url: "https://example.com/2", highlights: ["Highlight 2"] },
        {
          title: "Micdoodle DE",
          url: "https://micdoodle8.com/de/minecraft-simulation/",
          publishedDate: "2026-09-21T00:00:00.000Z",
          highlights: ["YouTuber RedLogic ran a Monte Carlo simulation\nwith seed -535646876083114041."],
        },
        {
          title: "Micdoodle ES",
          url: "https://micdoodle8.com/es/minecraft-simulation/",
          publishedDate: "2026-09-21T00:00:00.000Z",
          highlights: ["YouTuber RedLogic ran a Monte Carlo simulation   with seed -535646876083114041."],
        },
        {
          title: "Micdoodle ES HTTP",
          url: "http://www.micdoodle8.com/es/minecraft-simulation",
          highlights: ["Different snippet from ES mirror"],
        },
        { title: "Doc 4", url: "https://example.com/4", highlights: ["Highlight 4"] },
        { title: "Doc 5 promoted", url: "https://example.com/5", highlights: ["Highlight 5"] },
        { title: "Tail A", url: "https://mirror-a.example.com/post", highlights: ["Shared tail passage"] },
        {
          title: "Tail B",
          url: "https://mirror-b.example.com/post",
          publishedDate: "2026-09-21T00:00:00.000Z",
          highlights: ["Shared tail passage"],
        },
      ],
    });

    expect(formatSearchSections(body)).toEqual([
      "1. Doc 1\nURL: https://example.com/1\nHighlight 1",
      "2. Doc 2\nURL: https://example.com/2\nHighlight 2",
      "3. Micdoodle DE\nURL: https://micdoodle8.com/de/minecraft-simulation/\nPublished: 2026-09-21\nYouTuber RedLogic ran a Monte Carlo simulation\nwith seed -535646876083114041.",
      "4. Micdoodle ES\nURL: https://micdoodle8.com/es/minecraft-simulation/\nPublished: 2026-09-21\n[duplicate of #3 (https://micdoodle8.com/de/minecraft-simulation/): identical highlights omitted]",
      "5. Micdoodle ES HTTP\nURL: http://www.micdoodle8.com/es/minecraft-simulation\n[duplicate of #4 (https://micdoodle8.com/es/minecraft-simulation/): same URL; highlights omitted]",
      "6. Doc 4\nURL: https://example.com/4\nHighlight 4",
      "7. Doc 5 promoted\nURL: https://example.com/5\nHighlight 5",
      "8. Tail A\nURL: https://mirror-a.example.com/post",
      "9. Tail B\nURL: https://mirror-b.example.com/post\n[duplicate of #8 (https://mirror-a.example.com/post): identical highlights]",
    ]);
  });

  test("preserves distinct non-tracking query parameters, ports, hash fragments, and empty-highlight items while deduplicating reordered query params", () => {
    const body = JSON.stringify({
      results: [
        { title: "HN 100", url: "https://news.ycombinator.com/item?id=100", highlights: ["Thread 100"] },
        { title: "HN 200", url: "https://news.ycombinator.com/item?id=200", highlights: ["Thread 200"] },
        {
          title: "Search sorted A",
          url: "http://www.example.com:8080/search/?tag=b&z=9&tag=a&a=1&FBCLID=track1&UTM_SOURCE=feed",
          highlights: ["Port 8080 result"],
        },
        {
          title: "Search sorted B",
          url: "https://example.com:8080/search?a=1&tag=a&tag=b&z=9",
          highlights: ["Port 8080 duplicate"],
        },
        {
          title: "Search sorted C empty",
          url: "https://example.com:8080/search?a=1&tag=a&tag=b&z=9",
          highlights: [],
        },
        {
          title: "Different port",
          url: "https://example.com:9090/search?a=1&tag=a&tag=b&z=9",
          highlights: ["Port 9090 result"],
        },
        { title: "Comment 1", url: "https://github.com/org/repo/issues/1#issuecomment-1", highlights: ["First comment"] },
        { title: "Comment 2", url: "https://github.com/org/repo/issues/1#issuecomment-2", highlights: ["Second comment"] },
        { title: "Empty A", url: "https://example.com/empty-a", highlights: [] },
        { title: "Empty B", url: "https://example.com/empty-b", highlights: [] },
      ],
      // highlightResults = 8 so all distinct entries above are within budget
    });

    expect(formatSearchSections(body, "", 8)).toEqual([
      "1. HN 100\nURL: https://news.ycombinator.com/item?id=100\nThread 100",
      "2. HN 200\nURL: https://news.ycombinator.com/item?id=200\nThread 200",
      "3. Search sorted A\nURL: http://www.example.com:8080/search/?tag=b&z=9&tag=a&a=1&FBCLID=track1&UTM_SOURCE=feed\nPort 8080 result",
      "4. Search sorted B\nURL: https://example.com:8080/search?a=1&tag=a&tag=b&z=9\n[duplicate of #3 (http://www.example.com:8080/search/?tag=b&z=9&tag=a&a=1&FBCLID=track1&UTM_SOURCE=feed): same URL; highlights omitted]",
      "5. Search sorted C empty\nURL: https://example.com:8080/search?a=1&tag=a&tag=b&z=9\n[duplicate of #3 (http://www.example.com:8080/search/?tag=b&z=9&tag=a&a=1&FBCLID=track1&UTM_SOURCE=feed): same URL]",
      "6. Different port\nURL: https://example.com:9090/search?a=1&tag=a&tag=b&z=9\nPort 9090 result",
      "7. Comment 1\nURL: https://github.com/org/repo/issues/1#issuecomment-1\nFirst comment",
      "8. Comment 2\nURL: https://github.com/org/repo/issues/1#issuecomment-2\nSecond comment",
      "9. Empty A\nURL: https://example.com/empty-a",
      "10. Empty B\nURL: https://example.com/empty-b",
    ]);
  });

  test("recovers highlights when the first same-URL entry had none and deduplicates subsequent URL or highlight clones against the recovered entry", () => {
    const body = JSON.stringify({
      results: [
        { title: "Shortlink empty", url: "https://youtu.be/9t2fV52jMA8", highlights: [] },
        {
          title: "Watch with transcript",
          url: "https://www.youtube.com/watch?v=9t2fV52jMA8",
          publishedDate: "2026-09-26T00:00:00.000Z",
          highlights: ["Recovered transcript from watch URL."],
        },
        {
          title: "Mobile watch",
          url: "https://m.youtube.com/watch?v=9t2fV52jMA8",
          highlights: ["Shorter mobile excerpt."],
        },
        {
          title: "Syndicated mirror",
          url: "https://mirror.example.com/post",
          highlights: ["Recovered transcript from watch URL."],
        },
      ],
    });

    expect(formatSearchSections(body)).toEqual([
      "1. Shortlink empty\nURL: https://youtu.be/9t2fV52jMA8",
      "2. Watch with transcript\nURL: https://www.youtube.com/watch?v=9t2fV52jMA8\nPublished: 2026-09-26\n[same URL as #1 (https://youtu.be/9t2fV52jMA8)]\nRecovered transcript from watch URL.",
      "3. Mobile watch\nURL: https://m.youtube.com/watch?v=9t2fV52jMA8\n[duplicate of #2 (https://www.youtube.com/watch?v=9t2fV52jMA8): same URL; highlights omitted]",
      "4. Syndicated mirror\nURL: https://mirror.example.com/post\n[duplicate of #2 (https://www.youtube.com/watch?v=9t2fV52jMA8): identical highlights omitted]",
    ]);
  });

  test("omits recovered same-URL highlights when another result already printed identical highlights and refunds the unused highlight slot", () => {
    const body = JSON.stringify({
      results: [
        { title: "Shortlink empty", url: "https://youtu.be/9t2fV52jMA8", highlights: [] },
        { title: "Mirror blog", url: "https://blog.example.com/post", highlights: ["Exact transcript."] },
        {
          title: "Watch alias",
          url: "https://www.youtube.com/watch?v=9t2fV52jMA8",
          publishedDate: "2026-09-26T00:00:00.000Z",
          highlights: ["Exact transcript."],
        },
        { title: "Mobile alias", url: "https://m.youtube.com/watch?v=9t2fV52jMA8", highlights: ["Exact transcript."] },
        { title: "Unique 2", url: "https://example.com/u2", highlights: ["Passage 2"] },
        { title: "Unique 3", url: "https://example.com/u3", highlights: ["Passage 3"] },
        { title: "Unique 4", url: "https://example.com/u4", highlights: ["Passage 4"] },
        { title: "Unique 5 promoted", url: "https://example.com/u5", highlights: ["Passage 5"] },
      ],
    });

    expect(formatSearchSections(body)).toEqual([
      "1. Shortlink empty\nURL: https://youtu.be/9t2fV52jMA8",
      "2. Mirror blog\nURL: https://blog.example.com/post\nExact transcript.",
      "3. Watch alias\nURL: https://www.youtube.com/watch?v=9t2fV52jMA8\nPublished: 2026-09-26\n[same URL as #1 (https://youtu.be/9t2fV52jMA8); duplicate of #2 (https://blog.example.com/post): identical highlights omitted]",
      "4. Mobile alias\nURL: https://m.youtube.com/watch?v=9t2fV52jMA8\n[duplicate of #3 (https://www.youtube.com/watch?v=9t2fV52jMA8): same URL; highlights omitted]",
      "5. Unique 2\nURL: https://example.com/u2\nPassage 2",
      "6. Unique 3\nURL: https://example.com/u3\nPassage 3",
      "7. Unique 4\nURL: https://example.com/u4\nPassage 4",
      "8. Unique 5 promoted\nURL: https://example.com/u5\nPassage 5",
    ]);
  });

  test("points later tail duplicates to the result that actually displayed recovered highlights rather than an earlier unshown tail item", () => {
    const body = JSON.stringify({
      results: [
        { title: "Shortlink empty", url: "https://youtu.be/9t2fV52jMA8", highlights: [] },
        { title: "U1", url: "https://example.com/1", highlights: ["H1"] },
        { title: "U2", url: "https://example.com/2", highlights: ["H2"] },
        { title: "U3", url: "https://example.com/3", highlights: ["H3"] },
        { title: "U4", url: "https://example.com/4", highlights: ["H4"] },
        { title: "Unshown tail mirror A", url: "https://mirror-a.example.com/post", highlights: ["Shared transcript"] },
        { title: "Late watch recovery", url: "https://www.youtube.com/watch?v=9t2fV52jMA8", highlights: ["Shared transcript"] },
        { title: "Tail mirror B", url: "https://mirror-b.example.com/post", highlights: ["Shared transcript"] },
      ],
    });

    expect(formatSearchSections(body)).toEqual([
      "1. Shortlink empty\nURL: https://youtu.be/9t2fV52jMA8",
      "2. U1\nURL: https://example.com/1\nH1",
      "3. U2\nURL: https://example.com/2\nH2",
      "4. U3\nURL: https://example.com/3\nH3",
      "5. U4\nURL: https://example.com/4\nH4",
      "6. Unshown tail mirror A\nURL: https://mirror-a.example.com/post",
      "7. Late watch recovery\nURL: https://www.youtube.com/watch?v=9t2fV52jMA8\n[same URL as #1 (https://youtu.be/9t2fV52jMA8)]\nShared transcript",
      "8. Tail mirror B\nURL: https://mirror-b.example.com/post\n[duplicate of #7 (https://www.youtube.com/watch?v=9t2fV52jMA8): identical highlights]",
    ]);
  });

  test("refunds a reserved highlight slot after slotsUsed hits the cap and promotes a later mirror without suppressing against unshown tail items", () => {
    const lateMirror = JSON.stringify({
      results: [
        { title: "Shortlink empty", url: "https://youtu.be/9t2fV52jMA8", highlights: [] },
        { title: "Mirror blog", url: "https://blog.example.com/post", highlights: ["Exact transcript."] },
        { title: "Unique 2", url: "https://example.com/u2", highlights: ["Passage 2"] },
        { title: "Unique 3", url: "https://example.com/u3", highlights: ["Passage 3"] },
        { title: "Unique 4", url: "https://example.com/u4", highlights: ["Passage 4"] },
        { title: "Unshown tail A", url: "https://mirror-a.example.com/u5", highlights: ["Passage 5"] },
        { title: "Unshown tail B", url: "https://mirror-b.example.com/u5", highlights: ["Passage 5"] },
        {
          title: "Watch alias at rank 8",
          url: "https://www.youtube.com/watch?v=9t2fV52jMA8",
          publishedDate: "2026-09-26T00:00:00.000Z",
          highlights: ["Exact transcript."],
        },
        { title: "Promoted mirror C", url: "https://mirror-c.example.com/u5", highlights: ["Passage 5"] },
        { title: "Tail mirror D", url: "https://mirror-d.example.com/u5", highlights: ["Passage 5"] },
      ],
    });

    expect(formatSearchSections(lateMirror)).toEqual([
      "1. Shortlink empty\nURL: https://youtu.be/9t2fV52jMA8",
      "2. Mirror blog\nURL: https://blog.example.com/post\nExact transcript.",
      "3. Unique 2\nURL: https://example.com/u2\nPassage 2",
      "4. Unique 3\nURL: https://example.com/u3\nPassage 3",
      "5. Unique 4\nURL: https://example.com/u4\nPassage 4",
      "6. Unshown tail A\nURL: https://mirror-a.example.com/u5",
      "7. Unshown tail B\nURL: https://mirror-b.example.com/u5\n[duplicate of #6 (https://mirror-a.example.com/u5): identical highlights]",
      "8. Watch alias at rank 8\nURL: https://www.youtube.com/watch?v=9t2fV52jMA8\nPublished: 2026-09-26\n[same URL as #1 (https://youtu.be/9t2fV52jMA8); duplicate of #2 (https://blog.example.com/post): identical highlights omitted]",
      "9. Promoted mirror C\nURL: https://mirror-c.example.com/u5\nPassage 5",
      "10. Tail mirror D\nURL: https://mirror-d.example.com/u5\n[duplicate of #9 (https://mirror-c.example.com/u5): identical highlights]",
    ]);
  });

  test("recovers highlights for a same-URL alias of an unshown tail item when a late slot refund reopens the budget", () => {
    const lateSameUrl = JSON.stringify({
      results: [
        { title: "Shortlink empty", url: "https://youtu.be/9t2fV52jMA8", highlights: [] },
        { title: "Mirror blog", url: "https://blog.example.com/post", highlights: ["Exact transcript."] },
        { title: "Unique 2", url: "https://example.com/u2", highlights: ["Passage 2"] },
        { title: "Unique 3", url: "https://example.com/u3", highlights: ["Passage 3"] },
        { title: "Unique 4", url: "https://example.com/u4", highlights: ["Passage 4"] },
        { title: "Unshown doc", url: "https://example.com/u5", highlights: ["Passage 5"] },
        {
          title: "Watch alias at rank 7",
          url: "https://www.youtube.com/watch?v=9t2fV52jMA8",
          highlights: ["Exact transcript."],
        },
        { title: "Reopened same-URL alias", url: "http://www.example.com/u5/", highlights: ["Passage 5"] },
      ],
    });

    expect(formatSearchSections(lateSameUrl)).toEqual([
      "1. Shortlink empty\nURL: https://youtu.be/9t2fV52jMA8",
      "2. Mirror blog\nURL: https://blog.example.com/post\nExact transcript.",
      "3. Unique 2\nURL: https://example.com/u2\nPassage 2",
      "4. Unique 3\nURL: https://example.com/u3\nPassage 3",
      "5. Unique 4\nURL: https://example.com/u4\nPassage 4",
      "6. Unshown doc\nURL: https://example.com/u5",
      "7. Watch alias at rank 7\nURL: https://www.youtube.com/watch?v=9t2fV52jMA8\n[same URL as #1 (https://youtu.be/9t2fV52jMA8); duplicate of #2 (https://blog.example.com/post): identical highlights omitted]",
      "8. Reopened same-URL alias\nURL: http://www.example.com/u5/\n[same URL as #6 (https://example.com/u5)]\nPassage 5",
    ]);
  });

  test("normalizes X/Twitter profile and article URLs, non-HTTP raw schemes without namespace collisions, and missing-URL duplicate references", () => {
    const body = JSON.stringify({
      results: [
        { title: "Profile Twitter", url: "https://twitter.com/RedLogicP", highlights: ["Creator bio"] },
        { title: "Profile Mobile X", url: "https://mobile.x.com/RedLogicP/", highlights: ["Creator bio"] },
        { title: "X Article", url: "https://x.com/kepano/article/2078550254027477399", highlights: ["Longform note"] },
        { title: "X Web Status", url: "https://mobile.twitter.com/i/web/status/2078550254027477399", highlights: ["Longform note"] },
        { title: "Untitled 1", highlights: ["No-URL passage"] },
        { title: "Untitled 2", highlights: ["No-URL passage"] },
        { title: "YouTube real", url: "https://youtu.be/9t2fV52jMA8", highlights: ["Video body"] },
        { title: "Custom yt scheme", url: "yt:9t2fV52jMA8", highlights: ["Distinct non-HTTP URI"] },
        { title: "Malformed URL", url: "not a url", highlights: ["Raw text"] },
      ],
      // highlightResults = 7 so all 7 unique entries display highlights
    });

    expect(formatSearchSections(body, "", 7)).toEqual([
      "1. Profile Twitter\nURL: https://twitter.com/RedLogicP\nCreator bio",
      "2. Profile Mobile X\nURL: https://mobile.x.com/RedLogicP/\n[duplicate of #1 (https://twitter.com/RedLogicP): same URL; highlights omitted]",
      "3. X Article\nURL: https://x.com/kepano/article/2078550254027477399\nLongform note",
      "4. X Web Status\nURL: https://mobile.twitter.com/i/web/status/2078550254027477399\n[duplicate of #3 (https://x.com/kepano/article/2078550254027477399): same URL; highlights omitted]",
      "5. Untitled 1\nNo-URL passage",
      "6. Untitled 2\n[duplicate of #5: identical highlights omitted]",
      "7. YouTube real\nURL: https://youtu.be/9t2fV52jMA8\nVideo body",
      "8. Custom yt scheme\nURL: yt:9t2fV52jMA8\nDistinct non-HTTP URI",
      "9. Malformed URL\nURL: not a url\nRaw text",
    ]);
  });

  test("normalizes YouTube /watch///, nocookie /embed/, and utm_* params while keeping /embed/videoseries, /embed/live_stream, and multi-segment paths separate", () => {
    const body = JSON.stringify({
      results: [
        { title: "Watch slash", url: "https://www.youtube.com/watch///?v=9t2fV52jMA8&utm_source_platform=google", highlights: ["Clip body"] },
        { title: "Nocookie embed", url: "https://www.youtube-nocookie.com/embed/9t2fV52jMA8", highlights: ["Embed body"] },
        { title: "Subpath not video", url: "https://www.youtube.com/live/9t2fV52jMA8/chat", highlights: ["Live chat subpage"] },
        { title: "GA4 tagged", url: "https://hono.dev/docs/jwt?utm_campaign_id=99&utm_marketing_tactic=launch", highlights: ["JWT guide"] },
        { title: "Clean doc", url: "https://hono.dev/docs/jwt", highlights: ["Updated excerpt"] },
        { title: "Playlist A", url: "https://www.youtube.com/embed/videoseries?list=PL_ALPHA", highlights: ["Alpha tracks"] },
        { title: "Playlist B", url: "https://www.youtube.com/embed/videoseries?list=PL_BETA", highlights: ["Beta tracks"] },
        { title: "Live channel A", url: "https://www.youtube.com/embed/live_stream?channel=UC_ALPHA", highlights: ["Stream A"] },
        { title: "Live channel B", url: "https://www.youtube.com/embed/live_stream?channel=UC_BETA", highlights: ["Stream B"] },
      ],
    });

    expect(formatSearchSections(body, "", 7)).toEqual([
      "1. Watch slash\nURL: https://www.youtube.com/watch///?v=9t2fV52jMA8&utm_source_platform=google\nClip body",
      "2. Nocookie embed\nURL: https://www.youtube-nocookie.com/embed/9t2fV52jMA8\n[duplicate of #1 (https://www.youtube.com/watch///?v=9t2fV52jMA8&utm_source_platform=google): same URL; highlights omitted]",
      "3. Subpath not video\nURL: https://www.youtube.com/live/9t2fV52jMA8/chat\nLive chat subpage",
      "4. GA4 tagged\nURL: https://hono.dev/docs/jwt?utm_campaign_id=99&utm_marketing_tactic=launch\nJWT guide",
      "5. Clean doc\nURL: https://hono.dev/docs/jwt\n[duplicate of #4 (https://hono.dev/docs/jwt?utm_campaign_id=99&utm_marketing_tactic=launch): same URL; highlights omitted]",
      "6. Playlist A\nURL: https://www.youtube.com/embed/videoseries?list=PL_ALPHA\nAlpha tracks",
      "7. Playlist B\nURL: https://www.youtube.com/embed/videoseries?list=PL_BETA\nBeta tracks",
      "8. Live channel A\nURL: https://www.youtube.com/embed/live_stream?channel=UC_ALPHA\nStream A",
      "9. Live channel B\nURL: https://www.youtube.com/embed/live_stream?channel=UC_BETA\nStream B",
    ]);
  });

  test("degrades safely on non-object JSON payloads, malformed result fields, and control bytes in duplicate URL labels", () => {
    expect(formatSearchSections("null")).toEqual(["null"]);
    expect(formatSearchSections('{"results":"invalid"}')).toEqual(['{"results":"invalid"}']);

    const dirty = JSON.stringify({
      results: [
        null,
        {
          title: 123,
          url: "https://youtu.be/9t2fV5\n2jMA8?u=\x1b",
          publishedDate: 1727308800,
          highlights: [null, "  Clean passage  ", 42],
        },
        {
          title: "Watch clean",
          url: "https://www.youtube.com/watch?v=9t2fV52jMA8",
          highlights: ["Second passage"],
        },
        {
          title: "Numeric URL",
          url: 999,
          highlights: "not-an-array",
        },
      ],
    });

    expect(formatSearchSections(dirty)).toEqual([
      "1. https://youtu.be/9t2fV5\n2jMA8?u=\x1b\nURL: https://youtu.be/9t2fV5\n2jMA8?u=\x1b\nClean passage",
      "2. Watch clean\nURL: https://www.youtube.com/watch?v=9t2fV52jMA8\n[duplicate of #1 (https://youtu.be/9t2fV52jMA8?u=): same URL; highlights omitted]",
      "3. Numeric URL",
    ]);
  });
});

describe("fetchDirectMarkdown", () => {
  test("fetches YAML, JSON, and TOML across standard, +suffix, and legacy MIME types without parsing comments or YAML streams as Markdown titles", async () => {
    const cases = [
      {
        url: "https://opencode.ai/update/latest.yml",
        ct: "application/yaml; charset=utf-8",
        body: '---\ntitle: "not-frontmatter"\n---\n# generated by CI\nversion: 2.0.32\n',
      },
      {
        url: "https://crates.io/api/v1/crates/symphonia",
        ct: "application/json; charset=utf-8",
        body: '  {"crate":{"id":"symphonia","max_version":"0.5.4"}}  ',
      },
      {
        url: "https://api.github.com/repos/honojs/hono",
        ct: "application/vnd.github+json",
        body: '{"full_name":"honojs/hono"}',
      },
      {
        url: "https://api.example.com/spec",
        ct: "application/openapi+yaml",
        body: "openapi: 3.1.0\ninfo:\n  title: Spec",
      },
      {
        url: "https://cdn.example.com/Cargo.toml",
        ct: "application/toml",
        body: '# optional: fast kernel\n[package]\nname = "worldsmith"\n',
      },
      {
        url: "https://legacy.example.com/config.yml",
        ct: "text/x-yaml",
        body: "# legacy yaml\nport: 8080",
      },
      {
        url: "https://legacy.example.com/settings.toml",
        ct: "text/toml; charset=utf-8",
        body: '# legacy toml\nmode = "strict"',
      },
    ];

    for (const c of cases) {
      const item = await fetchDirectMarkdown(c.url, async () => new Response(c.body, { headers: { "content-type": c.ct } }));
      expect(item).toEqual({ url: c.url, title: c.url, text: c.body.trim() });
    }
  });

  test("fetches .yml, .yaml, .json, and .toml URLs served as octet-stream or text/plain while rejecting HTML shells and NUL-byte binaries", async () => {
    const toml = '# comment on top\n[tool.ruff]\nline-length = 100';
    const fromRaw = await fetchDirectMarkdown(
      "https://raw.githubusercontent.com/org/repo/main/pyproject.toml",
      async () => new Response(toml, { headers: { "content-type": "text/plain; charset=utf-8" } }),
    );
    expect(fromRaw).toEqual({
      url: "https://raw.githubusercontent.com/org/repo/main/pyproject.toml",
      title: "https://raw.githubusercontent.com/org/repo/main/pyproject.toml",
      text: toml,
    });

    const redirectedRes = new Response("version: 1.2.3", { headers: { "content-type": "application/octet-stream" } });
    Object.defineProperty(redirectedRes, "url", { value: "https://objects.githubusercontent.com/release-asset-blob?sig=1" });
    const fromOctet = await fetchDirectMarkdown(
      "https://github.com/org/repo/releases/latest/download/latest.yml",
      async () => redirectedRes,
    );
    expect(fromOctet).toEqual({
      url: "https://github.com/org/repo/releases/latest/download/latest.yml",
      title: "https://github.com/org/repo/releases/latest/download/latest.yml",
      text: "version: 1.2.3",
    });

    const htmlDisguised = await fetchDirectMarkdown(
      "https://cdn.example.com/config.json",
      async () => new Response("<!DOCTYPE html><html><body>Login</body></html>", { headers: { "content-type": "application/json" } }),
    );
    expect(htmlDisguised).toBeUndefined();

    const binaryDisguised = await fetchDirectMarkdown(
      "https://cdn.example.com/archive.yml",
      async () => new Response("PK\x03\x04\x00binary", { headers: { "content-type": "application/octet-stream" } }),
    );
    expect(binaryDisguised).toBeUndefined();
  });

  test("includes a wildcard Accept fallback after text/markdown and text/html so strict data endpoints do not return 406", async () => {
    let accept = "";
    await fetchDirectMarkdown("https://api.example.com/data.json", async (_url, init) => {
      accept = ((init?.headers as Record<string, string>) ?? {}).Accept ?? "";
      return new Response('{"ok":true}', { headers: { "content-type": "application/json" } });
    });

    expect(accept).toStartWith("text/markdown, text/html;q=0.9");
    expect(accept).toContain("*/*");
  });

  test("returns undefined when extracted HTML is under 200 chars and keeps HTML at or above 200 chars", async () => {
    const htmlWithBody = (text: string) =>
      `<!DOCTYPE html><html><head><title>Doc</title></head><body><main><article><p>${text}</p></article></main></body></html>`;

    const stubRedirect = `<!doctype html><title>Redirecting to: /docs/rules</title><meta http-equiv="refresh" content="0;url=/docs/rules"><body><a href="/docs/rules">Redirecting from <code>/docs/rules-workflows/</code> to <code>/docs/rules</code></a></body>`;
    expect(
      await fetchDirectMarkdown("https://antigravity.google/docs/rules-workflows", async () =>
        new Response(stubRedirect, { headers: { "content-type": "text/html" } }),
      ),
    ).toBeUndefined();

    expect(
      await fetchDirectMarkdown("https://example.com/short", async () =>
        new Response(htmlWithBody("a".repeat(199)), { headers: { "content-type": "text/html" } }),
      ),
    ).toBeUndefined();

    const exact200 = await fetchDirectMarkdown("https://example.com/full", async () =>
      new Response(htmlWithBody("b".repeat(200)), { headers: { "content-type": "text/html" } }),
    );
    expect(exact200).toEqual({
      url: "https://example.com/full",
      title: "Doc",
      text: "b".repeat(200),
    });
  });

  test("still keeps short Markdown, GitHub blobs, and X status posts under 200 chars without falling back", async () => {
    const md = await fetchDirectMarkdown("https://docs.example.com/tsconfig.json", async () =>
      new Response("# tsconfig.json\n\nShort doc.", { headers: { "content-type": "text/markdown; charset=utf-8" } }),
    );
    expect(md).toEqual({
      url: "https://docs.example.com/tsconfig.json",
      title: "tsconfig.json",
      text: "# tsconfig.json\n\nShort doc.",
    });

    const blobHtml = `<!DOCTYPE html><html><head><title>repo/package.json at main · org/repo</title></head><body>
      <script type="application/json" data-target="react-app.embeddedData">${JSON.stringify({
        payload: { blob: { rawLines: ['{"name":"tiny"}'] } },
      })}</script></body></html>`;
    const blob = await fetchDirectMarkdown("https://github.com/org/repo/blob/main/package.json", async () =>
      new Response(blobHtml, { headers: { "content-type": "text/html; charset=utf-8" } }),
    );
    expect(blob?.text).toBe('```json\n{"name":"tiny"}\n```');

    const tweet = await fetchDirectMarkdown("https://x.com/kepano/status/2078550254027477399", async (u) => {
      if (u.includes("api.fxtwitter.com")) {
        return new Response(
          JSON.stringify({
            code: 200,
            tweet: { text: "Short tweet.", author: { name: "Steph", screen_name: "kepano" }, created_timestamp: 1752600000 },
          }),
          { headers: { "content-type": "application/json" } },
        );
      }
      return new Response("<!DOCTYPE html><html><body></body></html>", { headers: { "content-type": "text/html" } });
    });
    expect(tweet?.text).toContain("Short tweet.");
  });
});

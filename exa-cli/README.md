# exa-cli (`exa`)

Standalone Exa search CLI built on Bun/TypeScript with automatic multi-API-key failover (`401` invalid key, `402` credits exhausted, `429` rate limited). `exa --help` is the full manual.

## Install

```bash
bun install
bun link
```

## Usage

```bash
exa search "Hono JWT middleware reading the token from a cookie"
exa search "Durable Objects alarm retries" --include-domains developers.cloudflare.com
exa fetch https://hono.dev/docs/middleware/builtin/jwt https://github.com/honojs/hono/blob/main/src/middleware/jwt/jwt.ts
exa fetch https://hono.dev/docs/middleware/builtin/jwt -o /tmp/hono-jwt.md
exa status
```

Search defaults to 10 results (first 5 with full highlights, remaining with title + URL) with bare `highlights: true` and `type: fast` instead of `auto`: on 40 agent-style queries `fast` found the same answers and ranked official sources at least as high while running ~9x faster (~0.5s vs ~4.4s) at the same price (Exa's base search price covers up to 10 results). Highlights are excerpts that can elide text with " ... ", so `exa fetch` returns the full page as markdown using a 3-tier pipeline: (1) requests `Accept: text/markdown` directly from the origin when the server returns `text/markdown` or `text/plain`, (2) parses HTML (and X/Twitter or GitHub SSR pages) locally with Defuddle + LinkeDOM to preserve `<Type>` generics and code block formatting without spending Exa credits, and (3) falls back to Exa `/contents` (`text: true`) only when local extraction yields no content. `fetch` and `--json` stdout are capped at 26000 chars by default. Multi-page `fetch` output past the cap fills the full 26000-char budget and lists the title and URL of both the cut result and any hidden results below the truncation note. Use `-o <file>` to save the full output.

## Keys

Keys are tried in order. Edit `~/.config/exa/config.json` (the bundled `config.json` is used when that file does not exist). Without a config file, the CLI reads `EXA_API_KEYS` (comma-separated) or `EXA_API_KEY`.

```json
{ "keys": [{ "label": "personal", "value": "00000000-0000-0000-0000-000000000000" }] }
```

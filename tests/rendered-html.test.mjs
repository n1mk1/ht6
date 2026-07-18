import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the LaunchKit product shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>LaunchKit — Full-stack AI boilerplate<\/title>/i);
  assert.match(html, /Skip the setup\./);
  assert.match(html, /Gemini playground/);
  assert.match(html, /Atlas notes/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("keeps public and secret configuration separated", async () => {
  const [clientConfig, frontendEnv, backendEnv] = await Promise.all([
    readFile(new URL("../app/client-config.ts", import.meta.url), "utf8"),
    readFile(new URL("../.env.example", import.meta.url), "utf8"),
    readFile(new URL("../backend/.env.example", import.meta.url), "utf8"),
  ]);

  assert.match(clientConfig, /NEXT_PUBLIC_AUTH0_CLIENT_ID/);
  assert.match(frontendEnv, /NEXT_PUBLIC_API_URL/);
  assert.doesNotMatch(frontendEnv, /GEMINI_API_KEY|MONGODB_URI/);
  assert.match(backendEnv, /GEMINI_API_KEY/);
  assert.match(backendEnv, /MONGODB_URI/);
});

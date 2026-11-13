// The API client: tokens in memory only, one refresh at a time, readable errors.
import { test } from "node:test";
import assert from "node:assert/strict";

const calls = [];
let refreshes = 0;
let accessOk = "a2";
globalThis.localStorage = { setItem: () => assert.fail("must not touch localStorage") };
globalThis.fetch = async (url, init) => {
  calls.push([url, init.method, init.headers.Authorization]);
  const json = (status, body) => ({ status, ok: status < 400, json: async () => body });
  if (url.endsWith("/auth/refresh")) {
    refreshes += 1;
    await new Promise((r) => setTimeout(r, 20));
    const sent = JSON.parse(init.body).refresh_token;
    return sent === "r1" ? json(200, { access_token: "a2", refresh_token: "r2" }) : json(401, {});
  }
  if (url.includes("/admin/fail")) return json(422, { detail: [{ loc: ["body", "days"], msg: "too big" }] });
  if (url.includes("/admin/boom")) return json(409, { error: { code: "conflict", message: "Already there." } });
  return init.headers.Authorization === `Bearer ${accessOk}` ? json(200, { ok: true }) : json(401, {});
};

const { api, session, ApiError } = await import("../src/api.js");

test("expired access token: one refresh for parallel requests, then retried", async () => {
  session.set({ access_token: "a1", refresh_token: "r1" });
  const [a, b] = await Promise.all([api("/admin/x"), api("/admin/y")]);
  assert.deepEqual(a, { ok: true });
  assert.deepEqual(b, { ok: true });
  assert.equal(refreshes, 1, "the rotating refresh token must be used once");
  assert.equal(calls.filter(([, , auth]) => auth === "Bearer a2").length, 2);
});

test("errors carry the server's message", async () => {
  await assert.rejects(api("/admin/fail"), (e) => e instanceof ApiError && e.status === 422 && e.message === "days: too big");
  await assert.rejects(api("/admin/boom"), (e) => e.code === "conflict" && e.message === "Already there.");
});

test("a failed refresh ends the session and tells the app", async () => {
  let expired = 0;
  session.onExpired(() => { expired += 1; });
  accessOk = "never";
  await assert.rejects(api("/admin/z"), (e) => e.status === 401);
  assert.equal(expired, 1);
  assert.equal(session.active, false);
});

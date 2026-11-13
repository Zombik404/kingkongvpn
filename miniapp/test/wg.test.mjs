import { test } from "node:test";
import assert from "node:assert/strict";
import { buildConfig, clamp, fromFragment, generateKeyPair, publicKeyFor, toFragment, tunnelName, b64decode } from "../src/wg.js";

test("public key matches WireGuard/libsodium X25519 (reference from Python cryptography)", () => {
  const priv = b64decode("AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=");
  assert.equal(publicKeyFor(priv), "B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw=");
  // clamping doesn't change the public key (X25519 clamps internally)
  assert.equal(publicKeyFor(clamp(priv)), "B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw=");
});

test("generated keys are 32-byte, clamped, base64 44 chars", () => {
  const seen = new Set();
  for (let i = 0; i < 50; i++) {
    const kp = generateKeyPair();
    assert.equal(kp.privateKey.length, 44);
    assert.equal(kp.publicKey.length, 44);
    const p = b64decode(kp.privateKey);
    assert.equal(p[0] & 7, 0);
    assert.equal(p[31] & 128, 0);
    assert.equal(p[31] & 64, 64);
    assert.equal(publicKeyFor(p), kp.publicKey);
    seen.add(kp.privateKey);
  }
  assert.equal(seen.size, 50);
});

test("config format", () => {
  const conf = buildConfig("PRIV=", {
    addresses: ["10.64.0.16/32", "fd00:6476:706e::10/128"], dns: ["1.1.1.1", "2606:4700:4700::1111"],
    server_public_key: "SRV=", allowed_ips: ["0.0.0.0/0", "::/0"], endpoint: "203.0.113.5:51820",
    persistent_keepalive: 25,
  });
  assert.equal(conf, [
    "[Interface]", "PrivateKey = PRIV=", "Address = 10.64.0.16/32, fd00:6476:706e::10/128",
    "DNS = 1.1.1.1, 2606:4700:4700::1111", "", "[Peer]", "PublicKey = SRV=",
    "AllowedIPs = 0.0.0.0/0, ::/0", "Endpoint = 203.0.113.5:51820", "PersistentKeepalive = 25", "",
  ].join("\n"));
});

test("tunnel names and fragments", () => {
  assert.equal(tunnelName("GlobalVPN", "DE"), "GlobalVPN-de");
  assert.equal(tunnelName("A very long name!", "NL").length <= 15, true);
  assert.match(tunnelName("Глобал", "DE"), /^[A-Za-z0-9_=+.-]+$/);
  const text = "[Interface]\nPrivateKey = a+b/c==\n";
  const frag = toFragment(text);
  assert.doesNotMatch(frag, /[+/=]/);
  assert.equal(fromFragment(frag), text);
});

import { arcPath, formatBytes, scalePoints, smoothPath } from "../src/charts.js";

test("chart helpers", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(5 * 1024 ** 3, "ru"), "5 ГБ");
  const pts = scalePoints([0, 10, 5], 100, 50, { l: 0, r: 0, t: 0, b: 0 });
  assert.deepEqual(pts, [[0, 50], [50, 0], [100, 25]]);
  const d = smoothPath(pts);
  assert.match(d, /^M0\.0,50\.0 C/);
  // monotone: control points never go above the peak (y < 0) or below the floor (y > 50)
  for (const n of d.match(/-?\d+\.\d/g).map(Number)) assert.ok(n >= 0 && n <= 100);
  assert.equal(smoothPath([]), "");
  assert.match(arcPath(50, 50, 40, 0.25), /^M50,10 A40,40 0 0 1 90\.00,50\.00$/);
  assert.match(arcPath(50, 50, 40, 1), / 0 1 1 /); // full circle uses the large-arc flag
});

// ---- provably fair: the device's shuffle must equal the server's (backend/app/games/fair.py)
import { dealMatches, shuffledShoe, verifyRound } from "../src/fair.js";

test("fair shuffle matches the server's known vector", async () => {
  // python: fair.shuffled_shoe("a"*64, "0=abc", 3, 6)[:8]
  const shoe = await shuffledShoe("a".repeat(64), "0=abc", 3, 6);
  assert.equal(shoe.slice(0, 8).join(" "), "KH KD 8C JS 3C 9C QH 6C");
  assert.equal(shoe.length, 312);
});

test("deal check: right round passes, another round or a swapped card fails", async () => {
  const shoe = await shuffledShoe("a".repeat(64), "0=abc", 3, 6); // KH KD 8C JS 3C 9C …
  // one seat: first KH, dealer up KD, second 8C, hole JS; the player then draws 3C
  const summary = { seats: [{ hands: [{ cards: ["KH", "8C", "3C"] }] }], dealer: { cards: ["KD", "JS"] } };
  assert.equal(dealMatches(shoe, summary), true);
  assert.equal(dealMatches(shoe, { ...summary, dealer: { cards: ["JS", "KD"] } }), false);
  assert.equal(dealMatches(shoe, { ...summary, seats: [{ hands: [{ cards: ["KH", "8C", "9C"] }] }] }), false);
  const { createHash } = await import("node:crypto");
  const f = { server_seed: "a".repeat(64), server_seed_hash: createHash("sha256").update("a".repeat(64)).digest("hex"), client_seed: "0=abc", number: 3, decks: 6, summary };
  assert.deepEqual(await verifyRound(f), { ok: true, hashOk: true, dealOk: true });
  assert.equal((await verifyRound({ ...f, server_seed_hash: "00" })).ok, false);
  assert.equal((await verifyRound({ ...f, server_seed: null })).ok, false);
});

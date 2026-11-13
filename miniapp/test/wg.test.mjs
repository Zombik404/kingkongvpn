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

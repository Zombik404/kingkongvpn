// WireGuard key generation and config building — runs only on the user's device (ADR-003).
// The private key never leaves this page: only the public key is sent to the API.
import { x25519 } from "@noble/curves/ed25519";

export function b64encode(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

export function b64decode(str) {
  const bin = atob(str);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Clamp like `wg genkey` does (RFC 7748), so the stored key is canonical. */
export function clamp(priv) {
  const k = Uint8Array.from(priv);
  k[0] &= 248;
  k[31] &= 127;
  k[31] |= 64;
  return k;
}

export function publicKeyFor(privBytes) {
  return b64encode(x25519.getPublicKey(privBytes));
}

export function generateKeyPair(random = (n) => crypto.getRandomValues(new Uint8Array(n))) {
  const priv = clamp(random(32));
  return { privateKey: b64encode(priv), publicKey: publicKeyFor(priv) };
}

/** Build a wg-quick config. `info` is the /vpn/connect response. */
export function buildConfig(privateKey, info) {
  const lines = [
    "[Interface]",
    `PrivateKey = ${privateKey}`,
    `Address = ${info.addresses.join(", ")}`,
  ];
  if (info.dns && info.dns.length) lines.push(`DNS = ${info.dns.join(", ")}`);
  lines.push(
    "",
    "[Peer]",
    `PublicKey = ${info.server_public_key}`,
    `AllowedIPs = ${info.allowed_ips.join(", ")}`,
    `Endpoint = ${info.endpoint}`,
  );
  if (info.persistent_keepalive) lines.push(`PersistentKeepalive = ${info.persistent_keepalive}`);
  return lines.join("\n") + "\n";
}

/** Tunnel/file name WireGuard apps accept: ≤15 chars of [A-Za-z0-9_=+.-]. */
export function tunnelName(prefix, countryCode) {
  const clean = (s) => String(s || "").replace(/[^A-Za-z0-9_=+.-]/g, "");
  const name = `${clean(prefix)}-${clean(countryCode).toLowerCase()}`.slice(0, 15);
  return name.replace(/-$/, "") || "vpn";
}

// base64url without padding, for passing a config in a URL fragment (never sent to servers).
export function toFragment(text) {
  return b64encode(new TextEncoder().encode(text)).replace(/\+/g, "-").replace(/\//g, "_")
    .replace(/=+$/, "");
}

export function fromFragment(frag) {
  const b64 = frag.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  return new TextDecoder().decode(b64decode(padded));
}

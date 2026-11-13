// Provably fair check, run on the player's device. The shuffle is the same as the server's
// (backend/app/games/fair.py): Fisher–Yates over the canonical shoe, driven by
// HMAC-SHA256(server_seed, "client_seed:nonce:counter") read as 32-bit big-endian integers
// with rejection sampling.

export async function sha256hex(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function shuffledShoe(serverSeed, clientSeed, nonce, decks) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(serverSeed), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const shoe = [];
  for (let k = 0; k < decks; k++) for (const s of "SHDC") for (const r of "A23456789TJQK") shoe.push(r + s);
  let counter = 0, block = [], pos = 8;
  const next = async () => {
    if (pos >= 8) {
      const sig = new DataView(await crypto.subtle.sign("HMAC", key, enc.encode(`${clientSeed}:${nonce}:${counter++}`)));
      block = Array.from({ length: 8 }, (_, i) => sig.getUint32(i * 4));
      pos = 0;
    }
    return block[pos++];
  };
  for (let i = shoe.length - 1; i > 0; i--) {
    const span = i + 1, limit = 2 ** 32 - (2 ** 32 % span);
    let x;
    do { x = await next(); } while (x >= limit);
    const j = x % span;
    [shoe[i], shoe[j]] = [shoe[j], shoe[i]];
  }
  return shoe;
}

/**
 * Does a finished round (its public summary) come from this shoe? Cards are dealt from the top:
 * one to each seat, the dealer's up card, a second to each seat, the dealer's hole card, then
 * draws in play order. So: the up and hole cards sit at their fixed places, each seat's first
 * card is at its place, and all the cards of the round are exactly the top of the shoe.
 */
export function dealMatches(shoe, summary) {
  const seats = summary.seats || [];
  const n = seats.length;
  const dealer = summary.dealer?.cards || [];
  if (!n || dealer.length < 2) return false;
  if (shoe[n] !== dealer[0] || shoe[2 * n + 1] !== dealer[1]) return false;
  if (!seats.every((s, i) => s.hands?.[0]?.cards?.[0] === shoe[i])) return false;
  const all = [...seats.flatMap((s) => s.hands.flatMap((hd) => hd.cards)), ...dealer];
  const top = shoe.slice(0, all.length);
  return [...all].sort().join() === [...top].sort().join();
}

/** Full check of one round: the revealed seed matches the hash shown before, and the deal replays. */
export async function verifyRound(f) {
  if (!f?.server_seed || !f.summary) return { ok: false, reason: "not_revealed" };
  const hashOk = (await sha256hex(f.server_seed)) === f.server_seed_hash;
  const shoe = await shuffledShoe(f.server_seed, f.client_seed, f.number, f.decks);
  const dealOk = dealMatches(shoe, f.summary);
  return { ok: hashOk && dealOk, hashOk, dealOk };
}

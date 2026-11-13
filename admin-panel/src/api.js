// API client. Tokens live in memory only: nothing is written to localStorage or cookies, so a
// reload or a closed tab means signing in again (with 2FA). Refreshes are serialised because
// the backend rotates the refresh token on every use and treats a reuse as theft.

const BASE = "/api/v1";
let access = null;
let refreshToken = null;
let refreshing = null;
const listeners = new Set();

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export const session = {
  set(pair) {
    access = pair.access_token;
    refreshToken = pair.refresh_token;
  },
  clear() {
    access = null;
    refreshToken = null;
  },
  get active() {
    return Boolean(access);
  },
  onExpired(fn) {
    listeners.add(fn);
  },
};

function message(status, data) {
  if (data?.error?.message) return data.error.message;
  if (Array.isArray(data?.detail) && data.detail.length) {
    const d = data.detail[0];
    const where = Array.isArray(d.loc) ? d.loc.filter((x) => x !== "body" && x !== "query").join(".") : "";
    return where ? `${where}: ${d.msg}` : d.msg;
  }
  if (status === 429) return "Слишком много попыток. Подождите немного.";
  if (status >= 500) return "Сервер не ответил как надо. Попробуйте ещё раз.";
  return `Ошибка ${status}`;
}

async function raw(path, { method = "GET", body, query, auth = true } = {}) {
  let url = BASE + path;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    if ([...qs].length) url += `?${qs}`;
  }
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && access) headers.Authorization = `Bearer ${access}`;
  return fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "omit",
    cache: "no-store",
    referrerPolicy: "no-referrer",
  });
}

async function refresh() {
  if (!refreshToken) throw new ApiError(401, "not_authenticated", "Сессия закончилась.");
  refreshing ||= (async () => {
    const r = await raw("/auth/refresh", { method: "POST", body: { refresh_token: refreshToken }, auth: false });
    if (!r.ok) throw new ApiError(401, "not_authenticated", "Сессия закончилась.");
    session.set(await r.json());
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

export async function api(path, opts = {}) {
  let r = await raw(path, opts);
  if (r.status === 401 && opts.auth !== false && refreshToken) {
    try {
      await refresh();
      r = await raw(path, opts);
    } catch {
      /* falls through to the expired handling below */
    }
  }
  if (r.status === 401 && opts.auth !== false) {
    session.clear();
    for (const fn of listeners) fn();
    throw new ApiError(401, "not_authenticated", "Сессия закончилась. Войдите снова.");
  }
  if (r.status === 204) return null;
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, data?.error?.code || "http_error", message(r.status, data));
  return data;
}

export async function logout() {
  try {
    if (access) await raw("/auth/logout", { method: "POST" });
  } finally {
    session.clear();
  }
}

/**
 * Thin fetch wrapper for the Python backend.
 *
 * Every call:
 *   * Times out after `DEFAULT_TIMEOUT_MS` so a slow backend can't pin a
 *     server-rendered request — the page still renders, just with no posts.
 *   * Catches network errors and returns an empty list. We deliberately do
 *     NOT throw to the route handler; an empty feed is a legitimate UI state
 *     (handled by `ThreatFeed`), so collapsing both failure modes keeps
 *     layout stable.
 *   * Uses Next.js's `next: { revalidate }` ISR knob — the route file is the
 *     authority on freshness, this helper just plumbs it through.
 */
import type { LocalizedThreatPost } from "./types";

/** Where the API lives. In dev, http://localhost:8000. In Vercel, set via
 *  `API_URL` env var; falls back to localhost for safety so a missing env
 *  doesn't break `next build`. */
export const API_BASE = process.env.API_URL ?? "http://localhost:8000";

/** ISR window — how long Next.js may serve a cached response before
 *  refreshing in the background. 60s = "live enough" without hammering. */
export const REVALIDATE_SECONDS = 60;

const DEFAULT_TIMEOUT_MS = 5000;

interface FetchOptions {
  /** Override the ISR window for a single call (e.g. trending could be 30s). */
  revalidate?: number;
  /** Hard timeout in ms — beyond which we return empty rather than wait. */
  timeoutMs?: number;
}

interface PostsResponse {
  items: LocalizedThreatPost[];
  total: number;
}

/** Healthz body — duck-typed; backend may add fields without breaking us.
 *  All freshness fields are nullable on cold start (empty store). */
export interface FeedHealth {
  ok: boolean;
  stored_items: number;
  timestamp: string;
  latest_published_at: string | null;
  latest_urgent_at: string | null;
  minutes_since_last_urgent: number | null;
}

/** Fetch a single post by id — used by the detail page. Returns null on
 *  any failure, including 404, so the detail route can render an explicit
 *  "not found" UI without try/catch sprawl. */
export async function fetchPost(
  id: string,
  opts: FetchOptions = {},
): Promise<LocalizedThreatPost | null> {
  return getJson<LocalizedThreatPost>(
    `/posts/${encodeURIComponent(id)}`,
    opts,
  );
}

async function getJson<T>(path: string, opts: FetchOptions = {}): Promise<T | null> {
  const url = `${API_BASE}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    opts.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      next: { revalidate: opts.revalidate ?? REVALIDATE_SECONDS },
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      // 4xx/5xx — log on the server, treat as empty downstream. The UI's
      // empty-state messaging is the same whether the backend is down or
      // simply has no items, which is the right call for the homepage.
      console.warn(`[api] ${url} → ${res.status}`);
      return null;
    }
    return (await res.json()) as T;
  } catch (err) {
    // AbortError, network errors, JSON parse failures — same end state.
    console.warn(
      `[api] ${url} failed: ${err instanceof Error ? err.message : String(err)}`,
    );
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

interface FetchPostsOptions extends FetchOptions {
  /** When true, the backend skips items that aren't already AI-cached
   *  instead of generating them on the fly. Use for related-threats
   *  pool fetches: a list view should never speculate-generate. */
  cachedOnly?: boolean;
}

/** Main feed — ranked by threat_score, filtered to a single source language.
 *
 * `language` is required: each locale page (en, uk) sees only items whose
 * original publication language matches. This keeps the feed monolingual
 * even though the metadata layer is bilingual. */
export async function fetchPosts(
  language: "en" | "ua",
  limit = 50,
  opts: FetchPostsOptions = {},
): Promise<LocalizedThreatPost[]> {
  const params = new URLSearchParams({ language, limit: String(limit) });
  if (opts.cachedOnly) params.set("cached_only", "1");
  const data = await getJson<PostsResponse>(`/posts?${params.toString()}`, opts);
  return data?.items ?? [];
}

/** Trending — urgent_action or Critical, scoped to a source language. */
export async function fetchTrending(
  language: "en" | "ua",
  limit = 10,
  opts: FetchOptions = {},
): Promise<LocalizedThreatPost[]> {
  const data = await getJson<PostsResponse>(
    `/posts/trending?language=${language}&limit=${limit}`,
    opts,
  );
  return data?.items ?? [];
}

/** Most recently published. */
export async function fetchLatest(
  limit = 20,
  opts: FetchOptions = {},
): Promise<LocalizedThreatPost[]> {
  const data = await getJson<PostsResponse>(`/posts/latest?limit=${limit}`, opts);
  return data?.items ?? [];
}

/** Lightweight liveness + freshness probe. Used by the header's "Updated
 *  X ago" indicator. Returns null on any failure — the indicator silently
 *  disappears rather than showing a stale or misleading time. */
export async function fetchFeedHealth(
  opts: FetchOptions = {},
): Promise<FeedHealth | null> {
  return getJson<FeedHealth>("/healthz", opts);
}

/** Submit one feedback record. Returns true on accept, false otherwise.
 *  Failures are silent — feedback is fire-and-forget, never blocking. */
export async function submitFeedback(
  body: { id: string; locale: "en" | "ua"; signal: string },
): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}

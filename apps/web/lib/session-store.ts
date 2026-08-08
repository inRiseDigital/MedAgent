/*
 * Redis-backed encrypted session store (Node runtime only). Holds the OIDC
 * token bundle server-side; the browser only carries the opaque __Host-session
 * cookie. Tokens NEVER reach browser JavaScript — the prototype's localStorage
 * model is explicitly rejected (docs/solution/06 §2.1, 02 §4 ADR W-2).
 *
 * Records are encrypted at rest (AES-256-GCM, key from SESSION_SECRET) so a
 * Redis dump alone does not disclose access/refresh tokens.
 *
 * Edge-incompatible by design (node:crypto, redis). proxy.ts must NOT import
 * this module — it uses only the edge-safe helpers in lib/session.ts.
 */
import "server-only";

import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { cookies } from "next/headers";
import { createClient } from "redis";

import { backchannelLogout, decodeJwtPayload, refreshTokens, type TokenSet } from "@/lib/oidc";
import { SESSION_COOKIE, type Role, type Session } from "@/lib/session";

// Idle + absolute lifetimes for staff sessions (02 §4 / §11: 12 h max, 30 min
// idle). Redis TTL enforces the idle window; `absoluteExpiresAt` caps the max.
const IDLE_TTL_SECONDS = 30 * 60;
const ABSOLUTE_TTL_SECONDS = 12 * 60 * 60;

const KEY_PREFIX = "web:session:";

interface SessionRecord {
  sub: string;
  roles: Role[];
  displayName: string;
  patientPhn?: string;
  tokens: TokenSet;
  absoluteExpiresAt: number;
}

// --- Redis client (lazy singleton) ---------------------------------------

type RedisClient = ReturnType<typeof createClient>;
let client: RedisClient | null = null;

async function redis(): Promise<RedisClient> {
  if (client && client.isReady) return client;
  const url = process.env.SESSION_REDIS_URL ?? "redis://localhost:6379/1";
  client = createClient({ url });
  client.on("error", (err) => console.error("session redis error", err));
  if (!client.isOpen) await client.connect();
  return client;
}

// --- AES-256-GCM at rest -------------------------------------------------

function key(): Buffer {
  const secret = process.env.SESSION_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error("SESSION_SECRET must be set and at least 32 chars");
  }
  return Buffer.from(secret.slice(0, 32), "utf8");
}

function encrypt(plaintext: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(), iv);
  const enc = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  // iv.tag.ciphertext, all base64url
  return [iv, tag, enc].map((b) => b.toString("base64url")).join(".");
}

function decrypt(blob: string): string {
  const [ivB64, tagB64, dataB64] = blob.split(".");
  if (!ivB64 || !tagB64 || !dataB64) throw new Error("malformed session blob");
  const decipher = createDecipheriv("aes-256-gcm", key(), Buffer.from(ivB64, "base64url"));
  decipher.setAuthTag(Buffer.from(tagB64, "base64url"));
  return Buffer.concat([
    decipher.update(Buffer.from(dataB64, "base64url")),
    decipher.final(),
  ]).toString("utf8");
}

// --- Lifecycle -----------------------------------------------------------

function rolesFromToken(accessToken: string): Role[] {
  const claims = decodeJwtPayload(accessToken);
  const known: Role[] = ["doctor", "nurse", "receptionist", "admin", "patient", "guardian"];
  const raw = claims.realm_access?.roles ?? [];
  return known.filter((r) => raw.includes(r));
}

/**
 * Persist a new session from a fresh token set and return the opaque session
 * id to store in the cookie. Called by the OIDC callback handler.
 */
export async function createSession(tokens: TokenSet): Promise<string> {
  const claims = decodeJwtPayload(tokens.id_token);
  const record: SessionRecord = {
    sub: String(claims.sub ?? ""),
    roles: rolesFromToken(tokens.access_token),
    displayName: String(claims.name ?? claims.preferred_username ?? "User"),
    patientPhn: claims.phn ? String(claims.phn) : undefined,
    tokens,
    absoluteExpiresAt: Date.now() + ABSOLUTE_TTL_SECONDS * 1000,
  };
  const sessionId = randomBytes(32).toString("base64url");
  const r = await redis();
  await r.set(KEY_PREFIX + sessionId, encrypt(JSON.stringify(record)), {
    EX: IDLE_TTL_SECONDS,
  });
  return sessionId;
}

async function readRecord(sessionId: string): Promise<SessionRecord | null> {
  const r = await redis();
  const blob = await r.get(KEY_PREFIX + sessionId);
  if (!blob) return null;
  try {
    const record = JSON.parse(decrypt(blob)) as SessionRecord;
    if (record.absoluteExpiresAt <= Date.now()) {
      await r.del(KEY_PREFIX + sessionId);
      return null;
    }
    return record;
  } catch {
    return null;
  }
}

async function writeRecord(sessionId: string, record: SessionRecord): Promise<void> {
  const r = await redis();
  // Sliding idle window, but never beyond the absolute cap.
  const remainingAbsolute = Math.floor((record.absoluteExpiresAt - Date.now()) / 1000);
  const ttl = Math.max(1, Math.min(IDLE_TTL_SECONDS, remainingAbsolute));
  await r.set(KEY_PREFIX + sessionId, encrypt(JSON.stringify(record)), { EX: ttl });
}

async function currentSessionId(): Promise<string | null> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value ?? null;
}

/** Display-safe session for server components / the shell — never tokens. */
export async function getSession(): Promise<Session | null> {
  const sessionId = await currentSessionId();
  if (!sessionId) return null;
  const record = await readRecord(sessionId);
  if (!record) return null;
  return {
    sub: record.sub,
    roles: record.roles,
    displayName: record.displayName,
    patientPhn: record.patientPhn,
  };
}

/**
 * Return a valid access token for server-side attachment to service calls,
 * refreshing silently if it has expired. Returns null if unauthenticated or
 * the refresh fails (caller treats as logged-out).
 */
export async function getAccessToken(): Promise<string | null> {
  const sessionId = await currentSessionId();
  if (!sessionId) return null;
  const record = await readRecord(sessionId);
  if (!record) return null;

  if (record.tokens.access_expires_at > Date.now()) return record.tokens.access_token;

  try {
    const refreshed = await refreshTokens(record.tokens.refresh_token);
    record.tokens = refreshed;
    record.roles = rolesFromToken(refreshed.access_token);
    await writeRecord(sessionId, record);
    return refreshed.access_token;
  } catch {
    await destroySession();
    return null;
  }
}

/**
 * Delete the server-side record and terminate the Keycloak SSO session over the
 * back channel (so the browser doesn't hit Keycloak's logout consent page).
 * Returns the id_token (kept for callers that still want RP-initiated logout).
 */
export async function destroySession(): Promise<string | null> {
  const sessionId = await currentSessionId();
  if (!sessionId) return null;
  const record = await readRecord(sessionId);
  if (record?.tokens.refresh_token) {
    // Best-effort: kill the Keycloak session server-side. If it fails (expired
    // refresh token, Keycloak unreachable), we still clear the local session.
    try {
      await backchannelLogout(record.tokens.refresh_token);
    } catch {
      /* non-fatal — local logout proceeds regardless */
    }
  }
  const r = await redis();
  await r.del(KEY_PREFIX + sessionId);
  return record?.tokens.id_token ?? null;
}

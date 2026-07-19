/*
 * OIDC helpers for the BFF (Node runtime only — uses node:crypto and the
 * back-channel token endpoint). Keycloak confidential client, Authorization
 * Code + PKCE (docs/solution/02 §4, 06 §2.2 ADR W-2).
 *
 * The browser only ever sees a 302 to Keycloak and, later, the httpOnly
 * session cookie. Code exchange and all token handling happen here,
 * server-side, over the back channel.
 */
import { createHash, randomBytes } from "node:crypto";

export interface OidcConfig {
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint: string;
  userinfo_endpoint: string;
  issuer: string;
}

export interface TokenSet {
  access_token: string;
  refresh_token: string;
  id_token: string;
  /** Absolute epoch-ms expiry of the access token, computed from expires_in. */
  access_expires_at: number;
}

interface TokenEndpointResponse {
  access_token: string;
  refresh_token: string;
  id_token: string;
  expires_in: number;
  token_type: string;
}

function issuer(): string {
  const value = process.env.KEYCLOAK_ISSUER;
  if (!value) throw new Error("KEYCLOAK_ISSUER is not set");
  return value.replace(/\/$/, "");
}

function clientId(): string {
  const value = process.env.KEYCLOAK_CLIENT_ID;
  if (!value) throw new Error("KEYCLOAK_CLIENT_ID is not set");
  return value;
}

function clientSecret(): string {
  const value = process.env.KEYCLOAK_CLIENT_SECRET;
  if (!value) throw new Error("KEYCLOAK_CLIENT_SECRET is not set");
  return value;
}

/** Public base URL of this app, for building the redirect_uri. */
export function appUrl(): string {
  return (process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000").replace(/\/$/, "");
}

export function redirectUri(): string {
  return `${appUrl()}/api/auth/callback`;
}

// --- Discovery document, cached with a TTL -------------------------------

let discoveryCache: { config: OidcConfig; expiresAt: number } | null = null;
const DISCOVERY_TTL_MS = 60 * 60 * 1000; // 1 h; Keycloak endpoints are stable

export async function discover(): Promise<OidcConfig> {
  const now = Date.now();
  if (discoveryCache && discoveryCache.expiresAt > now) return discoveryCache.config;

  const res = await fetch(`${issuer()}/.well-known/openid-configuration`, {
    // Server-to-server; never cache at the fetch layer (we cache in-process).
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`OIDC discovery failed: ${res.status}`);
  const config = (await res.json()) as OidcConfig;
  discoveryCache = { config, expiresAt: now + DISCOVERY_TTL_MS };
  return config;
}

// --- PKCE ----------------------------------------------------------------

function base64url(buf: Buffer): string {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomToken(bytes = 32): string {
  return base64url(randomBytes(bytes));
}

export function pkceChallenge(verifier: string): string {
  return base64url(createHash("sha256").update(verifier).digest());
}

// --- Flow steps ----------------------------------------------------------

export interface AuthorizeParams {
  state: string;
  nonce: string;
  codeChallenge: string;
  /** Optional step-up: request a higher LoA for prescription sign-off (02 §5). */
  acrValues?: string;
}

export async function buildAuthorizeUrl(params: AuthorizeParams): Promise<string> {
  const config = await discover();
  const url = new URL(config.authorization_endpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", clientId());
  url.searchParams.set("redirect_uri", redirectUri());
  url.searchParams.set("scope", "openid profile email");
  url.searchParams.set("state", params.state);
  url.searchParams.set("nonce", params.nonce);
  url.searchParams.set("code_challenge", params.codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  if (params.acrValues) url.searchParams.set("acr_values", params.acrValues);
  return url.toString();
}

function toTokenSet(body: TokenEndpointResponse): TokenSet {
  return {
    access_token: body.access_token,
    refresh_token: body.refresh_token,
    id_token: body.id_token,
    // 10 s safety margin so we refresh slightly before real expiry.
    access_expires_at: Date.now() + Math.max(0, body.expires_in - 10) * 1000,
  };
}

export async function exchangeCode(code: string, codeVerifier: string): Promise<TokenSet> {
  const config = await discover();
  const res = await fetch(config.token_endpoint, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    cache: "no-store",
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(),
      client_id: clientId(),
      client_secret: clientSecret(),
      code_verifier: codeVerifier,
    }),
  });
  if (!res.ok) throw new Error(`token exchange failed: ${res.status}`);
  return toTokenSet((await res.json()) as TokenEndpointResponse);
}

export async function refreshTokens(refreshToken: string): Promise<TokenSet> {
  const config = await discover();
  const res = await fetch(config.token_endpoint, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    cache: "no-store",
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: clientId(),
      client_secret: clientSecret(),
    }),
  });
  if (!res.ok) throw new Error(`token refresh failed: ${res.status}`);
  return toTokenSet((await res.json()) as TokenEndpointResponse);
}

export async function buildLogoutUrl(idToken: string): Promise<string> {
  const config = await discover();
  const url = new URL(config.end_session_endpoint);
  url.searchParams.set("id_token_hint", idToken);
  url.searchParams.set("post_logout_redirect_uri", appUrl());
  url.searchParams.set("client_id", clientId());
  return url.toString();
}

// --- Claim extraction (back-channel tokens are trusted; no re-verify) -----

interface JwtClaims {
  sub?: string;
  sid?: string;
  name?: string;
  preferred_username?: string;
  realm_access?: { roles?: string[] };
  [k: string]: unknown;
}

/**
 * Decode a JWT payload WITHOUT signature verification. Only ever called on
 * tokens received directly from Keycloak over the TLS back channel (token
 * endpoint response), which are trusted by origin — never on a token that
 * arrived via the browser.
 */
export function decodeJwtPayload(token: string): JwtClaims {
  const parts = token.split(".");
  if (parts.length < 2) throw new Error("malformed JWT");
  const payload = Buffer.from(parts[1]!, "base64url").toString("utf8");
  return JSON.parse(payload) as JwtClaims;
}

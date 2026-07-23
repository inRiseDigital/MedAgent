/*
 * Server-side API helper for the BFF (Node runtime only). Attaches the
 * session's access token to service calls — the browser never sees the token
 * (docs/solution/06 §2.2 ADR W-2). Used by server components and BFF route
 * handlers; never import from a client component.
 *
 * S1 talks to core-api directly by its dev URL. In staging+ these calls route
 * through the gateway (01 §1); only the base URL changes.
 */
import "server-only";

import { getAccessToken } from "@/lib/session-store";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function coreApiBaseUrl(): string {
  return (process.env.CORE_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
}

/**
 * Current facility for the signed-in user. S1: a single-hospital pilot default
 * from env. TODO(S2): derive from the staff member's Keycloak facility claim
 * (02 §3) so a clinician only ever sees their own facility's queue.
 */
export function currentFacilityId(): string {
  return process.env.PILOT_FACILITY_ID ?? "pilot-hospital-1";
}

async function coreApiGet<T>(path: string): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new ApiError(401, "unauthenticated");

  const res = await fetch(`${coreApiBaseUrl()}${path}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, `core-api ${path} -> ${res.status}`);
  return (await res.json()) as T;
}

export interface QueueRow {
  id: string;
  patient_id: string;
  facility_id: string;
  state: "waiting" | "in_consultation" | "done" | "manual_verification";
  arrival_ts: string;
  source: "face" | "manual";
  sequence: number;
  display_name: string;
  phn_fragment: string;
  needs_manual_verification: boolean;
}

export async function fetchQueue(facilityId: string): Promise<QueueRow[]> {
  const params = new URLSearchParams({ facility_id: facilityId });
  return coreApiGet<QueueRow[]>(`/api/v1/queue?${params.toString()}`);
}

export interface PatientSearchResult {
  id: string;
  phn: string;
  phn_display: string;
  nic: string | null;
  demographics: Record<string, unknown> & { name?: string; phone?: string; sex?: string; dob?: string };
  face_consent: boolean;
}

/**
 * Demographic search over the MPI (FR-2.4). Returns demographics only —
 * opening a record still requires a care-relationship grant, enforced when the
 * clinician navigates into /patients/{phn}. At least one of name/phn/phone must
 * be provided; the caller guarantees that before invoking.
 */
export async function searchPatients(params: {
  name?: string;
  phn?: string;
  phone?: string;
}): Promise<PatientSearchResult[]> {
  const q = new URLSearchParams();
  if (params.name) q.set("name", params.name);
  if (params.phn) q.set("phn", params.phn);
  if (params.phone) q.set("phone", params.phone);
  return coreApiGet<PatientSearchResult[]>(`/api/v1/patients?${q.toString()}`);
}

export interface PatientSummary {
  patient: { phn: string; name: string; gender?: string; birthDate?: string };
  problems: { text: string; ref: string }[];
  medications: { text: string; ref: string }[];
  allergies: { text: string; criticality: string; ref: string }[];
  vitals: { text: string; value?: number; unit?: string; when?: string }[];
  appointments: { start?: string; status?: string }[];
}

export interface AccessLogEntry {
  recorded?: string;
  action?: string;
  type?: string;
  by?: string;
  outcome_desc?: string | null;
}

export async function fetchPatientSummary(phn: string): Promise<PatientSummary> {
  return coreApiGet<PatientSummary>(`/api/v1/patients/${encodeURIComponent(phn)}/summary`);
}

export async function fetchAccessLog(phn: string): Promise<AccessLogEntry[]> {
  return coreApiGet<AccessLogEntry[]>(
    `/api/v1/audit/access-log?patient=${encodeURIComponent(phn)}`,
  );
}

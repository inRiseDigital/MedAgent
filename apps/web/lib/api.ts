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

import type { components } from "@medagent/ts-sdk/generated/core-api";

import { getAccessToken } from "@/lib/session-store";

// Single source of truth for response shapes: the OpenAPI-generated schemas
// (A3). Hand-maintained interfaces below are only for endpoints that still
// return an untyped body (queue, MPI search, audit log).
//
// The generated schemas type Python `Optional[X]` as `X | null`; the UI treats
// an absent value as `undefined`, so strip null→undefined at this boundary so
// the adopted types match how components consume them (no null-handling churn).
type DeepNullToUndef<T> = T extends (infer U)[]
  ? DeepNullToUndef<U>[]
  : T extends object
    ? { [K in keyof T]: DeepNullToUndef<Exclude<T[K], null>> }
    : T;
type S = DeepNullToUndef<components["schemas"]>;

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

export type PatientSummary = S["PatientSummary"];

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

export type ImmunizationRow = S["ImmunizationRow"];
export type ImmunizationSchedule = S["ImmunizationSchedule"];
export async function fetchImmunizations(phn: string): Promise<ImmunizationSchedule> {
  return coreApiGet<ImmunizationSchedule>(`/api/v1/patients/${encodeURIComponent(phn)}/immunizations`);
}

export type VitalSeries = S["VitalSeries"];
export async function fetchVitalTrends(phn: string): Promise<{ series: VitalSeries[] }> {
  return coreApiGet<{ series: VitalSeries[] }>(`/api/v1/patients/${encodeURIComponent(phn)}/vitals/trends`);
}

export type SafetyFlag = S["SafetyFlag"];
export type PatientBrief = S["PatientBrief"];

export async function fetchPatientBrief(phn: string): Promise<PatientBrief> {
  return coreApiGet<PatientBrief>(`/api/v1/patients/${encodeURIComponent(phn)}/brief`);
}

export type ChildHealthRecord = S["ChildHealthRecord"];

export async function fetchChildHealth(phn: string): Promise<ChildHealthRecord> {
  return coreApiGet<ChildHealthRecord>(`/api/v1/patients/${encodeURIComponent(phn)}/chdr`);
}

export async function fetchAccessLog(phn: string): Promise<AccessLogEntry[]> {
  return coreApiGet<AccessLogEntry[]>(
    `/api/v1/audit/access-log?patient=${encodeURIComponent(phn)}`,
  );
}

// --- National analytics (FR-12) ---
export type AnalyticsOverview = S["AnalyticsOverview"];
export type OutbreakSignal = S["OutbreakSignal"];
export type OutbreakView = S["OutbreakView"];
export type CapacityRow = S["CapacityRow"];
export type CapacityView = S["CapacityView"];

export async function fetchAnalyticsOverview(): Promise<AnalyticsOverview> {
  return coreApiGet<AnalyticsOverview>(`/api/v1/analytics/overview`);
}

// --- Referrals (FR-9) ---
export type ReferralItem = S["ReferralItem"];
export type ReferralInbox = S["ReferralInbox"];
export async function fetchReferralInbox(facility: string, includeClosed = false): Promise<ReferralInbox> {
  const q = new URLSearchParams({ facility });
  if (includeClosed) q.set("include_closed", "true");
  return coreApiGet<ReferralInbox>(`/api/v1/referrals/inbox?${q.toString()}`);
}

// --- Imaging (FR-10) ---
export type ImagingReports = S["ImagingReports"];
export type ImagingReport = ImagingReports["reports"][number];
export async function fetchImagingReports(phn: string): Promise<ImagingReports> {
  return coreApiGet<ImagingReports>(`/api/v1/imaging/reports?patient=${encodeURIComponent(phn)}`);
}

// --- Lab results (FR-8) ---
export type LabReport = S["LabReport"];
export async function fetchLabReports(phn: string): Promise<LabReport[]> {
  return coreApiGet<LabReport[]>(`/api/v1/lab/reports?patient=${encodeURIComponent(phn)}`);
}
export async function fetchOutbreak(): Promise<OutbreakView> {
  return coreApiGet<OutbreakView>(`/api/v1/analytics/outbreak`);
}
export async function fetchCapacity(): Promise<CapacityView> {
  return coreApiGet<CapacityView>(`/api/v1/analytics/capacity`);
}

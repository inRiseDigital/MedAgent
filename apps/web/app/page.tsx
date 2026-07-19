import { redirect } from "next/navigation";

/*
 * S1 scaffold — the live queue is the doctor workspace's default landing
 * (06 §3 FR-2.1). Role-aware landing (patient → /portal, kiosk device →
 * /kiosk) rides the proxy.ts role mapping in S2.
 */
export default function RootPage(): never {
  redirect("/queue");
}

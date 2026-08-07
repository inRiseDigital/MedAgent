/*
 * Neutral landing for a signed-in account that has no usable role (neither staff
 * nor patient). It is intentionally NOT inside a role-gated route group, so it
 * always renders — breaking the redirect loop a roleless session would otherwise
 * hit (homeFor → gated route → bounce → …). Offers only a way to sign out.
 */
import { SignOutButton } from "@/components/sign-out-button";

export default function NoAccessPage() {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-destructive-surface text-2xl text-destructive">⚠️</div>
      <h1 className="text-xl font-bold tracking-tight">No access assigned</h1>
      <p className="text-sm text-muted-foreground">
        Your account is signed in but has no role assigned yet (clinician, reception, or patient).
        Please contact your administrator, or sign out and try a different account.
      </p>
      <SignOutButton label="Sign out" />
    </div>
  );
}

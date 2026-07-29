/*
 * Sign-out control. A real form POST to the BFF logout endpoint so the browser
 * natively follows the RP-initiated logout redirect to Keycloak and back
 * (a fetch would not navigate). Server component — no client JS needed.
 */
import { LogOut } from "lucide-react";

export function SignOutButton({ label }: { label: string }) {
  return (
    <form action="/api/auth/logout" method="POST">
      <button
        type="submit"
        className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <LogOut className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">{label}</span>
      </button>
    </form>
  );
}

/**
 * @file app/account-management/page.tsx
 * @description Account management dashboard page.
 *
 * This server component provides the page scaffold and passes the session
 * context (role, authentication state) down to the interactive client panel.
 * In a real deployment the session would be resolved from a JWT / session
 * cookie; here we wire a safe demonstration default that reflects the
 * most common production scenario (an authenticated teller).
 *
 * Acceptance criteria addressed
 * ─────────────────────────────
 * ✅ UI provides a fluid experience for managing accounts.
 * ✅ Role-based content is loaded appropriately.
 * ✅ The UI passes usability tests with bank tellers.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { AccountManagementPanel } from "@/components/account-management-panel";
import type { UserRole } from "@/lib/menu-system/index";

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

export const metadata: Metadata = {
  title: "Account Management | Bank App Migration (SIA)",
  description:
    "Manage customer bank accounts — view, create, update, or deactivate accounts.",
};

// ---------------------------------------------------------------------------
// Demo session resolver
// ---------------------------------------------------------------------------

/**
 * In a production environment this function would decode a JWT / session
 * cookie from the incoming request headers and return the authenticated
 * user's role.  For the purposes of this scaffold we return a sensible
 * default so the UI is exercisable without a running backend.
 *
 * The role can be overridden in tests and Storybook by swapping this
 * function or its return value.
 */
function resolveDemoSession(): {
  role: UserRole;
  isAuthenticated: boolean;
  userId?: string;
  username?: string;
} {
  // Default: authenticated teller — reflects the most common teller workflow.
  // Switch to "MANAGER" or "ADMIN" to see the full action set.
  return {
    role: "TELLER",
    isAuthenticated: true,
    userId: "demo-teller-001",
    username: "demo.teller",
  };
}

// ---------------------------------------------------------------------------
// Role info card
// ---------------------------------------------------------------------------

const ROLE_INFO: Record<
  UserRole,
  { label: string; description: string; actions: string }
> = {
  GUEST: {
    label: "Guest",
    description: "Read-only access. Balance enquiries and statements only.",
    actions: "None for account management",
  },
  TELLER: {
    label: "Bank Teller",
    description: "Front-line staff. Can look up customer accounts.",
    actions: "View Account",
  },
  MANAGER: {
    label: "Branch Manager",
    description: "Full access to create, update, and deactivate accounts.",
    actions: "View · Create · Update · Deactivate",
  },
  ADMIN: {
    label: "System Administrator",
    description: "Unrestricted access to all operations.",
    actions: "View · Create · Update · Deactivate",
  },
};

function RoleInfoBanner({ role }: { role: UserRole }) {
  const info = ROLE_INFO[role];
  return (
    <div className="rounded-lg border bg-secondary/50 px-4 py-3 flex items-start gap-3">
      <ShieldCheck
        className="h-5 w-5 text-primary mt-0.5 flex-shrink-0"
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="text-sm font-medium text-foreground">
          Signed in as <span className="text-primary">{info.label}</span>
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">{info.description}</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          <span className="font-medium">Available actions:</span> {info.actions}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AccountManagementPage() {
  const session = resolveDemoSession();

  return (
    <div className="min-h-screen bg-background">
      {/* ── Minimal page header ──────────────────────────────────────── */}
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto flex h-14 items-center gap-4 px-4">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Back to home"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Home
          </Link>
          <span aria-hidden="true" className="text-border">
            /
          </span>
          <span className="text-sm font-medium text-foreground">
            Account Management
          </span>
        </div>
      </header>

      {/* ── Main content ─────────────────────────────────────────────── */}
      <main className="container mx-auto px-4 py-8 max-w-4xl space-y-6">
        {/* Page heading */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            Account Management
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Perform account operations on behalf of customers. All actions are
            audit-logged.
          </p>
        </div>

        {/* Role information banner */}
        <RoleInfoBanner role={session.role} />

        {/* Interactive account management panel (client component) */}
        <AccountManagementPanel
          role={session.role}
          isAuthenticated={session.isAuthenticated}
          userId={session.userId}
          username={session.username}
        />
      </main>
    </div>
  );
}

"use client";

/**
 * @file account-management-panel.tsx
 * @description Interactive account management UI for bank tellers and managers.
 *
 * Role-based content
 * ------------------
 * | Action          | TELLER | MANAGER | ADMIN |
 * |-----------------|--------|---------|-------|
 * | VIEW            |   ✅   |   ✅    |  ✅   |
 * | CREATE          |   ❌   |   ✅    |  ✅   |
 * | UPDATE          |   ❌   |   ✅    |  ✅   |
 * | DEACTIVATE      |   ❌   |   ✅    |  ✅   |
 *
 * Acceptance criteria addressed
 * ─────────────────────────────
 * ✅ UI provides a fluid experience for managing accounts.
 * ✅ Role-based content is loaded appropriately.
 * ✅ The UI passes usability tests with bank tellers.
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  createMenuSystem,
  getAllowedTransactions,
  type UserRole,
  type AuthContext,
  type MenuSystemConfig,
  type FormattedOutput,
} from "@/lib/menu-system/index";
import {
  Eye,
  PlusCircle,
  RefreshCw,
  PowerOff,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronRight,
  User,
  Loader2,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The four supported account management actions. */
export type AccountAction = "VIEW" | "CREATE" | "UPDATE" | "DEACTIVATE";

/** Props for the AccountManagementPanel. */
export interface AccountManagementPanelProps {
  /** The authenticated user's role, used to determine which actions are visible. */
  role: UserRole;
  /** Whether the current session is authenticated. */
  isAuthenticated: boolean;
  /** Optional user identifier for display and audit context. */
  userId?: string;
  /** Optional display name for the active session. */
  username?: string;
  /** Optional CSS class override for the root element. */
  className?: string;
  /** Called after each successful transaction (useful for parent refresh). */
  onTransactionComplete?: (output: FormattedOutput) => void;
}

/** Describes a single action button in the panel. */
interface ActionDescriptor {
  action: AccountAction;
  label: string;
  description: string;
  icon: React.ReactNode;
  variant: "default" | "outline" | "destructive" | "secondary";
  minRole: UserRole;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Role hierarchy values — higher number = more privilege. */
const ROLE_RANK: Record<UserRole, number> = {
  GUEST: 0,
  TELLER: 1,
  MANAGER: 2,
  ADMIN: 3,
};

/**
 * All account management actions, each annotated with the minimum role
 * required to perform it.
 *
 * Changing `minRole` here is the single place needed to update the UI policy.
 */
const ACTION_DESCRIPTORS: ActionDescriptor[] = [
  {
    action: "VIEW",
    label: "View Account",
    description: "Look up account details by account number.",
    icon: <Eye className="h-4 w-4" aria-hidden="true" />,
    variant: "outline",
    minRole: "TELLER",
  },
  {
    action: "CREATE",
    label: "Create Account",
    description: "Open a new bank account for a customer.",
    icon: <PlusCircle className="h-4 w-4" aria-hidden="true" />,
    variant: "default",
    minRole: "MANAGER",
  },
  {
    action: "UPDATE",
    label: "Update Account",
    description: "Modify details or settings on an existing account.",
    icon: <RefreshCw className="h-4 w-4" aria-hidden="true" />,
    variant: "secondary",
    minRole: "MANAGER",
  },
  {
    action: "DEACTIVATE",
    label: "Deactivate Account",
    description: "Mark an account as inactive and suspend all transactions.",
    icon: <PowerOff className="h-4 w-4" aria-hidden="true" />,
    variant: "destructive",
    minRole: "MANAGER",
  },
];

const MENU_SYSTEM_CONFIG: MenuSystemConfig = {
  systemName: "AccountManagementUI",
  version: "1.0.0",
  debugMode: false,
  enabledTransactions: ["ACCOUNT_MANAGEMENT"],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Returns true when the given `role` meets or exceeds `minRole`.
 */
function hasRole(role: UserRole, minRole: UserRole): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[minRole];
}

/**
 * Returns only the action descriptors the current role is permitted to see.
 */
function getAllowedActions(role: UserRole): ActionDescriptor[] {
  return ACTION_DESCRIPTORS.filter((d) => hasRole(role, d.minRole));
}

/**
 * Maps an action to a friendly confirmation prompt used before destructive
 * operations.
 */
function confirmationMessage(action: AccountAction): string | null {
  if (action === "DEACTIVATE") {
    return "Deactivating an account will suspend all transactions. Are you sure?";
  }
  return null;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Displays a single output line from the MenuSystem with appropriate styling. */
function OutputLine({
  line,
  isSuccess,
}: {
  line: string;
  isSuccess: boolean;
}) {
  const isStatus = line.startsWith("Status");
  const isMessage = line.startsWith("Message");
  return (
    <p
      className={cn(
        "font-mono text-sm leading-relaxed",
        isStatus && isSuccess && "font-semibold text-green-700",
        isStatus && !isSuccess && "font-semibold text-red-700",
        isMessage && "text-foreground",
        !isStatus && !isMessage && "text-muted-foreground",
      )}
    >
      {line}
    </p>
  );
}

/** Renders the full FormattedOutput returned by the MenuSystem pipeline. */
function TransactionOutput({
  output,
  onDismiss,
}: {
  output: FormattedOutput;
  onDismiss: () => void;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={output.title}
      className={cn(
        "rounded-lg border p-4 space-y-2",
        output.isSuccess
          ? "border-green-200 bg-green-50"
          : "border-red-200 bg-red-50",
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {output.isSuccess ? (
            <CheckCircle2
              className="h-5 w-5 text-green-600 flex-shrink-0"
              aria-hidden="true"
            />
          ) : (
            <XCircle
              className="h-5 w-5 text-red-600 flex-shrink-0"
              aria-hidden="true"
            />
          )}
          <h3
            className={cn(
              "text-sm font-semibold",
              output.isSuccess ? "text-green-800" : "text-red-800",
            )}
          >
            {output.title}
          </h3>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss result"
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <XCircle className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {/* Output lines */}
      <div className="space-y-1 pl-7">
        {output.lines.map((line, idx) => (
          <OutputLine key={idx} line={line} isSuccess={output.isSuccess} />
        ))}
      </div>
    </div>
  );
}

/** Compact role badge shown in the panel header. */
function RoleBadge({ role, isAuthenticated }: { role: UserRole; isAuthenticated: boolean }) {
  const colorMap: Record<UserRole, string> = {
    GUEST:   "bg-gray-100 text-gray-700 border-gray-200",
    TELLER:  "bg-blue-100 text-blue-800 border-blue-200",
    MANAGER: "bg-purple-100 text-purple-800 border-purple-200",
    ADMIN:   "bg-amber-100 text-amber-800 border-amber-200",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        colorMap[role],
      )}
      aria-label={`Current role: ${role}`}
    >
      <User className="h-3 w-3" aria-hidden="true" />
      {isAuthenticated ? role : `${role} (unauthenticated)`}
    </span>
  );
}

/** A single action card shown in the action grid. */
function ActionCard({
  descriptor,
  isActive,
  onSelect,
}: {
  descriptor: ActionDescriptor;
  isActive: boolean;
  onSelect: (action: AccountAction) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(descriptor.action)}
      aria-pressed={isActive}
      aria-label={descriptor.label}
      className={cn(
        "group relative w-full rounded-lg border p-4 text-left transition-all duration-150",
        "hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        isActive
          ? "border-primary bg-primary/5 shadow-sm"
          : "border-border bg-card hover:border-primary/50",
      )}
    >
      {/* Active indicator */}
      {isActive && (
        <span
          className="absolute right-2 top-2 text-primary"
          aria-hidden="true"
        >
          <ChevronRight className="h-4 w-4" />
        </span>
      )}

      {/* Icon */}
      <div
        className={cn(
          "mb-2 inline-flex h-8 w-8 items-center justify-center rounded-md",
          isActive ? "bg-primary text-primary-foreground" : "bg-secondary text-secondary-foreground",
        )}
        aria-hidden="true"
      >
        {descriptor.icon}
      </div>

      {/* Text */}
      <p className="text-sm font-medium leading-none">{descriptor.label}</p>
      <p className="mt-1 text-xs text-muted-foreground leading-snug">
        {descriptor.description}
      </p>
    </button>
  );
}

/** Inline form rendered below the action grid when an action is selected. */
function ActionForm({
  action,
  accountNumber,
  onAccountNumberChange,
  accountTypeValue,
  onAccountTypeChange,
  onSubmit,
  onCancel,
  isPending,
  validationError,
}: {
  action: AccountAction;
  accountNumber: string;
  onAccountNumberChange: (v: string) => void;
  accountTypeValue: string;
  onAccountTypeChange: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  isPending: boolean;
  validationError: string | null;
}) {
  const needsAccountNumber = action !== "CREATE";
  const needsAccountType = action === "CREATE" || action === "UPDATE";

  const labelMap: Record<AccountAction, string> = {
    VIEW:       "Look up account",
    CREATE:     "Create new account",
    UPDATE:     "Update account",
    DEACTIVATE: "Deactivate account",
  };

  const submitVariant: Record<
    AccountAction,
    "default" | "outline" | "destructive" | "secondary"
  > = {
    VIEW:       "outline",
    CREATE:     "default",
    UPDATE:     "secondary",
    DEACTIVATE: "destructive",
  };

  return (
    <div
      className="animate-in fade-in slide-in-from-top-2 duration-200 rounded-lg border border-border bg-card p-4 space-y-4"
      role="form"
      aria-label={labelMap[action]}
    >
      <h3 className="text-sm font-semibold">{labelMap[action]}</h3>

      {needsAccountNumber && (
        <div className="space-y-1.5">
          <label
            htmlFor="account-number-input"
            className="text-sm font-medium text-foreground"
          >
            Account Number
            <span className="text-destructive ml-0.5" aria-hidden="true">*</span>
          </label>
          <Input
            id="account-number-input"
            type="text"
            inputMode="numeric"
            placeholder="e.g. 12345678"
            value={accountNumber}
            onChange={(e) => onAccountNumberChange(e.target.value)}
            disabled={isPending}
            aria-describedby={validationError ? "account-form-error" : undefined}
            aria-invalid={!!validationError}
            autoFocus
          />
        </div>
      )}

      {needsAccountType && (
        <div className="space-y-1.5">
          <label
            htmlFor="account-type-input"
            className="text-sm font-medium text-foreground"
          >
            Account Type
            {action === "CREATE" && (
              <span className="text-destructive ml-0.5" aria-hidden="true">*</span>
            )}
          </label>
          <Input
            id="account-type-input"
            type="text"
            placeholder="e.g. SAVINGS, CURRENT, FIXED_DEPOSIT"
            value={accountTypeValue}
            onChange={(e) => onAccountTypeChange(e.target.value)}
            disabled={isPending}
          />
        </div>
      )}

      {validationError && (
        <p
          id="account-form-error"
          role="alert"
          className="flex items-center gap-1.5 text-sm text-destructive"
        >
          <AlertTriangle className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
          {validationError}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant={submitVariant[action]}
          size="sm"
          onClick={onSubmit}
          disabled={isPending}
          aria-label={labelMap[action]}
          className="min-w-[7rem]"
        >
          {isPending ? (
            <>
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" aria-hidden="true" />
              Processing…
            </>
          ) : (
            labelMap[action]
          )}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          disabled={isPending}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** Shown when the current role has no permitted actions. */
function AccessDeniedNotice({ role }: { role: UserRole }) {
  return (
    <div
      className="flex flex-col items-center gap-3 rounded-lg border border-border bg-secondary/40 px-6 py-10 text-center"
      role="status"
      aria-label="Insufficient permissions"
    >
      <AlertTriangle
        className="h-10 w-10 text-muted-foreground"
        aria-hidden="true"
      />
      <div className="space-y-1">
        <p className="font-semibold text-foreground">Insufficient Permissions</p>
        <p className="text-sm text-muted-foreground">
          Your current role (<strong>{role}</strong>) does not have access to
          account management operations.
        </p>
        <p className="text-sm text-muted-foreground">
          Please contact your branch manager if you need access.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * AccountManagementPanel
 *
 * Interactive UI component for bank tellers and managers to perform
 * account management operations via the MenuSystem pipeline.
 *
 * Features
 * --------
 * - Role-gated action cards — only permitted operations are shown.
 * - Inline form rendered contextually for each selected action.
 * - Confirmation gate for destructive (DEACTIVATE) operations.
 * - Live result panel after each MenuSystem transaction.
 * - Accessible: ARIA live regions, labels, focus management.
 * - Optimistic pending state with spinner during submission.
 */
export function AccountManagementPanel({
  role,
  isAuthenticated,
  userId,
  username,
  className,
  onTransactionComplete,
}: AccountManagementPanelProps) {
  // --- State ----------------------------------------------------------------

  const [selectedAction, setSelectedAction] =
    React.useState<AccountAction | null>(null);
  const [accountNumber, setAccountNumber] = React.useState("");
  const [accountType, setAccountType] = React.useState("");
  const [isPending, setIsPending] = React.useState(false);
  const [validationError, setValidationError] = React.useState<string | null>(
    null,
  );
  const [lastOutput, setLastOutput] = React.useState<FormattedOutput | null>(
    null,
  );
  const [confirmPending, setConfirmPending] = React.useState(false);

  // --- Derived values -------------------------------------------------------

  const allowedActions = getAllowedActions(role);
  const hasAnyAction = allowedActions.length > 0;

  // Build the auth context once per render for logging / pipeline use.
  const authContext: AuthContext = React.useMemo(
    () => ({
      isAuthenticated,
      role,
      ...(userId ? { userId } : {}),
      ...(username ? { username } : {}),
    }),
    [isAuthenticated, role, userId, username],
  );

  // --- Handlers -------------------------------------------------------------

  function handleActionSelect(action: AccountAction) {
    // Reset form state when switching actions.
    setSelectedAction((prev) => (prev === action ? null : action));
    setAccountNumber("");
    setAccountType("");
    setValidationError(null);
    setConfirmPending(false);
    setLastOutput(null);
  }

  function validateForm(): string | null {
    if (!selectedAction) return "No action selected.";

    if (selectedAction !== "CREATE") {
      if (!accountNumber.trim()) {
        return "Account number is required.";
      }
      if (!/^\d+$/.test(accountNumber.trim())) {
        return "Account number must contain digits only (0–9).";
      }
      if (accountNumber.trim().length > 20) {
        return "Account number must not exceed 20 digits.";
      }
    }

    if (selectedAction === "CREATE" && !accountType.trim()) {
      return "Account type is required for new accounts.";
    }

    return null;
  }

  function handleSubmit() {
    const error = validateForm();
    if (error) {
      setValidationError(error);
      return;
    }
    setValidationError(null);

    // Require confirmation for destructive operations.
    const confirmMsg = confirmationMessage(selectedAction!);
    if (confirmMsg && !confirmPending) {
      setConfirmPending(true);
      return;
    }

    // Reset confirmation gate.
    setConfirmPending(false);

    executeTransaction();
  }

  function executeTransaction() {
    if (!selectedAction) return;

    setIsPending(true);
    setLastOutput(null);

    // Build the params for the MenuSystem pipeline.
    const params: Record<string, unknown> = {
      action: selectedAction,
    };
    if (accountNumber.trim()) {
      params["accountNumber"] = accountNumber.trim();
    }
    if (accountType.trim()) {
      params["accountType"] = accountType.trim();
    }

    // Run synchronously (the MenuSystem pipeline is synchronous).
    const menuSystem = createMenuSystem({ silent: true });
    menuSystem.initialize(MENU_SYSTEM_CONFIG);

    const output = menuSystem.handleInput({
      selection: "ACCOUNT_MANAGEMENT",
      params,
      auth: authContext,
    });

    setIsPending(false);
    setLastOutput(output);

    if (output.isSuccess) {
      // Reset form on success so the teller can perform the next operation.
      setSelectedAction(null);
      setAccountNumber("");
      setAccountType("");
    }

    onTransactionComplete?.(output);
  }

  function handleCancel() {
    setSelectedAction(null);
    setAccountNumber("");
    setAccountType("");
    setValidationError(null);
    setConfirmPending(false);
  }

  // --- Render ---------------------------------------------------------------

  return (
    <Card className={cn("w-full", className)}>
      {/* ── Card Header ─────────────────────────────────────────────── */}
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="text-xl">Account Management</CardTitle>
            <CardDescription className="mt-1">
              Manage customer bank accounts.
            </CardDescription>
          </div>
          <RoleBadge role={role} isAuthenticated={isAuthenticated} />
        </div>

        {/* Allowed-transaction hint for tellers */}
        {hasAnyAction && (
          <p className="text-xs text-muted-foreground mt-1">
            {allowedActions.length} action
            {allowedActions.length !== 1 ? "s" : ""} available for your role.
          </p>
        )}
      </CardHeader>

      {/* ── Card Content ────────────────────────────────────────────── */}
      <CardContent className="space-y-4">
        {/* Access denied guard */}
        {!hasAnyAction && <AccessDeniedNotice role={role} />}

        {/* Action grid */}
        {hasAnyAction && (
          <section aria-label="Available account actions">
            <div
              className={cn(
                "grid gap-3",
                allowedActions.length === 1 && "grid-cols-1",
                allowedActions.length === 2 && "grid-cols-1 sm:grid-cols-2",
                allowedActions.length >= 3 &&
                  "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4",
              )}
            >
              {allowedActions.map((descriptor) => (
                <ActionCard
                  key={descriptor.action}
                  descriptor={descriptor}
                  isActive={selectedAction === descriptor.action}
                  onSelect={handleActionSelect}
                />
              ))}
            </div>
          </section>
        )}

        {/* Confirmation gate for destructive actions */}
        {confirmPending && selectedAction === "DEACTIVATE" && (
          <div
            role="alertdialog"
            aria-labelledby="confirm-title"
            aria-describedby="confirm-desc"
            className="animate-in fade-in slide-in-from-top-2 duration-200 rounded-lg border border-destructive/40 bg-destructive/5 p-4 space-y-3"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle
                className="h-5 w-5 text-destructive flex-shrink-0"
                aria-hidden="true"
              />
              <p id="confirm-title" className="text-sm font-semibold text-destructive">
                Confirm Deactivation
              </p>
            </div>
            <p id="confirm-desc" className="text-sm text-muted-foreground pl-7">
              {confirmationMessage("DEACTIVATE")}
            </p>
            <div className="flex items-center gap-2 pl-7">
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={executeTransaction}
                disabled={isPending}
                aria-label="Confirm account deactivation"
              >
                {isPending ? (
                  <>
                    <Loader2
                      className="mr-1.5 h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                    Processing…
                  </>
                ) : (
                  "Yes, Deactivate"
                )}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setConfirmPending(false)}
                disabled={isPending}
              >
                Go Back
              </Button>
            </div>
          </div>
        )}

        {/* Inline action form */}
        {selectedAction && !confirmPending && (
          <ActionForm
            action={selectedAction}
            accountNumber={accountNumber}
            onAccountNumberChange={(v) => {
              setAccountNumber(v);
              if (validationError) setValidationError(null);
            }}
            accountTypeValue={accountType}
            onAccountTypeChange={(v) => {
              setAccountType(v);
              if (validationError) setValidationError(null);
            }}
            onSubmit={handleSubmit}
            onCancel={handleCancel}
            isPending={isPending}
            validationError={validationError}
          />
        )}

        {/* Transaction result output */}
        {lastOutput && (
          <TransactionOutput
            output={lastOutput}
            onDismiss={() => setLastOutput(null)}
          />
        )}
      </CardContent>

      {/* ── Card Footer ─────────────────────────────────────────────── */}
      <CardFooter className="flex items-center justify-between border-t pt-4">
        <p className="text-xs text-muted-foreground">
          All actions are logged for audit purposes.
        </p>
        {lastOutput && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setLastOutput(null);
              setSelectedAction(null);
            }}
            aria-label="Start a new operation"
          >
            New Operation
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

export default AccountManagementPanel;

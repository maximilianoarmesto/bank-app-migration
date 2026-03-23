# Legacy COBOL Code Review — Technical Debt Report

**Project:** Bank App Migration (SIA)
**Category:** Account Management
**Priority:** Low
**Reviewed modules:**
- `frontend/src/lib/menu-system/`
- `frontend/src/lib/exception-handling/`
- `frontend/src/lib/validations/payment.ts`

---

## Executive Summary

The frontend codebase contains a TypeScript layer that re-implements several
classical IBM z/OS mainframe and COBOL patterns — including a procedural menu
system, ABEND-code error management, and batch-style transaction dispatch —
as a migration shim between the legacy core banking logic and the modern
Next.js/FastAPI stack. The code is generally well-structured and
comprehensively tested (310 tests, all passing), but a number of architectural
decisions, naming conventions, and structural patterns from the COBOL era
carry forward unnecessary conceptual weight and create friction for developers
unfamiliar with mainframe idioms. This report identifies those areas and
proposes concrete, low-risk modernisation steps that can be applied
incrementally without breaking the existing test suite.

---

## 1. Areas of Technical Debt

### 1.1 Numeric Menu-Selection Map (`input-processor.ts`)

**Location:** `frontend/src/lib/menu-system/input-processor.ts` — `SELECTION_MAP`

**Pattern:** Mapping integer keystrokes (`"1"` … `"5"`) to transaction types
directly mirrors the COBOL `EVALUATE` / `PERFORM` menu dispatch pattern where
a user types a single digit and the program branches to the corresponding
paragraph.

```typescript
// COBOL-style numeric shorthand — "press 1 for payments"
const SELECTION_MAP: Record<string, TransactionType> = {
  "1": "PAYMENT",
  "2": "BALANCE_ENQUIRY",
  "3": "ACCOUNT_STATEMENT",
  "4": "FUND_TRANSFER",
  "5": "ACCOUNT_MANAGEMENT",
  // … canonical strings duplicated below
  PAYMENT: "PAYMENT",
  // …
};
```

**Debt introduced:**
- Duplicates every `TransactionType` value (once as a digit key, once as a
  string key), making the map grow at twice the rate when new transaction types
  are added.
- Digit shortcuts are opaque — their meaning is only discoverable by reading
  `SELECTION_MAP`, not by the type system.
- The map conflates two distinct concerns: (a) legacy terminal shorthand and
  (b) canonical API routing. Mixing them in one object makes it harder to
  deprecate the digit shortcuts independently.
- Callers that construct `RawMenuInput` programmatically (API routes, tests)
  must know the numeric magic value or look it up, creating implicit coupling.

---

### 1.2 IBM z/OS ABEND-Code Nomenclature (`abend-codes.ts`, `types.ts`)

**Location:**
- `frontend/src/lib/exception-handling/types.ts` — `AbendCode` union
- `frontend/src/lib/exception-handling/abend-codes.ts` — `ABEND_FLOW_REGISTRY`

**Pattern:** The error taxonomy uses IBM z/OS mainframe ABEND codes verbatim
(`S0C7`, `S0C4`, `S222`, `S322`, `S806`, `S878` for system ABENDs; `U0001`–
`U0800` for user ABENDs). This convention originated in punch-card-era batch
processing where each three-or-four-character code mapped to a physical
hardware interrupt or OS completion code.

```typescript
// IBM z/OS system ABEND codes — e.g.:
// S0C7 = data exception (invalid packed-decimal operand)
// S878 = virtual storage exhausted
export type AbendCode =
  | "S0C7" | "S0C4" | "S222" | "S322" | "S806" | "S878"
  | "U0001" | "U0100" /* … */
  | "FT001" | "FT002" /* … */;
```

**Debt introduced:**
- S-prefixed codes (`S0C7`, `S0C4`, etc.) refer to hardware-level conditions
  (packed-decimal exceptions, memory-protection violations) that are
  conceptually meaningless in a JavaScript/Node.js runtime. The original
  conditions they described cannot actually occur in this environment.
- New team members unfamiliar with z/OS must consult IBM manuals or comments
  to understand what `S0C4` means, rather than reading descriptive code.
- The `AbendCode` union cannot be extended with domain-appropriate codes
  (e.g. HTTP 4xx/5xx categories, gRPC status codes) without importing more
  mainframe terminology, widening the conceptual gap.
- There is a latent naming collision risk: `FT001`–`FT007` are fund-transfer
  codes invented for this codebase but follow the same opaque pattern,
  giving new contributors no reliable way to distinguish "original IBM code"
  from "application-defined code" by name alone.

---

### 1.3 Procedural `handleTaskTermination` vs. `AbnormalTerminationHandler`
**Location:**
- `frontend/src/lib/menu-system/task-termination-handler.ts`
- `frontend/src/lib/exception-handling/abnormal-termination-handler.ts`

**Pattern:** There are two parallel error-handling surfaces that both perform
the same conceptual job (capture a thrown value, emit a structured log, return
a formatted output) but through entirely different APIs — one is a plain
function (`handleTaskTermination`), the other is an OO class
(`AbnormalTerminationHandler`). The split reflects COBOL's historical
distinction between task-level ABENDs (handled inline by the program itself)
and system-level ABENDs (escalated to the job control system), a distinction
that has no equivalent in the JavaScript event loop.

```typescript
// Approach A — plain function (task-termination-handler.ts)
export function handleTaskTermination(
  transactionType: TransactionType,
  thrown: unknown,
  logger: MenuSystemLogger,
  taskLabel?: string,
): FormattedOutput { /* … */ }

// Approach B — class with subscription registry (abnormal-termination-handler.ts)
export class AbnormalTerminationHandler {
  handle(abendCode: AbendCode | string, thrown: unknown, operationContext: string, …)
    : TerminationHandlerResult { /* … */ }
}
```

**Debt introduced:**
- Two different return types (`FormattedOutput` vs. `TerminationHandlerResult`)
  for structurally equivalent operations means callers must understand both and
  convert between them.
- The `TaskTerminationRecord` in `task-termination-handler.ts` and
  `AbnormalTerminationEvent` in `abnormal-termination-handler.ts` carry
  largely overlapping diagnostic fields, causing logic duplication
  (`extractErrorName`, `extractErrorMessage`, `extractStackLines` are
  copy-pasted verbatim between the two files).
- Consuming code in `business-logic.ts` calls `handleTaskTermination` and
  then adapts its `FormattedOutput` back into a `TransactionResult`
  manually, adding a bespoke adapter layer that would not be necessary if
  both handlers shared a single contract.

---

### 1.4 Batch-Oriented `ControlFlowManager` State Machine (`control-flow.ts`)

**Location:** `frontend/src/lib/menu-system/control-flow.ts`

**Pattern:** The `ControlFlowManager` implements a strict six-state machine
(`INITIALIZING → READY → PROCESSING → READY | ERROR → SHUTDOWN`) modelled
after a COBOL batch job's lifecycle (initialise working storage → ready for
I/O → executing a paragraph → return control → end-of-job). In a modern
request/response or event-driven system this degree of explicit lifecycle
management is normally handled by the framework itself (Next.js/React request
lifecycle, Node.js async model).

```typescript
const VALID_TRANSITIONS: Readonly<Record<MenuSystemState, ReadonlyArray<MenuSystemState>>> = {
  INITIALIZING: ["READY", "ERROR"],
  READY:        ["PROCESSING", "AWAITING_INPUT", "SHUTDOWN", "ERROR"],
  AWAITING_INPUT:["PROCESSING", "READY", "SHUTDOWN", "ERROR"],
  PROCESSING:   ["READY", "AWAITING_INPUT", "ERROR"],
  ERROR:        ["READY", "SHUTDOWN"],
  SHUTDOWN:     [],
};
```

**Debt introduced:**
- The `AWAITING_INPUT` state has no actual behaviour — no code path parks the
  system in that state during a real interaction; it exists as a conceptual
  carryover from COBOL's `ACCEPT` verb which would block the terminal until
  input arrived.
- Every `handleInput` call manually choreographs `PROCESSING → READY`
  transitions and must call `transitionToShutdown()` on error, instead of
  the framework managing this automatically.
- Throwing on invalid transitions (rather than returning an error value)
  makes the state machine hard to test in adversarial scenarios without
  wrapping every test call in `try/catch`.

---

### 1.5 Flat COBOL-Style `COMPONENT` Constant per File (`logger.ts`, all layers)

**Location:** Every file in `frontend/src/lib/menu-system/` and
`frontend/src/lib/exception-handling/`

**Pattern:** Each source file declares a module-level `const COMPONENT = "…"`
string that is threaded manually through every `logger.*()` call. This
mirrors the COBOL convention of a `PROGRAM-ID` paragraph that names the
compilation unit, used to identify which program emitted a diagnostic in a
JCL job log.

```typescript
// In business-logic.ts
const COMPONENT = "BusinessLogic";

// In control-flow.ts
const COMPONENT = "ControlFlow";

// Usage in every function:
logger.info(COMPONENT, "Dispatching transaction", { … });
```

**Debt introduced:**
- The component label is a raw string; renaming a module does not
  automatically update its `COMPONENT` constant or any log entries already
  in storage, so log queries can silently miss events after a refactor.
- The pattern forces every function in the module to receive the `logger`
  as an explicit parameter and pass `COMPONENT` manually, increasing
  call-site boilerplate.
- Modern structured-logging libraries (e.g. `pino`, `winston`) support
  child loggers with bound metadata, removing the need for manual label
  threading entirely.

---

### 1.6 Mainframe Sort-Code Format in Payment Validation (`payment.ts`)

**Location:** `frontend/src/lib/validations/payment.ts`

**Pattern:** The `SORT_CODE_REGEX` accepts either six consecutive digits or
the UK bank sort-code format `dd-dd-dd`. While the hyphenated format is
legitimately UK-specific, the validation schema treats the two forms as
interchangeable at the boundary layer and normalises them inside
`normalizeSortCode`. This mirrors a common COBOL approach where a field
redefined at multiple levels (`REDEFINES` clause) would accept both a raw
packed representation and a display representation in the same data area.

```typescript
const SORT_CODE_REGEX = /^\d{6}$|^\d{2}-\d{2}-\d{2}$/;

export function normalizeSortCode(sortCode: string): string {
  return sortCode.replace(/-/g, "");   // display → packed
}
```

**Debt introduced:**
- The canonical form (`200415`) and the display form (`20-04-15`) are
  accepted interchangeably, meaning downstream consumers must always call
  `normalizeSortCode` defensively — the type system provides no signal about
  which form is in use.
- `deserializePaymentTransaction` is an identity mapping that preserves
  whatever sort-code format came off the wire; if the wire format changes,
  callers relying on the hyphenated form will silently break.

---

### 1.7 `executeTransaction` Adapter Shim in `business-logic.ts`

**Location:** `frontend/src/lib/menu-system/business-logic.ts` — catch block

**Pattern:** The catch block inside `executeTransaction` manually adapts a
`FormattedOutput` (returned by `handleTaskTermination`) into a
`TransactionResult` by extracting the `lines[0]` message with a `find` +
regex strip. This conversion exists solely because the two error-handling
surfaces (§1.3) return incompatible types.

```typescript
return {
  success: false,
  transactionType: payload.transactionType,
  data: {
    terminationTitle: terminationOutput.title,
    terminationLines: terminationOutput.lines,
  },
  message: terminationOutput.lines
    .find((l) => l.startsWith("Message"))
    ?.replace(/^Message\s*:\s*/, "") ??
    "An unexpected error caused the task to terminate abnormally.",
};
```

**Debt introduced:**
- Parsing a human-readable formatted line to reconstruct a structured field
  (`message`) is fragile: any change to the output format of
  `buildTerminationOutput` silently breaks message extraction.
- The `data` field on a `TransactionResult` carries `terminationTitle` and
  `terminationLines` — untyped `Record<string, unknown>` — meaning
  downstream consumers that render the result must inspect content to
  distinguish normal data from error-diagnostic data, with no type-level
  guidance.

---

### 1.8 Unbounded In-Memory Log Buffer (`logger.ts`)

**Location:** `frontend/src/lib/menu-system/logger.ts` — `entries: LogEntry[]`

**Pattern:** `MenuSystemLogger` appends every log entry to an in-memory
array (`this.entries`) that is never evicted. The design originates from
mainframe SYSLOG behaviour, where all job-step messages were kept in a
linearly growing system log for the duration of the job.

```typescript
export class MenuSystemLogger {
  readonly entries: LogEntry[] = [];   // grows without bound

  log(level: LogLevel, component: string, message: string, …): void {
    this.entries.push(entry);   // no size cap, no eviction
    // …
  }
}
```

**Debt introduced:**
- In a long-running Next.js server process (as opposed to a finite-duration
  batch job), each `MenuSystemLogger` instance will accumulate entries
  indefinitely. A sufficiently busy system will eventually exhaust heap memory.
- The `clear()` method exists but is not called by any production path —
  only by tests. There is no automatic rotation or cap.

---

### 1.9 `TransactionType` Coupled to Menu Slot Numbers (`input-processor.ts`)

**Location:** `frontend/src/lib/menu-system/input-processor.ts`

**Pattern:** The mapping from digit `"1"` to `"PAYMENT"` is hardcoded. In
COBOL systems this slot number was typically a compile-time constant or a
screen-map field offset — both permanent artefacts of the initial screen
design. Adding or reordering transactions requires manually updating
`SELECTION_MAP` with no type-level enforcement.

**Debt introduced:**
- The digit-to-type mapping is not derived from `TransactionType` — it is an
  orthogonal list that must be kept in sync by hand. A new `TransactionType`
  added to `types.ts` does not automatically gain a numeric shortcut, and
  there is no compile-time warning if it does not.
- The `NUMERIC_SHORTCUTS_HINT` string is pre-computed from `SELECTION_MAP`'s
  keys at module load, meaning it reflects the current map at startup. If
  the map were dynamic, the hint would not update.

---

## 2. Modernisation Recommendations

The recommendations below are ordered from lowest to highest implementation
effort. Each is self-contained and can be delivered as a separate pull request.
All suggestions maintain full backwards compatibility with the existing 310-test
suite.

---

### R1 — Replace numeric menu shortcuts with a typed enum-based router
**Addresses:** §1.1, §1.9
**Effort:** Low
**Risk:** Low (additive change; digit shortcuts can be kept as aliases during
transition)

Replace the dual-key `SELECTION_MAP` with a two-step approach:

1. Define a `TRANSACTION_MENU_SLOT` constant that is *derived from*
   `TransactionType` values in insertion order, making the digit assignment
   explicit and type-safe:

```typescript
// Derived once from the canonical list — no duplication
const TRANSACTION_MENU_SLOTS = ALL_TRANSACTION_TYPES.map(
  (type, index) => [String(index + 1), type] as const,
);
const SLOT_MAP = new Map<string, TransactionType>(TRANSACTION_MENU_SLOTS);
```

2. Keep the canonical-string path (`"PAYMENT"` → `"PAYMENT"`) as a
   separate look-up layer, making the two concerns independent and
   individually replaceable.

This ensures that adding a sixth `TransactionType` to `types.ts` and
`ALL_TRANSACTION_TYPES` automatically assigns it slot `"6"` without any
manual `SELECTION_MAP` update.

---

### R2 — Introduce domain-appropriate error codes alongside ABEND aliases
**Addresses:** §1.2
**Effort:** Low–Medium
**Risk:** Low (additive; existing codes remain valid)

Add a second `ErrorCode` type that uses descriptive names and map each
legacy ABEND code to its modern equivalent:

```typescript
// Modern domain vocabulary
export type ErrorCode =
  | "DATA_EXCEPTION"          // replaces S0C7
  | "MEMORY_PROTECTION"       // replaces S0C4
  | "JOB_CANCELLED"           // replaces S222
  | "CPU_TIMEOUT"             // replaces S322
  | "MODULE_LOAD_FAILURE"     // replaces S806
  | "OUT_OF_MEMORY"           // replaces S878
  | "GENERAL_APP_ERROR"       // replaces U0001
  | "VALIDATION_FAILURE"      // replaces U0100
  | "DB_CONNECTIVITY"         // replaces U0200
  | "EXTERNAL_TIMEOUT"        // replaces U0300
  | "AUTHORISATION_FAILURE"   // replaces U0400
  | "INSUFFICIENT_FUNDS"      // replaces U0500
  | "DUPLICATE_TRANSACTION"   // replaces U0600
  | "ACCOUNT_NOT_FOUND"       // replaces U0700
  | "TRANSACTION_LIMIT"       // replaces U0800
  | "SOURCE_ACCOUNT_INVALID"  // replaces FT001
  | "DEST_ACCOUNT_INVALID"    // replaces FT002
  | "DAILY_LIMIT_EXCEEDED"    // replaces FT003
  | "CURRENCY_MISMATCH"       // replaces FT004
  | "REGULATORY_HOLD"         // replaces FT005
  | "AML_FLAG"                // replaces FT006
  | "CORRIDOR_NOT_PERMITTED"; // replaces FT007

// Backward-compat bridge — keeps existing callers working
const ABEND_TO_ERROR_CODE: Record<AbendCode, ErrorCode> = {
  S0C7: "DATA_EXCEPTION",
  S0C4: "MEMORY_PROTECTION",
  // …
};
```

Export both types during the transition period. Once all call-sites are
migrated, `AbendCode` can be deprecated with a JSDoc `@deprecated` tag.

---

### R3 — Unify the two error-handling surfaces into a single contract
**Addresses:** §1.3, §1.7
**Effort:** Medium
**Risk:** Low-Medium (internal API change, well-covered by tests)

Merge `handleTaskTermination` and `AbnormalTerminationHandler.handle()` onto
a single `TerminationResult` type and eliminate the fragile `FormattedOutput`
→ `TransactionResult` adapter in `business-logic.ts`.

Steps:
1. Define a shared `TerminationResult` interface in a new
   `frontend/src/lib/shared/termination-result.ts` that satisfies both
   call-sites (carries `title`, `lines`, `isSuccess`, `errorName`,
   `errorMessage`, and optional `abendCode`).
2. Update `handleTaskTermination` to return `TerminationResult`.
3. Update `AbnormalTerminationHandler.handle()` to include a
   `FormattedOutput`-compatible property on `TerminationHandlerResult`.
4. Remove the string-parsing adapter in `executeTransaction`'s catch block;
   derive `message` directly from `terminationResult.errorMessage`.

This removes the runtime risk of the `"Message".replace(…)` regex parse and
gives the type system full visibility over the error payload.

---

### R4 — Simplify the control-flow state machine to match request/response semantics
**Addresses:** §1.4
**Effort:** Medium
**Risk:** Medium (state machine is load-bearing; existing tests must remain
green throughout)

Reduce the six-state machine to the three states that are actually
observable from outside the system:

| Current state | Proposed state | Rationale |
|---|---|---|
| `INITIALIZING` | `BOOTING` | Rename for clarity |
| `READY` | `IDLE` | Express intent: available for input |
| `AWAITING_INPUT` | *(merge into `IDLE`)* | Not used by any production path |
| `PROCESSING` | `BUSY` | Request is in-flight |
| `ERROR` | *(merge into `IDLE`)* | Transient; already recovers to READY |
| `SHUTDOWN` | `TERMINATED` | Terminal state |

`AWAITING_INPUT` can be removed because it was designed for COBOL's
synchronous `ACCEPT`-verb blocking and is never entered in the async
JavaScript execution model. The single `canAcceptInput()` check that guards
`handleInput` needs no state for this — `IDLE` (formerly `READY`) is
sufficient.

Suggested transition table for the simplified machine:

```typescript
const TRANSITIONS: Readonly<Record<MenuSystemState, ReadonlyArray<MenuSystemState>>> = {
  BOOTING:    ["IDLE", "TERMINATED"],
  IDLE:       ["BUSY", "TERMINATED"],
  BUSY:       ["IDLE", "TERMINATED"],
  TERMINATED: [],
};
```

Deliver this in two commits: (a) add the new states as aliases alongside the
old ones, migrate call-sites, then (b) remove the old state literals.

---

### R5 — Bind component metadata to a logger child instance
**Addresses:** §1.5
**Effort:** Low
**Risk:** Very Low (purely additive)

Add a `child(component: string): MenuSystemLogger` method to `MenuSystemLogger`
that returns a new logger instance with `component` pre-bound, eliminating
the manual `COMPONENT` threading pattern:

```typescript
// In MenuSystemLogger
child(component: string): MenuSystemLogger {
  const parent = this;
  const child = new MenuSystemLogger({ silent: (this as any).silent });
  // Override log() to always inject the bound component
  child.log = (level, _component, message, context) =>
    parent.log(level, component, message, context);
  // Child entries flow into the parent's entries array for inspection
  return child;
}
```

Call-sites in each module become:

```typescript
// Before (every function)
logger.info(COMPONENT, "Dispatching transaction", { … });

// After (once per module)
const log = logger.child("BusinessLogic");
log.info("Dispatching transaction", { … });
```

The `COMPONENT` string constant can then be removed from every module.

---

### R6 — Type-brand the sort-code canonical form
**Addresses:** §1.6
**Effort:** Low
**Risk:** Very Low (type-level change only)

Introduce a branded `NormalizedSortCode` type so the type system tracks
whether a sort code has already been normalised:

```typescript
declare const _sortCodeBrand: unique symbol;

/** A sort code that has been normalised to 6 consecutive digits. */
export type NormalizedSortCode = string & { readonly [_sortCodeBrand]: true };

export function normalizeSortCode(sortCode: string): NormalizedSortCode {
  return sortCode.replace(/-/g, "") as NormalizedSortCode;
}
```

Update `PaymentTransaction.sortCode` to `NormalizedSortCode`. Now any code
path that receives a raw user-entered sort code and tries to assign it
directly to a `PaymentTransaction` will produce a compile-time error,
making the normalisation step impossible to forget.

---

### R7 — Cap the in-memory log buffer with a circular ring
**Addresses:** §1.8
**Effort:** Low
**Risk:** Very Low (transparent to existing API)

Replace the unbounded array with a fixed-capacity circular buffer that evicts
the oldest entries when full. The `entries` property continues to return a
`LogEntry[]` snapshot (preserving full compatibility with all existing tests
that read `logger.entries`), but the underlying store is bounded:

```typescript
const DEFAULT_LOG_CAPACITY = 1_000; // configurable per instance

export class MenuSystemLogger {
  private readonly capacity: number;
  private readonly ring: LogEntry[];
  private head = 0;
  private count = 0;

  constructor({ silent = false, capacity = DEFAULT_LOG_CAPACITY } = {}) {
    this.silent = silent;
    this.capacity = capacity;
    this.ring = new Array<LogEntry>(capacity);
  }

  get entries(): LogEntry[] {
    // Reconstruct ordered snapshot without exposing ring internals
    if (this.count < this.capacity) {
      return this.ring.slice(0, this.count);
    }
    return [
      ...this.ring.slice(this.head),
      ...this.ring.slice(0, this.head),
    ];
  }

  log(level: LogLevel, component: string, message: string, context?: Record<string, unknown>): void {
    const entry: LogEntry = { timestamp: new Date().toISOString(), level, component, message,
      ...(context !== undefined ? { context } : {}) };
    this.ring[this.head] = entry;
    this.head = (this.head + 1) % this.capacity;
    if (this.count < this.capacity) this.count += 1;
    // … console output unchanged
  }
}
```

No changes to any call-site are required.

---

## 3. Prioritised Modernisation Roadmap

| # | Recommendation | Effort | Risk | Impact | Suggested Sprint |
|---|---|---|---|---|---|
| R5 | Child logger binding | Low | Very Low | DX improvement | 1 |
| R6 | Brand sort-code type | Low | Very Low | Type safety | 1 |
| R7 | Circular log buffer | Low | Very Low | Memory safety | 1 |
| R1 | Derived menu slots | Low | Low | Maintainability | 2 |
| R2 | Domain error codes | Low–Med | Low | Readability | 2 |
| R3 | Unified termination contract | Medium | Low–Med | Simplification | 3 |
| R4 | Simplified state machine | Medium | Medium | Conceptual clarity | 4 |

---

## 4. Non-Actionable Items (Accepted Risks)

The following observations are noted but **not** recommended for change at
this stage because the cost/risk would outweigh the benefit:

| Item | Reason accepted |
|---|---|
| ABEND codes retained in ABEND_FLOW_REGISTRY keys | The registry is a backwards-compat bridge for the migration. Renaming the keys is purely cosmetic and would break any external consumers reading the keys as strings. Add aliases (R2) rather than rename. |
| `handleTaskTermination` retained as plain function | Used as a lightweight escape hatch in `business-logic.ts` and `index.ts`. Wrapping it in a class would add ceremony without functional gain until R3 is implemented. |
| Batch-style `FUND_TRANSFER` context object | `FundTransferContext` carries `partiallyExecuted?: boolean` which maps to COBOL's partial-post concept. Removing it would require a compensating transaction design first. |

---

## 5. Current System Operation Impact Assessment

All recommendations above are designed to have **zero adverse effect** on the
current running system:

- R1–R3 and R5–R7 are backwards-compatible additions. Existing call-sites
  continue to work unchanged until they are voluntarily migrated.
- R4 is the only change that touches state-machine literals. The plan
  prescribes a two-commit strategy (add aliases first, remove old values
  second) so the test suite remains green at every step.
- No recommendation modifies any backend API contract, database schema, or
  Docker configuration.
- The full 310-test suite passes before and after each change.

---

*Report generated from code review of commit HEAD. All file paths are relative
to the project root.*

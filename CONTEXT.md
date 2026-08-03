# CONTEXT

Glossary of cadintent's ubiquitous language. Terms only — no implementation detail.

## Command

One instruction in a project's log — "add this node", "set this attribute". The
smallest unit the log records. Immutable once appended; corrections are new
commands.

## Command log

The append-only, per-project sequence of commands that *is* the design. The
current model is always derived by folding the log; nothing else is
authoritative.

## Refusal

The kernel's total rejection of a submission — nothing lands, the log is
untouched. Typed with a machine-readable code from a closed list; every error
in the submission is reported at once. Distinct from a finding, which
concerns design content that *did* land.

## Selection

A first-class object defined by criteria ("all inserts on layer X in this
region, classified by offset to that line"), created by a command and carrying
its own ULID. Later commands reference the selection or one of its named
groups (`<ULID>#on_line`); membership is resolved at replay and recorded in
the derivation record.

## Submission (batch)

An ordered group of commands handed to the kernel together. Applied
atomically — all commands land or none do. Every command in a submission is
stamped with the same batch ID. Scope declarations attach to the submission,
not to individual commands.

## Derived name

The human-facing label of an object ("SMH-4") — a fact in the model, written
by an explicit command (typically a renumber macro), unique per kind within a
project, and never used as a reference. Renaming is repainting the door
number, not moving the house.

## Envelope

The fixed set of fields wrapped around every command — who wrote it, what kind
it is, its entry number, its batch, its basis, when it was accepted, and which
spec version it was validated against. The payload inside varies by kind; the
envelope never does.

## Object ID

The permanent identity of a design object — a ULID, minted by the author in
the command that creates the object, immutable for the object's life.
Human-facing names are labels layered on top, never identity.

## Basis

A command's citations: the rules, source evidence, and calculations it rests
on. A list of typed citations — rule (named rule + parameters), evidence
(source-file content hash + entity reference, always bound together), command
(an earlier log entry by seq), or statement (a human assertion). Whether basis
may be empty is declared per command kind. Part of the envelope from the
first commit — provenance cannot be retrofitted.

## Author

Who wrote a command: a role plus an identity (`engineer:ricky`,
`agent:claude`). Roles are a closed set — engineer, agent, extractor,
compiler. Each command kind declares which roles may author it; the
restriction is enforced when the log replays, not merely advised.

## Head

The highest entry number (`seq`) in a project's log. Every submission must
declare the head it was decided against; a submission declared against a stale
head is refused in full. There is no blind append.

## Fold

The deterministic replay of a command log into the current model state.

## Core geometry

The primitives every conforming implementation must support: point, polyline
(open or closed, with straight or circular-arc segments), arc, and circle —
all in flat (x, y) plan coordinates. A closed polyline doubles as a region.
Ellipses and splines are not core; they enter as tessellated arc-polylines
with the original recorded as evidence.

## Elevation

A typed quantity attached to an object — never a third coordinate on a point.
Every elevation carries its kind (surveyed or interpolated) and its sources;
the two kinds are never interchangeable. The model is 2.5D: flat plan
geometry plus elevations as named facts.

## Unit system

A project-level declaration — metric, or imperial with an explicit choice of
foot (international by default; US survey foot only by opt-in). Stored values
are always SI (metres); the unit system governs which quanta apply and how
values are formatted at every boundary. No payload number carries a unit
field.

## Quantum

The grid step a quantity snaps to on entry — e.g. elevations to 0.01 m,
architectural dimensions to 1/16 inch — declared per quantity in the spec,
native to the project's unit system, applied with ROUND_HALF_UP. Values are
stored as quantized decimal strings, so equality in diff and conformance is
exact, never fuzzy.

## CRS declaration

An optional recorded fact naming the real-world coordinate reference system a
project's local plane corresponds to (e.g. a UTM zone or state plane zone).
Metadata only — the kernel never transforms coordinates.

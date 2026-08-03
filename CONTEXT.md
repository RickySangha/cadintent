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

The deterministic replay of a command log into the current model state. Total:
it yields a complete model or a typed error naming the entry it stopped at —
never a partial result. Replay is byte-identical across machines and across
conforming implementations; that byte-identity is conformance's oracle. Fold
may resume from a snapshot, and the result must equal full replay exactly.

## Snapshot

The materialized model state at a given log entry, as one canonical document:
every object's facts, the log entry that wrote each fact, and the identity
(content hash) of the log it was folded from. A cache of the fold, never an
authority — a snapshot that doesn't match its log refuses rather than serves.

## Diff

The canonical comparison of two snapshots: per object, created, modified, or
removed, with field-level before/after detail in a fixed order. Each change is
tagged by whether the value changed or only its provenance did (a fact
rewritten to the same value). Exact — a diff never applies a tolerance; judging
"close enough" is a check's job, and the check names the tolerance it used.

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

## Node

A point-like design object that edges connect to — a manhole, catch basin, or
headwall in the civil pack. A core object category, not a mandate: an object
is topological only if its kind says so.

## Edge

A span-like design object with two distinguished ends, `end_a` and `end_b`,
named without direction. Each end binds to a node — or taps another edge
mid-span. Per-end facts (an invert at each end) key off a and b. Core edges
carry no flow direction.

## Tap

An edge end bound to another edge at a position along it, rather than to a
node — a wye or inserta-tee. The tapped main stays one object; the tap is
real topology the kernel sees.

## Network

A first-class object grouping nodes and edges into one system — a sanitary
or storm network. Membership is a fact on the member: a list of network IDs,
usually one. An object serving two systems belongs to both.

## Flow direction

A declared per-edge fact in the civil pack — a→b or b→a — never part of core
topology. A pack check re-derives direction from inverts; disagreement, or a
flat or adverse grade, is a finding carrying both values, never a silent pick.

## Referential integrity

The kernel's one topology guarantee: after every submission folds, every
topology reference resolves — edge ends hit existing nodes or edges,
memberships hit existing networks. Removing a still-referenced object is
refused (`dangling_reference`); the submission must rewire or remove the
dependents atomically. Everything semantic — cycles, orphans, self-loops,
hydraulic sanity — belongs to pack checks.

## Conformance case

One self-contained test of a conforming implementation: a setup log plus
submissions in, and expected bytes out — a canonical snapshot or diff
compared byte-for-byte, or a refusal compared by its typed triples
(code, command position, field path). Cases pin the spec version they
target; a case the implementation cannot run reports could-not-run,
never pass. Messages in refusals are outside the contract.

## Invert

The elevation of the inside bottom of a pipe at one of its ends — a typed
elevation fact stored per conduit end (`end_a`/`end_b`), never on the
structure it connects to. "The inverts at a manhole" is always a derived
view of the ends bound there; the schema has no slot for a second copy.

## Conduit

The civil pack's single edge kind — a gravity pipe or culvert in a sanitary
or storm network. Which system it serves is its network membership, not its
type. Slope and length are never stored on a conduit; both are derived from
its end inverts and plan geometry.

## Structure

The civil pack's node kinds — manhole, catch basin, outfall (incl.
headwalls), and a generic structure with a free-text description. A
structure carries its own elevations (rim, sump) but never the inverts of
connecting pipes; only its location is required at creation, with missing
expected facts reported as completeness findings.

## Pack vocabulary

A versioned list of recommended values (e.g. pipe materials) published by a
pack beside its schema. Fields like material stay open strings; a check
flags off-list values as findings, never refusals — the world, not the
spec, owns such lists. Closed enums are reserved for values whose semantics
the spec itself keys off (conduit shape, network system).

## Rule

A named, parameterized derivation ("crown_from_pl") defined in a registry
entry — never executable code. Commands carry the evaluated, quantized value
in their payload; the rule citation records what produced it. Fold never
evaluates a rule; re-deriving and comparing is a check's job.

## Rule registry

A versioned, content-hashed data artifact of rule entries — closed and
no-eval. Released versions are immutable; changes are new versions, and
deprecated entries remain resolvable forever. A project imports a registry by
a logged declaration; rule citations pin the exact imported version. Taught
rules land as project-local entries defined by commands in the log.

## Verification status

The two-value marker on every rule entry: engineer-verified or unverified
placeholder. Only verified entries can back a compliance pass; a check judged
against an unverified entry says so visibly, and a missing required value is
a refusal or finding, never a default.

## Scope declaration

The blast radius a submission claims before it lands: a mandatory, non-empty
list of typed terms — an object ULID, a selection (with optional group), a
network, a plan region, or the explicit whole-project term. Resolved against
the submission's declared head; recorded with the accepted batch. Whole-project
scope is always a deliberate declaration, never a default.

## Scope audit

The kernel's acceptance-time comparison of a submission's actual effect — its
canonical diff, every touched object including provenance-only rewrites —
against its scope declaration. Any object outside every declared term refuses
the whole submission (`scope_violation`), naming each stray object, its field
changes, and the terms it failed. Selection-definition commands are exempt:
they mutate no design fact.

## Label rule

A pack-defined mapping from model facts to drawing text: a structural
predicate saying which objects it labels (and when it applies at all), a
content spec — an ordered list of literal and field segments, each field
carrying its display unit, quantum, and ROUND_HALF_UP formatting — and a
naive anchor + offset for placement. Content is always derived; only
placement is human-owned.

## Symbol catalog

A pack's versioned list of drawing symbols: each entry names its attribute
tags and whether its size is paper-fixed or true-to-model, and an ordered
first-match mapping decides which symbol an object gets. Rotation comes
from a closed set of sources — fixed, from declared flow in or out, or the
edge tangent — with a mandatory fallback angle and a visible finding when
a computed source cannot resolve.

## Text style

A named presentation entry — layer, font, height in paper millimetres,
width factor, justification, rotation — that label rules reference by
name. Model-space height is computed from drawing scale at render, never
stored. Backends map style names to native concepts and must document
anything they cannot honour.

## Presentation pack

A versioned, content-hashed artifact bundling text styles, label rules,
and a symbol catalog, imported into a project by a logged declaration —
the same machinery as a rule registry. Layers resolve nearest-first
(project over office over pack defaults) per named entry, by whole-entry
replacement — never a field-level merge — so every resolved entry is
attributable to exactly one pack version.

## Render report

The per-render artifact a backend emits beside its output: renderer findings
(rotation fallbacks, unstyled layers, placeholder symbols, sanitize actions)
in the same typed finding shape as pack checks, citing the log head, spec
stamp, presentation pack versions, and drawing scale rendered from. A
separate channel from pack-check results — checks judge the model, a render
report judges one output artifact.

## Renderer limitations

The normative, documented list each backend ships of catalog features it
renders differently or not at all. For a listed feature, verification
degrades to property-level checks explicitly; an undocumented divergence is
a conformance failure.

## Project declaration

A `project.*` command establishing a project-level fact in the log — the
unit system, the CRS, a registry or presentation-pack import. Never an
out-of-band parameter: the log is the only authority. Engineer-authored,
whole-project scope. The unit system must land before any design content
and is immutable thereafter (`missing_declaration` / `immutable_declaration`
refusals); the CRS is metadata and latest-wins; imports are additive and
pin exact versions.

## CRS declaration

An optional recorded fact naming the real-world coordinate reference system a
project's local plane corresponds to (e.g. a UTM zone or state plane zone).
Metadata only — the kernel never transforms coordinates.

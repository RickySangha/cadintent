# Lessons from civil-platform for the openintent spec

- **Date:** 2026-08-02
- **Resolves:** `issues/0013-research-civil-platform-lessons.md`
- **Source oracle:** the private repo `/Users/ricky/Desktop/civil-platform` (docs, issues #16–#29, `engine/src/civil/`, `standards/conventions/`, `docs/reviews/`).
- **No-code-descent rule (restated):** this document extracts *lessons, shapes, and requirements* from the private repo and cites its file paths for traceability only. It contains **no copied code, no test data, and no project/survey data**. All JSON in this document is illustrative pseudo-JSON written fresh for this file; all numeric values in examples are invented.

Context: civil-platform is a working civil-engineering toolkit (Python, ezdxf, CLI-driven by a Claude Code agent) that has been dogfooded on five-plus real drawing sessions. Its design documents (`docs/PRD.md`, `docs/SPEC.md`, `docs/decisions/0001-architecture.md`) already sketch the command-log architecture openintent will standardize; its dogfood issues (#21–#29) and session post-mortems (`docs/reviews/`) are the empirical record of what breaks in practice. The through-line of the whole repo: **quality follows compiling from structured data onto a pristine base; defects follow reconciling stale authored copies.**

---

## 1. Command shapes in practice

*Input to openintent ticket 0017 (command envelope).*

### 1.1 The designed envelope (platform track, not yet built as a log)

`docs/SPEC.md` §2–§3 and `docs/decisions/0001-architecture.md` Q2 define the envelope the platform intends: an append-only per-project command log with

- `project_id` (ULID), `seq` (per-project monotonic bigint, optimistic-concurrency key), `author` (namespaced string: `agent:*`, `engineer:*`, `extractor:*`, `compiler:*`), `kind` (dotted family.verb string), `payload` (validated against a per-kind schema, discriminated union), `basis` (citations: rule IDs, source entity handles, calculation provenance), `created_at`.
- Commands are **immutable once appended** — corrections are new commands.
- Current model = pure deterministic `fold(snapshot, commands)`; replay must be byte-identical after canonical serialization (sorted keys, fixed float formatting), CI-enforced.
- Command families: `project.*`, `existing.*` (author-restricted to extractor/engineer), design (`node.add`, `node.set_attrs`, `node.remove`, `conduit.add/set_attrs/remove`, `alignment.add/set_pis`, `network.add`), `macro.*` (engine-executed; resulting fact commands are appended with a compiler author and calc-provenance basis), and `presentation.*` (`pin_label`, `unpin_label`, `suppress_label`, `keep_entity`, `style_exception`).
- Two schema-level prohibitions that openintent should inherit verbatim: (a) **no design or annotation payload may carry a world coordinate for text placement** — the only coordinate-bearing placement command is `presentation.pin_label`, restricted to engineer authors; (b) **design-agent authors are structurally barred from writing existing-conditions facts** (`existing.*` accepts only extractor/engineer authors). Both are fold-time rejections, not linting.

### 1.2 The mutations the toolkit actually performs today

The toolkit (built before the log exists) expresses mutations as **declarative design files**: JSON documents of typed *elements* applied by a build runner onto a pristine base (`engine/src/civil/design.py`, `engine/src/civil/build.py` `HANDLERS`, `engine/src/civil/elements.py`). These element kinds are, in effect, the field-tested command vocabulary:

| Element kind | What it mutates | Target reference |
|---|---|---|
| `profile_line` | draws a polyline in a profile grid from stations + a value rule (with optional hard `controls`) | grid calibration + station list; layer from conventions |
| `labels` | places convention-formatted text at a line's vertices/segments/stations | named sibling element (`"line": "crown"`) |
| `section_surface` | surface strings in cross-section cells | section-grid calibration |
| `select_inserts` (#22) | selects INSERT blocks by layer/block/region; classifies into named groups by lateral offset to a reference polyline | layer + region + entity handle of the classifying polyline |
| `pair_points` (#22) | greedy nearest-1:1 pairing between two selected groups | group references (`"between": ["bubbles.eos", "bubbles.pl"]`) |
| `set_attribs` (#22) | writes a named ATTRIB tag on selected INSERTs from a rule, formatted per conventions | group reference + tag name |
| `remeasure_dimension` (#26) | moves a defpoint of an auto-measured DIMENSION and re-renders it AutoCAD-faithfully | DXF entity handle |
| `python` | escape hatch (a callable) — explicitly the thing #22 exists to shrink | free-form |

Illustrative fresh pseudo-JSON of the two most instructive shapes:

```json
{"kind": "select_inserts", "id": "bubbles", "layer": "GRADE-BUBBLES",
 "region": [0, 0, 100, 100],
 "classify": {"by_offset_to": "<polyline-ref>",
              "groups": {"on_line": {"max_offset": 0.15}, "off_line": {}}}}

{"kind": "set_attribs", "on": "bubbles.on_line", "tag": "ELEV", "format": "0.01",
 "value": {"rule": "breakline_elev", "params": {"breakline": "BL1"}}}
```

### 1.3 Lessons for the envelope design

1. **Commands carry rules, not values.** The winning pattern everywhere (`engine/src/civil/rules.py`, issues #18/#22) is *design-as-rules*: a value payload is a rule reference plus parameters (`crown_from_pl`, `gutter_from_crown`, `breakline_elev`, `paired_plus_grade`, `existing_at`, `constant`), evaluated through a **no-eval rule registry** — never executable code, never a pre-computed number where a derivation exists. A parametric revision then is one field edit + one rebuild (issue #18's turn-2 acceptance criterion). openintent's command payloads should support expression/rule values as first-class, with the registry closed and versioned.
2. **Selection is a command-level concept.** Real mutations operate on *sets* ("all grade bubbles in this region within 0.15 of that line"), with classification and pairing as intermediate named results referenced by later commands (`bubbles.eos` style dotted refs). The envelope needs either set-valued targets or first-class select/classify commands whose results later commands cite.
3. **Every element application returns a derivation record** (per-target: value written, rule used, sources cited) that lands in the build report (issue #22 acceptance criteria). openintent's fold should require the equivalent: command → per-fact provenance, queryable.
4. **Elements are validated with closed key sets** — unknown keys are rejected (`elements.py` `_reject_unknown`, `SELECT_KEYS` etc.). Schema strictness (`additionalProperties: false` in JSON-Schema terms) is load-bearing: silent key typos otherwise become silent no-ops.
5. **Scope is part of the mutation.** Every design declares `scope: {layers, region}` and the runner audits every touched entity against it (`engine/src/civil/scopeaudit.py`; issue #18 "planted out-of-scope edit caught"). An openintent command batch should be able to declare its intended blast radius and have the kernel verify it.
6. **Macros are suspect by default.** ADR-0001 Q5: every engine-owned macro moves engineering from citable agent reasoning into tool internals — add sparingly; macro results are re-appended as fact commands with compiler authorship and provenance, never applied invisibly.

---

## 2. Identity & naming

*Input to the ULID + derived-names design.*

**The designed rule** (ADR-0001 Q3; PRD story 9): object identity is an **opaque ULID**; human names like "SMH-4" are *derived labels* — re-numberable, never identity. Renumbering must never break references, pins, or history. Provenance (`{author, command_seq, basis}`) is attached to every fact from commit one because "it cannot be retrofitted."

**What the toolkit actually uses today, and what that experience teaches:**

1. **DXF handles are the only identity available in a drawing, and they are fragile evidence, not identity.** Every check finding, every derivation record, and every breakline shot cites handles (`checks.py` `finding(...)` carries a `handles` list; `elevation.py` `Shot.handle`). This works only because the pristine-base convention keeps handles stable within a project; the moment the engineer re-exports from AutoCAD, handles are a new universe. openintent must treat backend/native IDs (handles) as *provenance pointers into a specific file version* (file hash + handle), never as model identity.
2. **Names inside designs are local and human** — element `id`s (`"crown"`, `"bubbles"`), breakline names, group dot-paths. These are readable and diff-able but are only unique within one design document. The ULID+derived-name split resolves the tension: stable machine identity, plus a deterministic naming layer that can be recomputed (and re-sequenced) without touching references.
3. **Derived display entities need derivation tags.** ADR-0001 Q10: every compiled display entity carries its `semantic_id` or a tag of the form `derived:label-of:<id>` — this is what makes click-to-pin and pin survival possible at all, and it "costs nothing now, impossible to retrofit." openintent's presentation layer needs the same: a label is not an entity with its own free identity; it is a derivation of a semantic object's fact.
4. **Identity of *files* matters as much as identity of objects.** The toolkit keys everything to content hashes: the SQLite index stores the source file's sha256/size/mtime and every reader refuses on mismatch (`dxfindex.py`); the pristine manifest records the backup's sha256 (`pristine.py`); extraction approval is `approve {report_checksum}` (SPEC §5). Lesson: openintent snapshots and imported artifacts need content-addressed identity, and any reference to extracted evidence should bind (artifact hash, native id).
5. **Problem observed:** the POC/session era had *no* stable identity, so "the drawing" itself became a second authoritative copy of the design and drifted (the 0.06 m stale-furniture defect, `docs/reviews/2026-07-22-storm-session-review.md`). Identity + single-source derivation is the cure; naming is presentation.

---

## 3. Checks that earned their keep

*Input to tickets 0020/0021 (fold & diff semantics), 0023 (conformance), 0024 (DXF backend). Every check below exists because a real session shipped (or nearly shipped) the defect it catches.*

The check registry lives in `engine/src/civil/checks.py` (`CHECKS`, `applicable()`, `not_runnable()`, `run()`); `civil build` auto-runs the applicable set against the **saved** file and embeds results in the build report, exit 1 on findings (#23). Every finding carries both values, both handles, its sources, and **the tolerance it was judged against**.

| Check | Failure it catches | Forcing incident / issue | Spec/kernel implication |
|---|---|---|---|
| **`labeled_vs_geometry`** conflict detection | a labeled fact and its geometry-derived counterpart disagree beyond tolerance; either could silently win | POC storm session defect 2: agent described directly conflicting evidence as "confirmed" (`docs/reviews/2026-07-22-storm-session-review.md`); issue #19 | Evidence precedence is a kernel rule: explicit labeled values outrank geometry-derived; disagreement ⇒ a conflict *flag carrying both values + evidence refs*, never a silent pick. Prohibit "confirmed" phrasing over conflicting evidence. |
| **`plan_vs_profile_span`** (two-path consistency) | one fact reaching output via two derivations (plan-geometry length vs profile station span) disagreeing | storm defect 1: 113.13 vs 113.09 m, a hand-placed chainage tick vs computed station; ADR-0001 addendum rule 3; #19 | Any fact derivable by two paths gets a compile-gate agreement check within tolerance. In openintent: the fold/compile must enumerate dual-derivation facts and diff them every build. |
| **`band_vs_design`** incl. preserved furniture | stale kept labels disagreeing with current design values | storm defect 2: merged-back build output kept pre-revision invert labels 0.06 m off | Kept/pinned presentation content is validated against the model even though it is never edited; violations reported, not suppressed. |
| **`elev_source_check`** / `elev_at` discipline | a design elevation taken from the nearest raw shot instead of interpolated along the governing breakline | storm defect 3: headwall invert from a shot 6.2 m away when the interpolated value had been computed and discarded; #19, #21, #29 | Elevation-at-a-point is a *typed query* returning `{elevation, kind: surveyed|interpolated, sources, station}`; surveyed and interpolated are never interchangeable; nearest-shot substitution is a flagged deviation. |
| **`attrib_vs_rule`** (independent re-derivation) | build writes a rule-derived value; nothing independently verifies the file matches the rule | 25094 session: the "check is REQUIRED" rule was satisfied *vacuously* — the build script checked its own output; #23 | Verification must be **structural, not instructional**: applicability derived from the design's own content (`set_attribs` present ⇒ check runs), re-derivation done from the saved artifact with fresh assembly, comparison by exact formatted string (numeric tolerance would hide rounding-mode regressions). A design with nothing checkable reports `"none declared"` visibly — a vacuous pass must be distinguishable from a real one. |
| **`clearance`** (clash scan) | proposed linework routed within a minimum distance of point features (street lights, poles, stubs) | 23049 grading session: 2 of 5 correction rounds were spatial clashes (service moved to fix conflict A landed 0.16 m from a street light — conflict B), `docs/reviews/2026-07-28-grading-session-review.md`; #25 | Clash awareness must be a check, not a memory. Distance is point-to-nearest-point-on-segment, never vertex-to-point. **No default minima**: a rule without a stated minimum is refused, not defaulted — required distances are office/municipal data the design must state. |
| **Stale-index refusal** | queries served from a cache of a file that has changed on disk | 19 Ave session staleness ("file-as-truth diverges from the file mid-session"); render-hang-era re-parsing; #17 | Any derived cache is keyed to the content hash of its source and *refuses* (distinct exit code + "re-index" hint) rather than serving stale data. Applies directly to openintent snapshots vs logs. |
| **Scope audit** | a build touching entities outside its declared layers/region | #18 acceptance criterion (planted out-of-scope edit) | "Don't touch anything else" is mechanically verified by pre/post snapshot diff, reported with handle + layer + reasons. |
| **Post-save audit vs pristine baseline** | build introducing structural errors beyond what the base already had | #18; render-hang incident (recover-audit is expensive — run once, post-save only) | Audits compare against a *baseline of the input*, so pre-existing noise doesn't mask regressions and regressions don't hide in pre-existing noise. |
| **DXFIN openability** (`verify-dxfin`, accoreconsole) | the library round-trip passes but the target CAD application rejects the file | 26003 session: AutoCAD LT refused a DXF with empty-name STYLE records that AutoCAD's *own export* created and ezdxf silently tolerated; #28 | The reference implementation's opinion of validity is not the consumer's. Conformance needs an *external-oracle* verification hook; "opted-in but unavailable ⇒ refuse" (a check that could not run is not a pass). |
| **STYLE sanitize** (always-on in build) | same root cause, prevented rather than detected: empty-name flags=0 STYLE records renamed deterministically and idempotently, reported in the build report | #28; `engine/src/civil/acadcompat.py` | Known artifact-level poison patterns get an always-on, idempotent, *reported* sanitize step in the export path. |
| **Render filter by bbox-intersect** | a long polyline crossing a zoom window with no vertex inside silently vanishes from the verification render — a false alarm indistinguishable from missing geometry | 26003 session: a 76 m curb vanished mid-corridor; #27 | Verification tooling itself needs conformance tests: spatial bucketing must be bbox-intersect, not vertex-inside; over-inclusion is harmless, exclusion is a lie. |
| **Render safe-path guardrails** | full-modelspace rendering + recover-loading freezing the machine | `docs/reviews/2026-07-23-render-hang-incident.md`; #17 | Resource guardrails (max-span refusal, entity-count caps, pre-filter) belong *in tools*, not in judgment; enforce with AST-level tests that forbidden APIs appear nowhere in the executable path. |
| **Dimension display-var resolution** (#26) | re-rendered dimensions showing "1,6" instead of "1.60", wrong layer/colour, flattened stacked text | 23049: the same three pitfalls debugged from scratch twice in one session, despite being in prose notes | Pitfall tables must become code that cannot hit the pitfall; display-variable resolution follows a documented precedence and *reports the source of every value used*. |
| **Breakline station-vs-chain measures** (#29) | `station=` queries resolved against cumulative chord distance instead of polyline stationing — up to ~0.9 m elevation error at the observed worst point | 22077/169 St existing-ground work | When two measures exist along a linear feature, the API names which one every answer used (`measure: polyline|chain`), and **refuses loudly** the query that conflates them ("a chord chain is not a chainage"), offering the honest alternative. |

Meta-lessons for the conformance/kernel tickets:

- **Checks graduate: prose → named tool → enforced architecture** (render-hang review). Each step removes a failure mode class. openintent's spec is the third stage; its conformance suite should encode each check above as fixture cases (the toolkit keeps a fixture drawing that reproduces all three storm-session defects, per #19).
- **Findings are evidence objects**: `{check, message, both values, refs/handles, sources, tolerance-used}`. Exit codes are part of the contract (0 clean / 1 findings / distinct code for "could not run").
- **Tolerances are data, documented, overridable per design — but never edited to make a finding disappear** (template rule §8). Real findings at the edge of survey quality are "an engineering call, not a tolerance to edit" (#29's tail findings).

---

## 4. Label / attrib / block lessons

*Input to ticket 0022 (presentation schemas).*

1. **Label content is always derived; label placement is the only human-owned degree of freedom.** The POC measured ~10% of manual fixes as content errors and ~90% as position fixes, and hand-fixed positions reverting on rebuild was "the single biggest workflow pain" (`docs/PRD.md`). Hence the three-model factoring (existing / design / presentation) and pins as durable override data keyed to semantic IDs (ADR-0001). openintent's presentation layer should define: pin, unpin, suppress, keep, style-exception — all referencing semantic IDs, never output entities.
2. **Conventions are mined, not hand-specified — and resolved nearest-first.** `civil conventions mine` extracts label conventions from an issued exemplar region down to text style, height, width, rotation, halign/valign codes, align-point pairing offsets, row baselines, and linetype scales (`engine/src/civil/conventions.py`; the mined artifact `standards/conventions/22077-profile-labels.json`; issue #18). Two hard-won refinements: (a) what the exemplar *cannot* prove is flagged `derived: false` and falls back to office defaults — mining is honest about its evidence; (b) precedence is **same drawing → same office → jurisdiction** — the watermain session succeeded precisely because it cloned in-drawing exemplars, while the POC's generic conventions pack produced translation errors (`docs/reviews/2026-07-23-watermain-session-review.md`). An exemplar also tells you *how* something was drafted, not *whether the situation calls for it* (23049 review) — conventions need applicability conditions, not just formats.
3. **Declarative attrib elements (#22).** Filling block-attribute values from rules had no declarative path, so a whole session's design lived in a 148-line Python escape hatch; #22 replaced it with ~30 lines of JSON (`select_inserts` → `pair_points` → `set_attribs`). Shape lesson for the spec: attributed symbols (blocks with named text tags) are a first-class presentation primitive; writing a tag value = (selection, tag name, rule, format). Formatting is part of the contract — decimal quantum with ROUND_HALF_UP semantics, because bankers'-rounding float formatting demonstrably disagrees with issued drawings (#18's validation found four real labels that plain float formatting gets wrong).
4. **attrib_vs_rule (#23)** — see §3. The presentation-layer corollary: whenever the model writes a *formatted string* into an artifact, verification compares the string, and the check must be a fresh derivation from the saved artifact, not a readback of the build's in-memory value.
5. **Literal-text attribs**: some ATTRIB values are literal engineer text, not rule-derived (commit `b862671` "literal-text attribs"). The schema must distinguish `value: {rule...}` from `value: {literal...}` so the checker knows what is verifiable and reports the rest as such — the visible-vacuity principle again.
6. **Placement pain in the wild** (23049 review): leader arrowheads inherited `dimasz × dimscale` and rendered 2.9 m long; block-tiling + arrow entities were used where the office convention was a single polyline with a shape linetype and vertex-order-as-direction; dimension re-rendering was a minefield (#26). Implications: (a) symbol catalogs must carry display-scale semantics explicitly; (b) direction/orientation can be encoded in geometry order rather than extra entities — presentation schemas should allow that idiom; (c) anything the renderer of record displays differently from the reference library (SHX shape linetypes, stacked-text `\X`, dimstyle-scaled arrowheads) must be a documented renderer-limitations list so verification degrades to property-level checks explicitly.
7. **Rules ingestion from conversation is a real mechanism.** Twice in a row (watermain, grading reviews) drafting rules taught by the engineer in chat had nowhere durable to land, and reappeared as correction rounds. openintent should define a path from "engineer statement" to "cited, engineer-confirmed conventions/rules entry" — rule packs are data with provenance, including *unverified* status (the joint-deflection placeholder is explicitly flagged engineer-unverified in ADR-0001; never claim compliance from unverified values).

---

## 5. Geometry / units / tolerance practices

*Input to ticket 0018 (geometry and units).*

Observed practice (all in project world units = metres; stations in metres with `SS+ss.ss` display formatting; grades in %):

- **Quantization is explicit and central**: design elevations round to 0.01 m, grades to 0.1 %, both as decimal-string quanta evaluated with ROUND_HALF_UP (`engine/src/civil/rules.py` `ELEV_QUANTUM`/`GRADE_QUANTUM`; the Decimal rule is "load-bearing, and the real file proves it" — #18). The spec should carry per-quantity quanta and rounding mode as schema-level facts, not formatting conveniences.
- **Check tolerances, documented and overridable**: elevation 0.01 m, length 0.02 m, station 0.02 m (`checks.py` `DEFAULT_TOLERANCES`). Every finding names the tolerance it was judged against.
- **Breakline/elevation service tolerances** (`engine/src/civil/elevation.py`): query-within-0.05 m-of-a-shot ⇒ `surveyed`, else `interpolated`; lateral tolerance beyond which a query is *refused*; max-gap between shots beyond which assembly is refused; extrapolation past the string ends is refused unless explicitly requested ("`--extrapolate` invents ground and must be stated out loud"). The pattern: **every tolerance has a refusal on the other side of it** — the library would rather throw a typed refusal (`ElevationRefused`) than invent an answer.
- **Arcs are tessellated by chord-deviation tolerance** (0.01 m max chord deviation, minimum segment count) into polylines for all distance/projection math (`engine/src/civil/geometry.py`); point-to-line distance is nearest-point-on-segment with per-segment clamping (#24, #25). Projection math is implemented **once, in one module**, shared by stationing, measuring, classification, and clearance (#24: "shares projection math with #21 — implement once").
- **Profile/section spaces are affine world-space regions**: profile grids map station/elevation ↔ world x/y via anchor + units-per-metre calibrations with vertical exaggeration (e.g. 10:1 profiles, 5:1 sections), stored in project notes and referenced — never restated — by designs (`engine/src/civil/design.py` header, `drafting.py`). Profiles are *world-space content* viewed through sheet viewports (ADR-0001 Q10). openintent's geometry ticket should model these calibrated sub-spaces explicitly.
- **Two measures along a linear feature** (#29): chord-chain distance vs stationing along a governing polyline are different quantities; the observed divergence reached metres over a 250 m string. Every station-parameterized answer must name its measure; conflating them is a refusal.
- **Bboxes are an index/prefilter concept, never geometry**: bbox tests may over-include (harmless) but must never exclude an intersecting entity (#27); true distances always come from full vertex geometry loaded fresh (#24: "bboxes in the index are not enough — that's the point").
- **Determinism as a stated property**: fold/replay byte-identical under canonical JSON (sorted keys, fixed float formatting) per SPEC §2.3; builds idempotent (restore-then-build twice ⇒ semantic diff empty, #18 tests).

---

## 6. Top 10 "must be structurally impossible in openintent"

Each item names the pain and its evidence trail; the spec should make the state *unrepresentable*, not merely checked.

1. **A hand-authored copy of a derived fact.** Label content typed by hand drifted 0.06 m from the design and was defended as "existing labels, don't change" (storm review defect 2). In openintent, label content has no storage location — it exists only as a derivation of model facts; the schema has no field to write it.
2. **Merge-back: build output re-ingested as design input.** The entire 0.06 m defect class "exists only because a DXF round-trip made the drawing a second authoritative-looking copy" (ADR-0001 addendum rule 1; PRD). Compiled artifacts must be typed as *outputs*: no command kind accepts a compiled artifact as a source of design facts.
3. **A coordinate parameter for text placement in any design/agent command.** The POC's placement failure mode; SPEC §3 hard rule; ADR-0001 Q5 ("deliberately no parameter anywhere for a label coordinate"). Placement is compiler-owned; the only placement override is an engineer-authored presentation pin referencing a semantic ID.
4. **Design agents writing existing-conditions facts.** The base could otherwise be quietly adjusted until the design passes (PRD story 22; SPEC fold rejects forbidden authors). Author-kind restrictions are fold-time schema, not policy.
5. **Silent resolution of conflicting evidence.** Labeled-vs-geometry disagreement was once narrated as confirmation (storm review). Extraction/import output types must force a three-way status — agreed / conflict-with-both-values / flagged — with no representable "picked one silently."
6. **A pass that verified nothing (vacuous checks).** The 25094 session met "checks are required" with zero runnable checks; the build was its own witness (#23). Conformance report schema must make "nothing was independently verified" a distinct, visible status, and check applicability must be derived structurally from document content, never opted into.
7. **Stale derived state served as current.** Stale index (T1), stale mid-session file (19 Ave), stale pristine (build refusal), stale LB-placement constraint (23049 round 4). Every derived artifact carries the content hash of its source and readers refuse on mismatch; snapshots that don't fold to the log head are unusable, not quietly usable. (The 23049 constraint case adds a forward requirement: positional dependencies between elements should be recorded so orphaned constraints flag their dependents — a "constraint ledger".)
8. **Interpolated and surveyed elevations interchangeable — or a station resolved against an unnamed measure.** Nearest-shot substitution (storm defect 3) and chord-vs-polyline stationing (#29, errors up to ~0.9 m) are both category errors the type system can prevent: elevation results are tagged `surveyed|interpolated` with cited sources, station answers are tagged with their measure, and mixed-measure queries are unrepresentable or refused.
9. **Compliance claims from unverified rule values.** Joint-deflection and clearance minima are engineer-unverified placeholders or deliberately absent defaults (#25: no `DEFAULT_CLEARANCES` anywhere — "the config defaults should come from Ricky, not be invented"). Rule-pack entries carry a verification status; a check judged against an unverified or absent value must say so; a missing required minimum is a refusal, not a default.
10. **Out-of-scope mutation without a trace.** "Don't touch anything else" was a promise until the scope audit made it a report (#18). Command batches declare scope; the kernel diffs actual effect against declared scope; an undeclared effect is a rejected fold or a mandatory finding — never silent.

Honourable mentions that shaped the toolkit but rank below the ten: resource-unbounded verification tooling (render-hang incident — guardrails in tools, not judgment); reference-library validity standing in for consumer validity (#28 — external oracle hooks in conformance); verification renders that can silently omit intersecting geometry (#27).

---

## Appendix — traceability map

| Topic | Primary civil-platform sources |
|---|---|
| Envelope, fold, authors, command kinds | `docs/SPEC.md` §§2–3, `docs/decisions/0001-architecture.md` Q2/Q5, `docs/PRD.md` |
| Element/command vocabulary in practice | `engine/src/civil/elements.py`, `build.py` (`HANDLERS`, `run_build`), `design.py`, `rules.py`, `engine/examples/*.json`, issues `0018`, `0022`, `0026` |
| Identity & naming | ADR-0001 Q3/Q10, SPEC §4, `dxfindex.py`, `pristine.py`, storm review |
| Checks | `engine/src/civil/checks.py`, `scopeaudit.py`, `acadcompat.py`, `render.py`, `dimensions.py`, issues `0019`, `0023`–`0029`, `docs/reviews/*` |
| Labels/attribs/conventions | `conventions.py`, `standards/conventions/22077-profile-labels.json` (structure only), issues `0018`, `0022`, `0023`, `0026`, watermain + grading reviews |
| Geometry/units/tolerances | `rules.py`, `checks.py`, `elevation.py`, `geometry.py`, `drafting.py`, issues `0021`, `0024`, `0027`, `0029` |
| Workflow rules the kernel should absorb | `engine/src/civil/templates/CLAUDE.md` (nine binding rules), `docs/TOOLKIT-PLAN.md` |

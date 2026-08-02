# Name availability research: `openintent`

**Date:** 2026-08-02
**Resolves:** `issues/0011-research-name-availability.md`

Question: is `openintent` available and unencumbered for an open-source engineering-design-format project ("an open, typed intermediate representation for engineering/CAD design intent") — and if not, what are the best fallbacks?

**Verdict up front: no.** The name is heavily encumbered on every axis checked — GitHub org taken, PyPI package taken by an active project, all three obvious domains registered, and at least three distinct live-ish projects already trade under "OpenIntent" or a near-identical name, two of them in adjacent spaces (design-tool interchange schemas; AI-agent tooling). Best clean fallbacks: **`cadintent`** and **`intentform`** (fully clear across all checks), with `intentir` a close third.

---

## 1. GitHub

| Handle | Status | Evidence |
|---|---|---|
| `openintent` | **Taken** — org, created 2025-11-03, display name "OIML" (Open Intent Modeling Language), 1 repo (`openintent/oiml`, "a standard for AI-driven development that enables declarative code generation through structured intents", Apache-2.0, 0 stars, last push 2025-11-27) | https://github.com/openintent · `api.github.com/orgs/openintent` |
| `openintent-project` | **Available** (GitHub API 404) | `api.github.com/users/openintent-project` |
| `open-intent` | **Taken** — org "OpenINTENT", created 2023-07-16, 0 public repos (parked/squatted) | https://github.com/open-intent |
| `openintents` | **Taken** — the classic Android OpenIntents org (id 311533, since ~2010) | https://github.com/openintents |
| `openintent-ai` | **Taken** — home of the OpenIntent Coordination Protocol (see §5) | https://github.com/openintent-ai/openintent |

## 2. PyPI

- **`openintent` — taken and active.** "Python SDK and Server for the OpenIntent Coordination Protocol" — durable, auditable coordination between humans and AI agents. v0.17.0 released **2026-03-24**; homepage `openintent.ai`, repo `github.com/openintent-ai/openintent`. This is a live, actively-released project. https://pypi.org/project/openintent/
- Close variants `open-intent`, `open_intent`, `openintents`: **not registered** (PyPI JSON API 404) — but PyPI normalizes `open-intent`/`open_intent`/`openintent` to the *same* canonical name, so those are not actually claimable as separate packages. Effectively the entire `openintent` name family on PyPI is gone.
- `intentspec` — taken ("Coverage and enforcement layer for AI agent infrastructure", v0.3.0). https://pypi.org/project/intentspec/

## 3. npm

- **`openintent` — available** (registry 404). https://registry.npmjs.org/openintent
- `open-intent` — **taken**: "An API for the open-intent chatbots", last publish 2022-06-22 (v1.0.27), dormant chatbot-framework leftovers. https://registry.npmjs.org/open-intent
- Note: npm forbids new names that differ from an existing package only by punctuation, so `openintent` may be rejected at publish time as too similar to `open-intent` even though the GET is a 404.

## 4. Domains (RDAP lookups, 2026-08-02)

| Domain | Status | Registered | Registrar |
|---|---|---|---|
| openintent.org | **Registered** | 2025-02-10 (expires 2027-02-10) | GoDaddy |
| openintent.io | **Registered** | 2026-05-28 (expires 2028-05-28) | GoDaddy |
| openintent.dev | **Registered** | 2025-08-30 (expires 2026-08-30) | GoDaddy |
| openintent.ai | **Registered and in use** — homepage of the OpenIntent Coordination Protocol | per PyPI metadata | — |

Sources: `rdap.publicinterestregistry.org` (.org), `rdap.identitydigital.services` (.io), `pubapi.registry.google` (.dev). All three carry client-transfer-prohibited status, i.e. real registrations, not just parked drops.

## 5. Existing projects named OpenIntent / close variants

1. **google/openintent — Wi-Fi/network design interchange schema. Most serious collision.** "A collaborative effort by network operators, manufacturers and tooling companies to develop an interoperability standard schema to describe the necessary information needed to deploy network equipment." Apache-2.0, 42 stars, 112 commits, backed by Google with vendor participation (Hamina Network Planner ships OpenIntent import/export; Aruba engaged). Active, and it is *literally an open interchange schema for engineering-design tools* — the same conceptual category as this project, just for wireless networks instead of CAD. Confusion is near-certain. https://github.com/google/openintent · https://docs.hamina.com/hamina/live/openintent
2. **OpenIntent Coordination Protocol (openintent-ai) — active, 2026.** AI-agent coordination protocol with a shipping Python SDK (`pip install openintent`), 21 RFCs, docs site, `openintent.ai` domain. Adjacent audience (AI tooling / typed intent schemas). Owns the PyPI name outright. https://github.com/openintent-ai/openintent · https://openintent.ai
3. **OIML / github.com/openintent — "Open Intent Modeling Language".** Young (Nov 2025), 0 stars, near-dormant, but it squats the exact GitHub handle and uses "Open Intent" for a typed-intent standard — uncomfortably close framing.
4. **OpenIntents (Android)** — venerable open-source Android project (openintents.org, github.com/openintents), largely dormant, but long-established name recognition in the Android-Intents sense. Distant audience; low severity, but adds to the crowding. https://github.com/openintents · http://www.openintents.org/pages/projects/
5. **open-intent chatbot framework** — dead (npm last publish 2022; the GitHub `open-intent` org is now an empty shell). Low severity, but it holds the npm `open-intent` name, which blocks the hyphenated npm variant and possibly `openintent` via npm's similar-name rule.
6. **"Open intent detection/discovery"** is also a standing term of art in NLU research (open-intent classification benchmarks/toolkits, e.g. the intent-detection topic space on GitHub), so search results for the name will always be polluted by chatbot/NLU literature.

## 6. Trademark red flags

No registered "OpenIntent" trademark surfaced in searches (Justia trademark results show no OpenIntent owner), and none of the projects above appear to be commercial trademark holders. However: (a) google/openintent is a Google-hosted industry consortium — Google's lawyers are a bad party to be confusingly-similar with; (b) openintent.ai is a live product-shaped project that could commercialize; (c) the OpenAI-vs-Open-Artificial-Intelligence litigation (2025) shows "Open + <word>" names do get fought over. No hard legal bar found, but the practical crowding alone is disqualifying.

---

## Fallback candidates

All checked 2026-08-02 against GitHub (users API), PyPI (JSON API), npm (registry), and RDAP for .org/.dev/.io. "Free" = 404/unregistered.

### `cadintent` — fully clean
GitHub free · PyPI free · npm free · cadintent.org / .dev / .io all unregistered. Says exactly what the project is (CAD + design intent). No colliding projects found. Downside: "CAD" may read narrower than "engineering design" if scope grows beyond CAD.

### `intentform` — fully clean
GitHub free · PyPI free · npm free · intentform.org / .dev / .io all unregistered. Nice double reading ("a form/format for intent"). Slight risk of reading as a web-forms product.

### `intentir` — clean except GitHub handle
PyPI free · npm free · intentir.org / .dev / .io all unregistered. GitHub org `intentir` exists but is an **empty squat created 2026-05-16** (0 repos, no name/bio); `intentir-project` or similar would work, or the handle may be reclaimable via GitHub's dormant-name process. "Intent IR" is the most technically precise name for a typed intermediate representation.

### `designintent` — partially encumbered
PyPI free · npm free · designintent.dev unregistered, but GitHub user `designintent` taken (empty account, created 2026-07-05) and designintent.org / .io registered. Also a generic term of art in CAD literature ("design intent" is standard parametric-CAD vocabulary), which is good for meaning but bad for searchability and ownability.

### `intentspec` — effectively taken
GitHub org exists (empty, Mar 2026), **PyPI taken by an active AI-agent-infrastructure package (v0.3.0)**, npm taken, all three domains registered. Not viable.

## Recommendation table

| Name | GitHub | PyPI | npm | .org/.dev/.io | Collision risk | Verdict |
|---|---|---|---|---|---|---|
| **openintent** | taken (OIML org) | taken, active | free (but similar-name rule) | all registered | **High** — Google Wi-Fi schema + active AI protocol + OIML | **Reject** |
| **cadintent** | free | free | free | all free | None found | **Recommend** |
| **intentform** | free | free | free | all free | None found | **Strong alternate** |
| **intentir** | squatted (empty) | free | free | all free | Low (empty squat only) | Viable if GitHub handle variant acceptable |
| designintent | taken (empty) | free | free | .dev only free | Medium — generic CAD term, 2 domains gone | Weak fallback |
| intentspec | taken (empty) | taken, active | taken | all registered | High | Reject |

**Recommendation:** drop `openintent`; adopt **`cadintent`** (or `intentform` if the CAD framing feels too narrow), and register the GitHub org, PyPI/npm names, and at least the .org and .dev domains promptly — the empty squats on `intentir`/`designintent`/`intentspec`, all created within the last five months, show this namespace is being actively land-grabbed.

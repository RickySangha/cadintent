# Renderer limitations — cadintent DXF backend (normative, v0)

Per #22 decision 9 and #24 decision 6, this backend ships a normative list of
catalog features it renders differently or not at all. For listed features,
verification degrades to property-level checks explicitly. **An undocumented
divergence is a conformance failure.**

1. **SHX shape linetypes** — not emitted; linetypes render CONTINUOUS unless
   the template DXF defines them. Verification degrades to layer/linetype-name
   property checks.
2. **Stacked text** (`\X` and friends) — never emitted; MTEXT verification is
   plain-content only.
3. **Fonts** — text style names map to TEXTSTYLE records; SHX/TTF fonts are
   referenced by name, never shipped. Rendered text extents are unverifiable;
   checks compare style name + height only.
4. **Dimensions** — no DIMENSION entities in v0 at all (the entire
   dimstyle-scaled-arrowhead minefield is out of scope, not partially
   entered).
5. **Annotative text** — not used; paper-mm heights become fixed model
   heights via the drawing scale at render (#22 decision 3).
6. **Colors / lineweights** — not in the v0 catalog; layers are created with
   defaults and carry no honoured color contract.

Additional documented behavior (not divergences, stated for completeness):

- Target version is **R2010 (AC1024)**; model space only, one drawing scale
  per render, naive placement (charter #4).
- "Opens clean" means the **ezdxf headless round-trip** (fresh readfile +
  zero-error audit + exact re-derivation of derived strings), explicitly not
  AutoCAD's opinion. The external DXFIN oracle (`CADINTENT_ACCORECONSOLE`)
  is an opt-in local hook with could-not-run visibility — never claimed in
  CI.
- Template blocks are assumed drawn at **unit nominal size** (1 drawing
  unit); the INSERT scale is the symbol's resolved size (`paper` sizes are
  paper mm × drawing scale; `model` sizes are SI metres).

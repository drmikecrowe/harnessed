<overview>
Redesign workflow. Modernise an existing site without breaking what works. Audit first, then evolve or overhaul. Misclassifying the mode (greenfield vs preserve vs overhaul) is the single biggest source of bad redesign output.
</overview>

<required_reading>
Read these NOW:
1. references/redesign.md (mode detection, audit, preservation, levers, what never changes silently)
2. references/brief-and-dials.md (dial reading of the EXISTING site is your starting point)
3. references/design-directives.md (visual rules to apply during evolution)
4. references/ai-tells.md (patterns to retire in the existing site)
5. references/static-sites.md OR references/app-stack.md (match the existing site's stack unless migrating)
6. references/performance-a11y-darkmode.md (honor existing a11y wins; do not regress)
</required_reading>

<process>
<step name="1. Detect the mode">
Per redesign.md, classify: Greenfield, Redesign-Preserve, or Redesign-Overhaul. If ambiguous, ask ONCE: <i>"Should this redesign preserve the existing brand, or are we starting visually from scratch?"</i>
</step>

<step name="2. Audit before touching">
Document the current state: brand tokens (colors, type, logo, radii); information architecture (page tree, nav, conversion paths); content blocks (what exists, what works, what's filler); patterns to preserve (signature interactions, recognisable hero, copy voice); patterns to retire (AI-slop tells, broken layouts, dead links, generic stock, perf traps); a dial reading of the existing site (its current VARIANCE/MOTION/DENSITY is the starting point, not the baseline); and the SEO baseline (ranking pages, meta, structured data, OG cards). SEO migration is the #1 redesign risk.
</step>

<step name="3. Read the dial of the existing site">
Infer the current dials from the live site. That baseline governs the redesign: Preserve = match existing VARIANCE/DENSITY, MOTION +1; Overhaul = +2 VARIANCE, +2 MOTION, match DENSITY.
</step>

<step name="4. Preserve what works">
Do not change IA unless asked (keep slugs, anchor IDs, nav labels stable for SEO and muscle memory). Extract brand colors before applying design-directives.md color rules - a brand that is already purple stays purple (LILA RULE override). Preserve copy voice unless asked for a rewrite. Honor existing accessibility wins (focus states, alt text, keyboard nav, contrast). Respect existing analytics events (do not rename tracked buttons/fields/IDs).
</step>

<step name="5. Evolve via the modernisation levers (in order)">
Apply in priority order; stop when the brief is satisfied:
1. Typography refresh (biggest lift per unit of risk).
2. Spacing & rhythm (increase section padding, fix vertical rhythm).
3. Color recalibration (desaturate, unify neutrals, keep brand accent).
4. Motion layer (MOTION_INTENSITY-appropriate micro-interactions on existing components).
5. Hero & key-section recomposition (reference-vocabulary.md patterns).
6. Full block replacement (only when a block is unsalvageable).
</step>

<step name="6. Decide: targeted evolution vs full redesign">
If IA, content, and SEO are sound -> targeted evolution (Levers 1-4): ~70% of value at ~40% of risk. If visual debt is structural (broken IA, no design system, broken mobile) -> full redesign with strict content preservation. If the brand itself is changing -> greenfield (use build-site.md).
</step>

<step name="7. Honor what never changes silently">
Never modify without explicit user approval: URL structure / route slugs; primary nav labels; form field names or order; brand logo or wordmark; existing legal / consent / cookie copy.
</step>

<step name="8. Run the pre-flight check">
Run workflows/pre-flight-check.md. Fix every failing box before delivering.
</step>
</process>

<success_criteria>
- Mode correctly detected and stated (greenfield / preserve / overhaul)
- Full audit performed before proposing changes (brand tokens, IA, content, SEO baseline)
- Existing site's dial reading used as the starting point, not the baseline
- IA, slugs, nav labels, analytics IDs, and copy voice preserved unless explicit approval given
- Modernisation applied via the levers in priority order
- Redesigned surfaces pass design-directives.md and ai-tells.md; ZERO em-dashes
- Existing accessibility wins honored (no regressions)
- Pre-flight check passes every box
</success_criteria>

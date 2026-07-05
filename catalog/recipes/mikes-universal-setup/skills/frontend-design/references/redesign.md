<overview>
Redesign protocol. This skill handles greenfield builds AND redesigns. Misclassifying the mode is the single biggest source of bad redesign output. Detect the mode first, audit before touching, preserve what works, evolve deliberately.
</overview>

<detect_mode>
First action: classify.
- <b>Greenfield</b> - no existing site, or full overhaul approved. Dial baseline from brief-and-dials.md.
- <b>Redesign - Preserve</b> - modernise without breaking the brand. Audit first, extract brand tokens, evolve gradually.
- <b>Redesign - Overhaul</b> - new visual language on top of existing content. Treat as greenfield for visuals; preserve content and IA.

If ambiguous, ask ONCE: <i>"Should this redesign preserve the existing brand, or are we starting visually from scratch?"</i>
</detect_mode>

<audit_before_touching>
Document the current state before proposing changes:
- <b>Brand tokens</b> - primary / accent colors, type stack, logo treatment, radii.
- <b>Information architecture</b> - page tree, primary nav, key conversion paths.
- <b>Content blocks</b> - what exists, what's doing work, what's filler.
- <b>Patterns to preserve</b> - signature interactions, recognisable hero, copy voice.
- <b>Patterns to retire</b> - AI-slop tells, broken layouts, dead links, generic stock imagery, perf traps.
- <b>Dial reading of the existing site</b> - infer current DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY. That is your starting point, not the baseline.
- <b>SEO baseline</b> - current ranking pages, meta titles, structured data, OG cards. SEO migration is the #1 redesign risk.
</audit_before_touching>

<preservation_rules>
- <b>Do not change information architecture</b> unless asked. Keep page slugs, anchor IDs, primary nav labels stable for SEO and muscle memory.
- <b>Extract brand colors before applying design-directives.md color rules.</b> A brand that is already purple stays purple - apply the LILA RULE override.
- <b>Preserve copy voice</b> unless asked for a rewrite. Visual modernisation is not a content rewrite.
- <b>Honor existing accessibility wins.</b> Do not regress focus states, alt text, keyboard nav, contrast.
- <b>Respect existing analytics events.</b> Do not rename buttons, form fields, section IDs that downstream tracking depends on.
</preservation_rules>

<modernisation_levers>
Apply in order; stop when the brief is satisfied:
1. <b>Typography refresh</b> - biggest visual lift per unit of risk.
2. <b>Spacing & rhythm</b> - increase section padding, fix vertical rhythm.
3. <b>Color recalibration</b> - desaturate, unify neutrals, keep brand accent.
4. <b>Motion layer</b> - add MOTION_INTENSITY-appropriate micro-interactions to existing components.
5. <b>Hero & key-section recomposition</b> - restructure top-of-funnel using reference-vocabulary.md patterns.
6. <b>Full block replacement</b> - only when the existing block is unsalvageable.
</modernisation_levers>

<decision_tree>
- IA, content, and SEO sound -> <b>targeted evolution</b> (Levers 1-4). ~70% of value at ~40% of risk.
- Visual debt is structural (broken IA, no design system, broken mobile) -> <b>full redesign</b> with strict content preservation.
- Brand itself is changing -> <b>greenfield</b>.
</decision_tree>

<what_never_changes_silently>
Never modify without explicit user approval:
- URL structure / route slugs.
- Primary nav labels.
- Form field names or order (breaks analytics + autofill).
- Brand logo or wordmark.
- Existing legal / consent / cookie copy.
</what_never_changes_silently>

<overview>
Performance, accessibility, and dark-mode guardrails. Apply to every build, static or app. The dark-mode protocol covers token strategy and what the brief (not this skill) decides.
</overview>

<hardware_acceleration>
- Animate ONLY `transform` and `opacity`. Never animate `top`, `left`, `width`, `height`.
- Use `will-change: transform` sparingly - only on elements that will actually animate.
</hardware_acceleration>

<reduced_motion>
- Any motion above MOTION_INTENSITY > 3 MUST honor `prefers-reduced-motion`. Non-negotiable.
- In Motion: wrap with `useReducedMotion()` and degrade to static. On static sites: feature-detect `window.matchMedia('(prefers-reduced-motion: reduce)')` and skip JS-driven animation.
- In CSS: gate animations behind `@media (prefers-reduced-motion: no-preference)` or provide an override block under `@media (prefers-reduced-motion: reduce)` that disables.
- Infinite loops, parallax, scroll-hijack, and magnetic physics MUST collapse to static / instant under reduced motion.
</reduced_motion>

<dark_mode_mandatory>
- Design for BOTH modes from the start. Never ship light-only or dark-only without explicit user instruction.
- Use Tailwind `dark:` variant OR CSS variables for tokens. Pick one strategy per project.
- Do not prescribe specific dark-mode colors here. The brief decides. Maintain visual hierarchy, brand identity, and WCAG AA contrast (AAA for body) across both modes.
- Respect `prefers-color-scheme: dark`. Default to system preference unless the brand insists on one mode.
</dark_mode_mandatory>

<core_web_vitals>
- <b>LCP</b> < 2.5s. Hero image must be preloaded (or `next/image priority` in the app stack).
- <b>INP</b> < 200ms. Heavy work off main thread.
- <b>CLS</b> < 0.1. Reserve space for images, fonts, embeds.
- Run Lighthouse before declaring a page done. Static sites should hit these easily (see static-sites.md perf_notes).
</core_web_vitals>

<dom_cost>
- Apply grain / noise filters EXCLUSIVELY to fixed, `pointer-events-none` pseudo-elements (e.g. `fixed inset-0 z-[60] pointer-events-none`). NEVER on scrolling containers - continuous GPU repaints destroy mobile FPS.
- Be aware of bundle size. Motion is not tiny. Three.js is large. Lazy-load anything not above the fold. On static sites, ship near-zero JS by default.
</dom_cost>

<z_index_restraint>
NEVER spam arbitrary `z-50` or `z-10`. Use z-index strictly for systemic layer contexts (sticky navbars, modals, overlays, grain). Document the z-index scale in a project constants file (or a CSS variables block on static sites).
</z_index_restraint>

<dark_mode_protocol>
Dual-mode by default. Never assume light-only unless the brief is print-emulating editorial.

<token_strategy>
Pick one, stick to it:
- <b>Tailwind `dark:` variant</b> (default for utility-first projects): every color utility paired with its dark variant (`bg-white dark:bg-zinc-950`, `text-gray-900 dark:text-gray-100`).
- <b>CSS variables</b> (for shadcn/ui, Radix Themes, or component libraries with theming, and the natural choice for plain-CSS static sites): define semantic tokens (`--surface`, `--surface-elevated`, `--text-primary`, `--accent`) and swap values under `[data-theme="dark"]` or `@media (prefers-color-scheme: dark)`.
</token_strategy>

<what_this_skill_enforces>
The brief and brand decide specific colors. This skill enforces only:
- <b>Contrast</b> - WCAG AA minimum for body text, AAA target for hero copy.
- <b>Hierarchy parity</b> - visual hierarchy that works in light must work in dark. If a CTA pops in light, it pops in dark.
- <b>Brand fidelity</b> - primary brand color stays recognisable. Don't desaturate the brand into a dark mode.
- <b>No pure `#000000` and no pure `#ffffff`</b> - use off-black (zinc-950, near-black warm gray) and off-white. Pure values kill depth.
</what_this_skill_enforces>

<default_mode_and_testing>
- Respect `prefers-color-scheme` unless the brand insists. Add a manual toggle if either mode would lose key brand expression.
- <b>Test in both modes before finishing.</b> Open the page in both modes during development. Do not ship a page you have only seen in one mode.
</default_mode_and_testing>
</dark_mode_protocol>

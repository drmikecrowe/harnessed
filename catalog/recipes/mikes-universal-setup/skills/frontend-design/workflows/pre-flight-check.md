<overview>
Final pre-flight check. Run this matrix before delivering any page. This is the last filter. Run every box. If any box fails, the output is not done.
</overview>

<required_reading>
You should already have read the reference each box points to. Re-open one if a box is unclear.
</required_reading>

<process>
This is mechanical. Work top to bottom, tick each box honestly. If a box cannot be ticked, stop and fix it before continuing.

<setup_checks>
- [ ] Brief inference declared (the one-line design read from brief-and-dials.md)?
- [ ] Dial values explicit and reasoned from the brief, not silently using the baseline?
- [ ] Design system chosen from design-systems.md if applicable, or aesthetic labeled honestly?
- [ ] Redesign mode detected and audit performed (if a redesign - redesign.md)?
</setup_checks>

<hard_locks>
- [ ] <b>ZERO em-dashes anywhere on the page.</b> Headlines, eyebrows, pills, body, quotes, attribution, captions, buttons, alt text. Zero. (ai-tells.md em_dash_ban - non-negotiable.)
- [ ] Page Theme Lock: ONE theme (light, dark, or auto) for the whole page. No section flips to inverted mode mid-page (design-directives.md theme_lock)?
- [ ] Color Consistency Lock: one accent color used identically across all sections (design-directives.md color)?
- [ ] Shape Consistency Lock: one corner-radius system applied consistently (design-directives.md materiality_and_cards)?
</hard_locks>

<a11y_checks>
- [ ] Button Contrast Check: every CTA text readable against its background (no white-on-white, WCAG AA 4.5:1)?
- [ ] CTA Button Wrap: no CTA label wraps to 2+ lines at desktop?
- [ ] Form Contrast Check: form inputs, placeholders, focus rings, labels all pass WCAG AA against the section background?
- [ ] Serif discipline: if a serif is used, it is NOT Fraunces or Instrument_Serif (or is, with explicit brand justification)? Different serif from your previous project?
- [ ] Premium-consumer palette check: if the brief is premium-consumer, the palette is NOT the AI-default beige+brass+oxblood+espresso family? Different family from your previous premium-consumer project?
- [ ] Italic descender clearance: every italic word with `y g j p q` has `leading-[1.1]` min + `pb-1` reserve?
</a11y_checks>

<hero_checks>
- [ ] Hero fits the viewport: headline <= 2 lines, subtext <= 20 words AND <= 4 lines, CTA visible without scroll, font scale planned around image?
- [ ] Hero top padding: max `pt-24` at desktop, hero content does not float halfway down the viewport?
- [ ] Hero stack discipline: max 4 text elements in hero (eyebrow OR brand strip, headline, subtext, CTAs)? No tiny tagline below CTAs, no trust micro-strip in hero?
- [ ] Eyebrow count (mechanical): count `uppercase tracking` micro-labels above section headlines across all components. Count <= ceil(sectionCount / 3)? Hero counts as 1.
</hero_checks>

<layout_checks>
- [ ] Split-Header Ban: no "left big headline + right small explainer paragraph" pattern as a section header (vertical stack instead)?
- [ ] Zigzag Alternation Cap: no 3+ consecutive sections with the same image+text-split layout?
- [ ] No Duplicate CTA Intent: no two CTAs with the same intent ("Get in touch" + "Let's talk" both on page = Fail)?
- [ ] Logo wall = logo only: no industry / category labels printed below logos?
- [ ] Bento Background Diversity: at least 2-3 bento cells have real visual variation (image, gradient, pattern), not all white-on-white text cards?
- [ ] "Used by / Trusted by" logo wall lives UNDER the hero, not inside it, uses REAL SVG logos (Simple Icons / devicon) or generated SVG marks, NOT plain text wordmarks?
- [ ] Navigation on ONE line at desktop, height <= 80px?
- [ ] Section-Layout-Repetition: no two sections share the same layout family (at least 4 different families across 8 sections)?
- [ ] Bento has rhythm AND exact cell count (N items -> N cells, no empty cells in middle or end)?
- [ ] Long lists use the right UI component (not default `<ul>` with `divide-y` for > 5 items - design-directives.md content_density alternatives)?
</layout_checks>

<content_image_checks>
- [ ] Copy Self-Audit: every visible string re-read, no grammatically-broken or AI-hallucinated phrases shipped?
- [ ] Real images used (gen-tool first, then Picsum-seed, then explicit placeholder slots) - NO div-based fake screenshots, NO hand-rolled decorative SVGs, NO pure-text minimalism?
- [ ] No pills/labels overlaid on images (no `Plate . Brand`, no `Field notes - journal`)?
- [ ] No photo-credit captions as decoration (`Field study no. 12 . Ines Caetano`)?
- [ ] No version footers (`v1.4.2`, `Build 0048`) on marketing pages?
- [ ] No micro-meta-sentences under eyebrows ("Each of these is a feature we ship today...")?
- [ ] No decoration text strip at hero bottom (`BRAND. MOTION. SPATIAL.`)?
- [ ] No floating top-right sub-text in section headings?
- [ ] No scoring/progress bars with filled background tracks as comparison visuals?
- [ ] No locale / city-name / time / weather strips unless brief is genuinely globally-distributed or place-focused?
- [ ] No scroll cues (`Scroll`, `scroll`, `Scroll to explore`)?
- [ ] No version labels in hero (V0.6, BETA, INVITE-ONLY) unless the brief is a launch?
- [ ] No section-numbering eyebrows (`00 / INDEX`, `001 . Capabilities`, `06 . how it works`)?
- [ ] No decorative dots (zero by default, only for real semantic state)?
- [ ] No `border-t` + `border-b` on every row of long lists / spec tables?
- [ ] Content density sane: no 20-row data tables, no fake-precise specs without justification, <= 25-word sub-paragraphs by default?
- [ ] Quotes <= 3 lines of body, attribution clean (no em-dash)?
</content_image_checks>

<motion_checks>
- [ ] Motion motivated: every animation justified in one sentence (hierarchy / storytelling / feedback / state transition), no GSAP-for-show?
- [ ] Marquee max-one-per-page: no two horizontal marquees on the same page?
- [ ] GSAP sticky-stack / horizontal-pan implemented per motion.md canonical skeleton (`start: "top top"`, `pin: true`, correct scrub)?
- [ ] No `window.addEventListener('scroll')` - using Motion `useScroll()` / ScrollTrigger / IntersectionObserver / CSS scroll-driven animations only?
- [ ] Reduced motion wrapped for everything MOTION_INTENSITY > 3?
- [ ] Motion claimed = motion shown: if MOTION_INTENSITY > 4, page actually animates, not just claimed?
</motion_checks>

<build_checks>
- [ ] Dark mode tokens defined and tested in both modes?
- [ ] Mobile collapse explicit (`w-full`, `px-4`, `max-w-7xl mx-auto`) for high-variance layouts?
- [ ] Viewport stability: `min-h-[100dvh]`, never `h-screen`?
- [ ] `useEffect` animations (app stack) have strict cleanup functions?
- [ ] Empty / loading / error states provided?
- [ ] Cards omitted in favor of spacing where possible?
- [ ] Icons from an allowed library only (Phosphor / HugeIcons / Radix / Tabler), no hand-rolled SVG paths?
- [ ] Motion isolated in client-leaf components with `'use client'` at the top, memoized (app stack)? On static sites, JS isolated and minimal?
- [ ] No AI Tells from ai-tells.md (Inter as default, AI-purple, three-equal cards, Jane Doe, Acme, "Quietly in use at")?
- [ ] Core Web Vitals plausibly hit (LCP < 2.5s, INP < 200ms, CLS < 0.1)?
- [ ] One design system per project (no Material + shadcn mixed)?
</build_checks>
</process>

<enforcement>
If a single checkbox cannot be honestly ticked, the page is not done. Fix it before delivering. The em-dash box and the consistency locks are absolute: any em-dash or mid-page theme/accent/radius flip is an automatic fail regardless of how good the rest is.
</enforcement>

<success_criteria>
Every box ticked honestly. Output ships only when the full matrix passes.
</success_criteria>

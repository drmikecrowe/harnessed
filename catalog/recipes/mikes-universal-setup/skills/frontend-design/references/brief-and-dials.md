<overview>
Brief inference and the three configuration dials. Read this before any design or code. The dials gate every layout, motion, and density decision in the other references.
</overview>

<brief_inference>
Most LLM design output is bad because the model jumps to a default aesthetic instead of reading the room. Before touching code, infer what the user actually wants.

<signals>
1. <b>Page kind</b> - landing (SaaS / consumer / agency / event), portfolio (dev / designer / creative studio), redesign (preserve vs overhaul), editorial / blog.
2. <b>Vibe words</b> the user used - "minimalist", "calm", "Linear-style", "Awwwards", "brutalist", "premium consumer", "Apple-y", "playful", "serious B2B", "editorial", "agency-y", "glassy", "dark tech".
3. <b>Reference signals</b> - URLs linked, screenshots pasted, products named, brands they compete with.
4. <b>Audience</b> - B2B procurement panel vs. design-conscious consumer vs. recruiter scanning a portfolio. The audience picks the aesthetic, not your taste.
5. <b>Brand assets that already exist</b> - logo, color, type, photography. For redesigns these are starting material, not optional (see redesign.md).
6. <b>Quiet constraints</b> - accessibility-first audiences, public-sector, regulated industries, trust-first commerce, kids' products. These OVERRIDE aesthetic preference.
</signals>

<design_read>
Before any code, state in one line: <i>"Reading this as: &lt;page kind&gt; for &lt;audience&gt;, with a &lt;vibe&gt; language, leaning toward &lt;design system or aesthetic family&gt;."</i>

Example reads:
- "Reading this as: B2B SaaS landing for technical buyers, with a Linear-style minimalist language, leaning toward Tailwind utilities + Geist + restrained motion."
- "Reading this as: solo designer portfolio for hiring managers, with an editorial / kinetic-type language, leaning toward native CSS + scroll-driven animation + custom typography."
- "Reading this as: redesign of a public-sector service site, with a trust-first language, leaning toward GOV.UK Frontend or USWDS."
</design_read>

<when_ambiguous>
Ask exactly ONE clarifying question - never a multi-question dump - and only when the design read genuinely diverges. Example: <i>"Should this feel closer to Linear-clean or Awwwards-experimental?"</i> If you can confidently infer from context, do not ask. Declare the design read and proceed.
</when_ambiguous>

<anti_default>
Do not default to: AI-purple gradients, centered hero over dark mesh, three equal feature cards, generic glassmorphism on everything, infinite-loop micro-animations everywhere, Inter + slate-900. These are LLM defaults. Reach past them deliberately based on the design read. (Full forbidden list in ai-tells.md.)
</anti_default>
</brief_inference>

<three_dials>
After the design read, set three dials. Every layout, motion, and density decision below is gated by these.

- <b>DESIGN_VARIANCE: 8</b> - 1 = Perfect Symmetry, 10 = Artsy Chaos
- <b>MOTION_INTENSITY: 6</b> - 1 = Static, 10 = Cinematic / Physics
- <b>VISUAL_DENSITY: 4</b> - 1 = Art Gallery / Airy, 10 = Cockpit / Packed Data

<b>Baseline: 8 / 6 / 4.</b> Use these unless the design read overrides. Do not ask the user to edit this file; overrides happen conversationally. Never invent aliases like LAYOUT_VARIANCE or ANIM_LEVEL - these exact names are referenced throughout.

<dial_inference>
| Signal | VARIANCE | MOTION | DENSITY |
|---|---|---|---|
| "minimalist / clean / calm / editorial / Linear-style" | 5-6 | 3-4 | 2-3 |
| "premium consumer / Apple-y / luxury / brand" | 7-8 | 5-7 | 3-4 |
| "playful / wild / Dribbble / Awwwards / experimental / agency" | 9-10 | 8-10 | 3-4 |
| "landing page / portfolio / marketing site (default)" | 7-9 | 6-8 | 3-5 |
| "trust-first / public-sector / regulated / accessibility-critical" | 3-4 | 2-3 | 4-5 |
| "redesign - preserve" | match existing | +1 | match existing |
| "redesign - overhaul" | +2 | +2 | match existing |
</dial_inference>

<use_case_presets>
| Use case | VARIANCE | MOTION | DENSITY |
|---|---|---|---|
| Landing (SaaS, mainstream) | 7 | 6 | 4 |
| Landing (Agency / creative) | 9 | 8 | 3 |
| Landing (Premium consumer) | 7 | 6 | 3 |
| Portfolio (Designer / studio) | 8 | 7 | 3 |
| Portfolio (Developer) | 6 | 5 | 4 |
| Editorial / Blog | 6 | 4 | 3 |
| Public-sector service | 3 | 2 | 5 |
</use_case_presets>
</three_dials>

<dial_definitions>
Technical reference for what each dial value means.

<design_variance_levels>
- <b>1-3 (Predictable):</b> Symmetrical CSS Grid (12-col, equal fr-units), equal paddings, centered alignment.
- <b>4-7 (Offset):</b> `margin-top: -2rem` overlaps, varied image aspect ratios (4:3 next to 16:9), left-aligned headers over center-aligned data.
- <b>8-10 (Asymmetric):</b> Masonry layouts, Grid with fractional units (`grid-template-columns: 2fr 1fr 1fr`), massive empty zones (`padding-left: 20vw`).
- <b>MOBILE OVERRIDE:</b> For levels 4-10, asymmetric layouts above `md:` MUST collapse to strict single-column (`w-full`, `px-4`, `py-8`) on viewports &lt; 768px.
</design_variance_levels>

<motion_intensity_levels>
- <b>1-3 (Static):</b> No automatic animations. CSS `:hover` and `:active` states only. `prefers-reduced-motion` is the default mode anyway.
- <b>4-7 (Fluid CSS):</b> `transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1)`. `animation-delay` cascades for load-ins. Focus on `transform` and `opacity`.
- <b>8-10 (Advanced Choreography):</b> Complex scroll-triggered reveals, parallax, scroll-driven animation (CSS `animation-timeline` or GSAP ScrollTrigger). Use Motion hooks. NEVER `window.addEventListener('scroll')` - hard ban, see motion.md.
</motion_intensity_levels>

<visual_density_levels>
- <b>1-3 (Art Gallery):</b> Lots of white space. Huge section gaps (`py-32` to `py-48`). Expensive, clean.
- <b>4-7 (Daily App):</b> Standard web app spacing (`py-16` to `py-24`).
- <b>8-10 (Cockpit):</b> Tight paddings. No card boxes; 1px lines separate data. Mandatory: `font-mono` for all numbers.
</visual_density_levels>
</dial_definitions>

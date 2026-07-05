---
name: frontend-design
description: Distinctive, intentional visual design for landing pages, portfolios, editorial sites, and redesigns that do not read as templated defaults. Covers brief inference, design direction, typography and color, the static-site vs app/framework build paths, and a strict pre-flight check. Use when building or reshaping any UI surface.
---

<essential_principles>
These apply to EVERY task. They cannot be skipped. Detail lives in references/; this section is the always-loaded core.

<stance>
Approach this as the design lead at a small studio known for giving every client a visual identity that could not be mistaken for anyone else's. The client has already rejected templated proposals and is paying for a distinctive point of view: make deliberate, opinionated choices about palette, typography, and layout that are specific to this brief, and take one real aesthetic risk you can justify.

Ground it in the subject: name one concrete subject, its audience, and the page's single job. The subject's own world - its materials, instruments, artifacts, and vernacular - is where distinctive choices come from. Build with the brief's real content throughout.
</stance>

<brief_inference_first>
Before any code, infer what the user actually wants and state a one-line <b>design read</b>: <i>"Reading this as: &lt;page kind&gt; for &lt;audience&gt;, with a &lt;vibe&gt; language, leaning toward &lt;system or aesthetic&gt;."</i> Most LLM design output is bad because the model jumps to a default aesthetic instead of reading the room. The audience picks the aesthetic, not your taste. Quiet constraints (accessibility-first, public-sector, regulated, kids' products) OVERRIDE aesthetic preference. See references/brief-and-dials.md.
</brief_inference_first>

<three_dials>
After the design read, set three dials. Every layout, motion, and density decision below is gated by them. <b>Baseline: DESIGN_VARIANCE 8 / MOTION_INTENSITY 6 / VISUAL_DENSITY 4</b> (1-10 each); infer overrides from the brief, do not ask the user to edit values. Never invent aliases like LAYOUT_VARIANCE or ANIM_LEVEL. See references/brief-and-dials.md for the inference tables and dial definitions.
</three_dials>

<anti_default_discipline>
Do not default to AI-template looks: (1) warm cream background near #F4F1EA with high-contrast serif display and terracotta accent; (2) near-black with a single bright acid-green or vermilion accent; (3) broadsheet hairline rules, zero radius, dense newspaper columns. Also avoid AI-purple gradients, centered hero over dark mesh, three equal feature cards, glassmorphism on everything, infinite micro-loops everywhere, and Inter + slate-900. These are defaults, not choices. Where the brief pins a direction, follow it exactly - the brief's words always win. Where it leaves an axis free, don't spend that freedom on a default. See references/ai-tells.md for the full forbidden list.
</anti_default_discipline>

<signature_and_restraint>
Spend your boldness in one place. Let the signature element be the one memorable thing; keep everything around it quiet and disciplined; cut any decoration that does not serve the brief. Not taking a risk can be a risk itself. Build to a quality floor without announcing it: responsive to mobile, visible keyboard focus, reduced motion respected. Consider Chanel's advice: before leaving the house, take a look in the mirror and remove one accessory.
</signature_and_restraint>

<two_pass_planning>
Work in two passes. First brainstorm a compact token system (Color: 4-6 named hex values; Type: a characterful display face + a complementary body face + a utility face if needed; Layout: a concept in prose + ASCII wireframes; Signature: the single unique element). Then critique that plan against defaults before writing code - if any part reads like the generic default for any similar page, revise it and say why. Only then write code, deriving every color and type decision from the revised plan. Do this planning in your thinking; show the user only when you have higher confidence it will delight them.
</two_pass_planning>

<real_images>
Landing pages and portfolios are visual products. Generate section-specific assets with the image tool when available; otherwise use real photography (`https://picsum.photos/seed/{descriptive-seed}/{w}/{h}` or brand URLs). NEVER div-based fake screenshots, NEVER hand-rolled decorative SVGs as default, NEVER pure-text "minimalism." Even restrained sites need 2-3 real images. Real SVG logos (Simple Icons / devicon) for social proof, never plain text wordmarks. See references/design-directives.md images_and_assets.
</real_images>

<hard_locks>
Non-negotiable, enforced by the pre-flight check:
- <b>Em-dash ban:</b> ZERO em-dashes (`-`/`-`) anywhere visible. Headlines, eyebrows, pills, body, quotes, attribution, captions, buttons, alt text. Use periods, commas, parentheses, colons, or regular hyphens. Binary rule. (references/ai-tells.md em_dash_ban)
- <b>Theme lock:</b> ONE theme (light, dark, or auto) per page. No section flips mid-page. (references/design-directives.md theme_lock)
- <b>Color consistency lock:</b> one accent color used identically across the whole page. (references/design-directives.md color)
- <b>Shape consistency lock:</b> one corner-radius system applied everywhere. (references/design-directives.md materiality_and_cards)
</hard_locks>

<writing_voice>
Words make a design easier to understand and use; they are design material, not decoration. Write from the end user's side: name things by what people control, never by how the system is built. Active voice as default; an action keeps the same name through the whole flow ("Publish" -> "Published"). Treat failure and emptiness as moments for direction, not mood - errors don't apologize and are never vague. One copy register per page. See references/design-directives.md writing_voice.
</writing_voice>

<pre_flight_mandatory>
Before delivering any code, run workflows/pre-flight-check.md. It is the last filter and is not optional. If any box cannot be honestly ticked, the page is not done.
</pre_flight_mandatory>
</essential_principles>

<intake>
What do you need? (Pick one. If you can confidently infer from context, declare it and proceed - do not ask.)

1. <b>Build a static site</b> - GitHub Pages, S3/CloudFront, Netlify/Vercel/Cloudflare Pages, plain HTML/CSS, or an SSG (Eleventy, Astro, Hugo, Jekyll). <i>Do NOT default to React/Next.</i>
2. <b>Build an app/framework site</b> - React/Next/Vue + Tailwind + component library, with hydration/client state.
3. <b>Redesign an existing site</b> - audit first, then evolve (preserve) or overhaul.
4. <b>Design direction only</b> - a design plan / token system, no code yet.
</intake>

<routing>
| Response | Workflow |
|----------|----------|
| 1, "static", "github pages", "s3", "cloudfront", "netlify", "vercel", "ssg", "eleventy"/"11ty", "astro", "hugo", "jekyll", "plain html" | `workflows/build-site.md` (static branch) |
| 2, "app", "react", "next", "next.js", "vue", "framework" | `workflows/build-site.md` (app branch) |
| 3, "redesign", "modernise", "modernize", "rebrand", "overhaul", "refresh" | `workflows/redesign-site.md` |
| 4, "plan", "direction", "tokens", "design only", "ideas" | Steps 1-6 of `workflows/build-site.md` (brainstorm + critique; present the token system, no code) |
| other | Clarify with ONE question, then select |

**After reading the workflow, follow it exactly.** Both build branches load the stack-agnostic visual references (design-directives, ai-tells, performance-a11y-darkmode) plus their branch-specific stack reference. Every path ends at workflows/pre-flight-check.md.
</routing>

<reference_index>
All domain knowledge in `references/`:

<b>Inference & config:</b> brief-and-dials.md (design read + three dials + dial definitions)
<b>Foundations:</b> design-systems.md (official DS map + install commands + canonical sources + Liquid Glass), app-stack.md (React/Next/Tailwind/Motion defaults), static-sites.md (GitHub Pages / S3+CloudFront / SSGs / plain HTML)
<b>Visual rules:</b> design-directives.md (typography, color, layout, hero, materiality, interactive states, forms, content density, quotes, theme lock, writing voice)
<b>Anti-slop:</b> ai-tells.md (forbidden patterns + production-test tells + em-dash ban)
<b>Motion:</b> motion.md (context-aware patterns + GSAP/Motion skeletons)
<b>Quality floor:</b> performance-a11y-darkmode.md (a11y, reduced motion, dark mode, Core Web Vitals)
<b>Patterns:</b> reference-vocabulary.md (hero/nav/grid/card/scroll/typography/micro-interaction names)
<b>Redesign:</b> redesign.md (mode detection, audit, preservation, modernisation levers)
</reference_index>

<workflows_index>
| Workflow | Purpose |
|----------|---------|
| build-site.md | Greenfield build; branches on static site vs app/framework; ends at pre-flight check |
| redesign-site.md | Audit-first redesign (preserve or overhaul); ends at pre-flight check |
| pre-flight-check.md | Final enforcement matrix; ships only when every box passes |
</workflows_index>

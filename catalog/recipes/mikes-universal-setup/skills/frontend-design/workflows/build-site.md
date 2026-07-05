<overview>
Greenfield build workflow. Builds a landing page, portfolio, editorial site, or marketing surface that does not read as templated. Branches on static site vs app/framework build. For redesigns, use redesign-site.md instead.
</overview>

<out_of_scope_gate>
This workflow is NOT for: dashboards / dense product UI / admin panels (use Fluent, Carbon, Atlassian, or Polaris from design-systems.md); data tables (TanStack Table / AG Grid); multi-step forms / wizards; code editors (Monaco / CodeMirror); native mobile (Apple HIG / Material); realtime collab UIs. If the brief is one of these, say so explicitly, point to the right tool, and only apply this workflow's marketing/landing/about surfaces where they apply.
</out_of_scope_gate>

<required_reading>
Read these NOW before writing code:
1. references/brief-and-dials.md (design read + dials - always)
2. references/design-directives.md (typography, color, layout, hero, copy - always)
3. references/ai-tells.md (forbidden patterns + em-dash ban - always)
4. references/performance-a11y-darkmode.md (a11y, dark mode, vitals - always)
5. references/static-sites.md OR references/app-stack.md (the branch below picks one)
6. references/design-systems.md (if the brief reads as an official system, or to pick an aesthetic honestly)
7. references/motion.md (only if MOTION_INTENSITY > 3)
8. references/reference-vocabulary.md (pattern names, when composing hero/sections)
</required_reading>

<process>
<step name="1. Read the room">
Infer the brief per brief-and-dials.md. Before any code, state the design read in one line: <i>"Reading this as: &lt;page kind&gt; for &lt;audience&gt;, with a &lt;vibe&gt; language, leaning toward &lt;system or aesthetic&gt;."</i> Set the three dials (DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY) from the brief, not the baseline. Ask ONE clarifying question only if the read genuinely diverges.
</step>

<step name="2. Pick the stack (branch)">
Determine whether this is a <b>static site</b> or an <b>app/framework build</b>:
- <b>Static</b> (GitHub Pages, S3/CloudFront, Netlify/Vercel/Cloudflare Pages, plain HTML/CSS, or an SSG like Eleventy / Astro / Hugo / Jekyll): read references/static-sites.md. Do NOT default to React/Next. Reach for the lightest tool that ships the page.
- <b>App/framework</b> (React/Next/Vue + Tailwind + component library, hydration, client state): read references/app-stack.md.

This branch only swaps the IMPLEMENTATION layer. The visual rules (design-directives, ai-tells) apply identically to both.
</step>

<step name="3. Ground it in the subject">
Name one concrete subject, its audience, and the page's single job, and state the choice. Use any known preferences, prior designs, and brand assets as hints. The subject's own world - materials, instruments, artifacts, vernacular - is where distinctive choices come from. Build with the brief's real content throughout.
</step>

<step name="4. Pick the foundation">
Per design-systems.md: if the brief reads as an official design system (Fluent, Material, Carbon, GOV.UK, USWDS, Primer, etc.), install and use the OFFICIAL package - do not hand-roll its CSS. Otherwise build an aesthetic honestly from native CSS (+ Tailwind if your build supports it) + a maintained component library, and label borrowed inspiration vs. official material in comments. One system per project. For static sites, prefer a CSS-only distribution over forcing a React dependency.
</step>

<step name="5. Brainstorm the design plan (pass 1)">
Create a compact token system: <b>Color</b> (4-6 named hex values), <b>Type</b> (a characterful display face used with restraint + a complementary body face + a utility face for captions/data if needed), <b>Layout</b> (a layout concept in one-sentence prose + ASCII wireframes to ideate and compare), <b>Signature</b> (the single unique element this page will be remembered by, that embodies the brief appropriately).
</step>

<step name="6. Critique the plan vs defaults (pass 2)">
Before writing code, review the plan against the brief. If any part reads like the generic default you would produce for any similar page rather than a choice made for THIS brief - revise it, say what you changed and why. Check against the three AI-look clusters (warm cream + serif + terracotta; near-black + acid accent; broadsheet hairline columns) and the banned defaults in ai-tells.md. Spend your boldness in one signature element; keep everything around it disciplined. Only after confirming the plan's relative uniqueness do you write code, deriving every color and type decision from the revised plan.
</step>

<step name="7. Build">
Write the code following the revised plan. Apply design-directives.md (typography discipline, color locks, layout hard rules, hero rules, content density, theme lock, writing voice). Honor every mandatory rule and ban in ai-tells.md. Be careful with CSS selector specificities - type-based (`.section`) and element-based (`.cta`) selectors cancel each other out, especially for section padding/margins.
</step>

<step name="8. Add real images">
Generate section-specific assets with the image tool (hero photography, product shots, textures) at the right aspect ratios. If no gen tool, use `https://picsum.photos/seed/{descriptive-seed}/{w}/{h}` or actual brand URLs. Never div-based fake screenshots, never hand-rolled decorative SVGs, never pure-text "minimalism." Even restrained sites need 2-3 real images. For social proof, use real SVG logos (Simple Icons / devicon) or invented SVG monogram marks - never plain text wordmarks. Set explicit width/height to prevent CLS; preload the hero.
</step>

<step name="9. Add motion only if motivated">
If MOTION_INTENSITY > 3, add motion that actually serves the subject (hierarchy / storytelling / feedback / state transition - never "it looked cool"). Use the patterns/skeletons in motion.md. "Motion claimed = motion shown": if you claim a high dial, the page must actually move; if you cannot ship working motion, drop the dial to 3 and ship clean static. Reduced motion is mandatory. On static sites use CSS scroll-driven animations / IntersectionObserver / standalone GSAP.
</step>

<step name="10. Accessibility, dark mode, performance">
Per performance-a11y-darkmode.md: animate only transform/opacity; honor prefers-reduced-motion; design for both light and dark from the start (or auto via prefers-color-scheme), test both; WCAG AA contrast (AAA for body); hit LCP < 2.5s, INP < 200ms, CLS < 0.1. For static sites, protect the natural perf advantage - ship near-zero JS.
</step>

<step name="11. Run the pre-flight check">
Run workflows/pre-flight-check.md against the finished page. This is not optional. Fix every failing box before delivering.
</step>
</process>

<success_criteria>
- Design read stated as a one-liner; dials set from the brief, not the baseline
- Stack chosen correctly: static site did NOT default to React/Next; app build used the app stack
- One design system (official package or honestly-labeled aesthetic), never mixed
- Design plan critiqued against defaults before coding; one signature element carries distinctiveness
- Every mandatory directive honored; every banned tell absent (ZERO em-dashes)
- Real images throughout (gen tool or picsum-seed); no div-fake-screenshots, no plain-text wordmarks
- Motion (if any) is motivated and actually works; reduced motion honored
- Both light/dark designed and tested; WCAG AA; vitals on target
- Pre-flight check passes every box
</success_criteria>

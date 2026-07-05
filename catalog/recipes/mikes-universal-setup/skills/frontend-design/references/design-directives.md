<overview>
The design engineering directives: typography, color, layout, hero, materiality, interactive states, content, copy voice, and theme lock. These rules are STACK-AGNOSTIC - they apply identically to static sites and app/framework builds. Tailwind class examples are illustrative; translate to plain CSS or your styling system when not using Tailwind. Bias-correction: LLMs default to cliches; override proactively. Rules marked mandatory or banned are non-negotiable.
</overview>

<typography>
<defaults>
- <b>Display / Headlines:</b> `text-4xl md:text-6xl tracking-tighter leading-none`.
- <b>Body / Paragraphs:</b> `text-base text-gray-600 leading-relaxed max-w-[65ch]`.
</defaults>

<sans_choice>
<b>Discouraged as default:</b> `Inter`. Pick `Geist`, `Outfit`, `Cabinet Grotesk`, `Satoshi`, or a brand-appropriate face first. Override: Inter is acceptable when the user explicitly asks for a neutral / standard / Linear-style feel, or for a public-sector / accessibility-first site.

<b>Pairings to know:</b> Geist + Geist Mono, Satoshi + JetBrains Mono, Cabinet Grotesk + Inter Tight, GT America + IBM Plex Mono.
</sans_choice>

<serif_discipline>
Serif is <b>very discouraged as the default font for any project.</b> "It feels creative / premium / editorial" is NOT a reason to reach for serif. The "creative brief = serif" reflex is the single most-tested AI tell in production rounds.

Serif is acceptable ONLY when ONE is explicitly true:
- The brand brief literally names a serif font, OR
- The aesthetic family is genuinely editorial / luxury / publication / manuscript / heritage / vintage AND you can articulate why this specific serif fits this specific brand.

For everything else (creative agency, design studio, modern brand, premium consumer, portfolio, lifestyle), default sans-serif display (Geist Display, ABC Diatype, Söhne Breit, Cabinet Grotesk Display, Migra Sans, GT Walsheim, Inter Display, PP Neue Montreal). Sans display is the default the way black is the default in fashion.

<b>BANNED as defaults:</b> `Fraunces` and `Instrument Serif` (the two LLM-favorite display serifs).

If a serif is justified (rare), rotate from this pool and do NOT reuse the same serif across consecutive projects: PP Editorial New, GT Sectra Display, Cardinal Grotesque, Reckless Neue, Tiempos Headline, Recoleta, Cormorant Garamond, Playfair Display, EB Garamond, IvyPresto, Migra, Editorial Old, Saol Display, Söhne Breit Kursiv, Domaine Display, Canela, Schnyder, Tobias, NB Architekt, ITC Galliard.
</serif_discipline>

<emphasis_rule>
When emphasizing a word within a headline (the kinetic "and `spatial` design" move), use italic or bold of the SAME font. Do NOT inject a random serif word into a sans headline (or vice versa) for visual interest. Mixed-family emphasis is amateur.
</emphasis_rule>

<italic_descender_clearance>
When italic is used in display type and the word contains a descender (`y g j p q`), `leading-[1]` or `leading-none` will clip the descender. Use `leading-[1.1]` minimum and add `pb-1` or `mb-1` reserve on the wrapping element. Audit every italic word in display headlines before shipping.
</italic_descender_clearance>
</typography>

<color>
- Max 1 accent color. Saturation &lt; 80% by default.
- <b>THE LILA RULE:</b> the "AI Purple / Blue glow" aesthetic is discouraged as default. No automatic purple button glows, no random neon gradients. Use neutral bases (Zinc / Slate / Stone) with high-contrast singular accents (Emerald, Electric Blue, Deep Rose, Burnt Orange). Override: if the brand explicitly asks for purple / violet / lila, embrace it with intent (consistent palette, harmonised neutrals, restrained gradients - not generic AI gradient slop).
- <b>One palette per project.</b> Do not fluctuate between warm and cool grays within the same project.
- <b>COLOR CONSISTENCY LOCK (mandatory):</b> once an accent is chosen for a page, it is used on the WHOLE page. A warm-grey site does not suddenly get a blue CTA in section 7. A rose-accented site does not get a teal badge in the footer. Pick one accent, lock it, audit every component before shipping.

<premium_consumer_palette_ban>
For premium-consumer briefs (cookware, wellness, artisan, luxury, heritage craft, DTC home goods) the LLM default is warm beige/cream + brass/clay/oxblood/ochre + espresso/ink dark text. This palette is BANNED as the default reach. Concretely banned hex families:
- Backgrounds: `#f5f1ea`, `#f7f5f1`, `#fbf8f1`, `#efeae0`, `#ece6db`, `#faf7f1`, `#e8dfcb` (warm paper / cream / chalk / bone)
- Accents: `#b08947`, `#b6553a`, `#9a2436`, `#9c6e2a`, `#bc7c3a`, `#7d5621` (brass / clay / oxblood / ochre)
- Text: `#1a1714`, `#1a1814`, `#1b1814` (espresso / warm near-black)

Every premium-consumer site shipped with this palette is invisible. <b>Default alternatives (rotate, do not reuse):</b>
- Cold Luxury: silver-grey + chrome + smoke (Tesla, Apple Watch Hermes-without-the-leather)
- Forest: deep green + bone + amber accent (Filson, Patagonia premium)
- Black and Tan: true off-black + warm tan, sharp contrast, no beige
- Cobalt + Cream: saturated blue against a single neutral, no brass
- Terracotta + Slate: warm rust against cool grey, no brass
- Olive + Brick + Paper: muted olive plus brick-red accent
- Pure monochrome + single saturated pop: off-white + off-black + one bright accent (electric blue, emerald, hot pink)

<b>Palette-rotation rule:</b> if the previous premium-consumer project used beige+brass, this one MUST use a different family. Do not ship the same warm-craft palette twice in a row. Override: beige+brass+espresso is acceptable ONLY when the brand brief explicitly names those colors, or the brand identity is genuinely vintage / artisan / warm-craft AND you can articulate why this specific palette fits.
</premium_consumer_palette_ban>
</color>

<layout_diversification>
<b>ANTI-CENTER BIAS:</b> centered Hero / H1 sections are avoided when `DESIGN_VARIANCE > 4`. Force "Split Screen" (50/50), "Left-aligned content / right-aligned asset", "Asymmetric white-space", or scroll-pinned structures. Override: centered hero is OK for editorial / manifesto / launch-announcement briefs where the message itself is the design.
</layout_diversification>

<materiality_and_cards>
- Use cards ONLY when elevation communicates real hierarchy. Otherwise group with `border-t`, `divide-y`, or negative space.
- When a shadow is used, tint it to the background hue. No pure-black drop shadows on light backgrounds.
- For `VISUAL_DENSITY > 7`: generic card containers are banned. Data metrics breathe in plain layout.
- <b>SHAPE CONSISTENCY LOCK (mandatory):</b> pick ONE corner-radius scale for the page and stick to it. Options: all-sharp (radius 0), all-soft (radius 12-16px), all-pill (full radius for interactive). Mixed systems allowed only with a documented rule followed everywhere (e.g. "buttons full-pill, cards 16px, inputs 8px"). Round buttons in a square layout, or square cards on a pill-button page, is broken design.
</materiality_and_cards>

<interactive_states>
LLMs default to "static successful state only." Always implement full cycles:
- <b>Loading:</b> skeletal loaders matching the final layout's shape. Avoid generic circular spinners.
- <b>Empty States:</b> beautifully composed; indicate how to populate.
- <b>Error States:</b> clear, inline (forms), or contextual (toasts only for transient).
- <b>Tactile Feedback:</b> on `:active`, use `-translate-y-[1px]` or `scale-[0.98]` to simulate a physical push.
- <b>BUTTON CONTRAST CHECK (mandatory, a11y):</b> verify button text is readable against the button background. White button + white text, `bg-white` CTA with `text-white` label, transparent button against the page background with no border -> all banned. Audit every CTA: WCAG AA min (4.5:1 body, 3:1 large text 18px+). Same rule for ghost buttons over photos (use a backdrop, scrim, or stroke).
- <b>CTA BUTTON WRAP BAN (mandatory):</b> button text MUST fit on one line at desktop. If a label wraps to 2-3 lines, the button is broken. Fix by shortening the label (3 words max for primary CTAs, ideally 1-2) OR widening the button. Do not constrain `max-width` on CTAs. Wrapped CTAs at desktop = Pre-Flight Fail.
- <b>NO DUPLICATE CTA INTENT (mandatory):</b> two CTAs with the same intent on one page = Pre-Flight Fail. "Get in touch" + "Contact us" + "Let's talk" + "Start a project" + "Reach out" = all "contact" intent -> pick ONE label everywhere (nav, hero, footer). Same for "Try free"/"Get started"/"Sign up free" (signup) and "View work"/"See selected work"/"Browse projects" (portfolio). One label per intent.
</interactive_states>

<forms>
- Label ABOVE input. Helper text optional but present in markup. Error text BELOW input. Standard `gap-2` for input blocks.
- No placeholder-as-label. Ever.
- <b>FORM CONTRAST CHECK (mandatory, a11y):</b> form inputs, placeholder text, focus rings, helper text, and error text all pass WCAG AA contrast against the section background. Light placeholders on near-white forms, white form on white page section, labels grayer than 4.5:1 -> all banned. Audit every form before shipping.
</forms>

<layout_hard_rules>
Failing any of these is shipping broken work.

<hero_rules>
- <b>Hero MUST fit the initial viewport.</b> Headline max 2 lines desktop, subtext max 20 words AND max 3-4 lines, CTAs visible without scroll. If copy is too long: reduce font scale OR cut copy. Never let the hero overflow and force scroll to find the CTA.
- <b>Hero font-scale discipline.</b> Plan font size and image size together. If the asset is large and the headline > 6 words, do not start at `text-7xl/8xl`. Default `text-4xl md:text-5xl lg:text-6xl`; `text-6xl md:text-7xl` only when headline is 3-5 words. A 4-line hero headline is always a font-size error, never a copy-length error.
- <b>HERO TOP PADDING CAP (mandatory):</b> hero top padding max `pt-24` (~6rem) desktop. More means the hero floats halfway down and reads as a layout bug. Need breathing room? Increase font scale or asset size, not top padding.
- <b>HERO STACK DISCIPLINE (max 4 text elements):</b> the hero is a single moment, not a feature list. Allowed, max 4 total: (1) eyebrow OR brand strip OR neither (pick zero or one); (2) headline (max 2 lines); (3) subtext (max 20 words, max 4 lines); (4) CTAs (1 primary + max 1 secondary). BANNED in the hero: tiny tagline below CTAs ("Works with GitHub, GitLab..."), trust micro-strip, pricing teaser, feature bullet list, social-proof avatar row - all move to sections directly below. If you have an eyebrow AND a tagline below CTAs, drop the tagline. One small text element per hero, max.
- <b>"Used by" / "Trusted by" logo wall belongs UNDER the hero, never inside it.</b> The hero is for value prop + primary CTA. The logo wall is a separate section directly below. Do not stuff trust logos into the same flex row as hero copy.
</hero_rules>

<nav_rules>
- Navigation MUST render on a single line on desktop. If items don't fit at `lg` (1024px), condense labels, drop secondary items, or move to a hamburger. A two-line nav at desktop is broken.
- Navigation height cap: 80px max desktop, default 64-72px. No huge "agency" nav bars eating 15% of the viewport.
</nav_rules>

<grid_rules>
- <b>Bento grids MUST have rhythm, not one-sided repetition.</b> Do not stack 6 left-image / right-text rows. Vary composition: alternate full-width feature rows, asymmetric tile sizes, vertical breaks.
- <b>BENTO CELL COUNT RULE (mandatory):</b> a bento grid has EXACTLY as many cells as you have content for. 3 items -> 3 cells (1+2, 2+1, asymmetric trio). 5 items -> 5 cells. An empty cell in the middle or end means you planned wrong - re-shape the grid, do not paste a blank tile.
- <b>Bento Background Diversity (mandatory):</b> not 6 white-on-white text cards. At least 2-3 cells need real visual variation: a real image, a brand-appropriate gradient (not AI-purple), a pattern, a tinted background.
</grid_rules>

<repetition_rules>
- <b>Section-Layout-Repetition Ban.</b> Once you use a layout family for a section (3-column-image-cards, full-width-quote, split-text-image), it appears at most ONCE on the page. A landing page with 8 sections must use at least 4 different layout families.
- <b>ZIGZAG ALTERNATION CAP (mandatory).</b> Alternating "left-image + right-text" then reverse = banal. Max 2 sections in a row with image+text-split. The 3rd consecutive is a Pre-Flight Fail. Break the pattern with a full-width section, vertical-stack, bento grid, marquee, or a different family.
- <b>EYEBROW RESTRAINT (mandatory, #1 violated rule in production tests).</b> An "eyebrow" is the small uppercase wide-tracking label above a section headline (e.g. `FOUR COLORWAYS`, `SELECTED WORK`), CSS signature ~`text-[11px] uppercase tracking-[0.18em]`. Every AI-built site puts one above EVERY header. Hard rule: maximum 1 eyebrow per 3 sections (hero counts as 1). If section A has one, the next 2 cannot. Pre-Flight is mechanical: count `uppercase tracking` instances; if count > ceil(sectionCount / 3), it fails. Instead of an eyebrow: drop it. The headline alone is enough; the section's location already categorizes it.
- <b>SPLIT-HEADER BAN (mandatory).</b> "left big headline + right small explainer paragraph" (col-span-7/8 + col-span-4/5) as a section header is banned as default. Stack headline over body vertically (max-width 65ch). Reach for the split only when the right column carries a real visual/interactive element, not filler text.
</repetition_rules>

<mobile_rule>
Mobile collapse must be explicit per section. For every multi-column layout, declare the `&lt; 768px` fallback in the same component. No "Tailwind handles it" assumptions.
</mobile_rule>
</layout_hard_rules>

<images_and_assets>
Landing pages and portfolios are VISUAL products. Text-only pages with fake-screenshot divs are slop.

<priority_order>
1. <b>Image-generation tool first.</b> If ANY image-gen tool is available you MUST use it for section-specific assets (hero photography, product shots, textures, mood). Generate at the right aspect ratio. Do not skip because hand-rolled CSS feels faster.
2. <b>Real web images second.</b> `https://picsum.photos/seed/{descriptive-seed}/{w}/{h}` for placeholder photography (seed describes the section, e.g. `marrow-cookware-kitchen`); actual stock/brand URLs the brief provides; open-license sources (Unsplash, Pexels) if explicitly allowed.
3. <b>Last resort: tell the user.</b> If neither is possible, do NOT fill the page with hand-rolled SVG or div-based fake screenshots. Leave clearly-labeled placeholder slots (`<!-- TODO: hero product photo, 1600x1200 -->`) and say at the end: "This page needs real images at: [list]. Please generate or provide them."
</priority_order>

Even minimalist sites need real images. A pure-text page is not minimalism; it is incomplete work. Generate B&W minimalist photography if the brief is restrained; do not skip images entirely because the dial is low.

<logos>
Real company logos for social proof - do NOT default to plain text wordmarks. Use real SVG logos:
- <b>Simple Icons</b> (`https://cdn.simpleicons.org/{slug}/ffffff`, or `simple-icons` npm) covers most known brands.
- <b>devicon</b> for tech-stack logos.
- <b>Invented brand name? Then invent an SVG mark too.</b> A simple monogram (one letter in a circle, two-letter ligature, abstract glyph) as inline `<svg>` matching the page style. Plain text wordmarks for invented names look generic.
- Ensure logos render in both light and dark mode.
- <b>LOGO-ONLY rule (mandatory):</b> logo wall = logos and nothing else. Do NOT print industry/category labels below each logo (no `Vercel` + `hosting`). The logo is the credibility. Optional: brand name as alt-text for screen readers, optional link.
</logos>

<forbidden_assets>
- <b>Div-based fake screenshots are banned.</b> A hand-built product preview from styled divs (fake task list, fake terminal, fake dashboard) is the #1 LLM-design Tell. Use a real screenshot URL, generate one, use a real component preview, or skip.
- <b>Hand-rolled decorative SVGs strongly discouraged</b> as default (acceptable only when the brief explicitly asks, or it's a single simple geometric mark you're confident in). SVG icons from libraries: fine.
- <b>Hero needs a real visual.</b> Text + gradient blob is not a hero - it's a placeholder.
</forbidden_assets>
</images_and_assets>

<content_density>
Landing pages live on the first impression. Cut ruthlessly.

- <b>Default content shape per section:</b> short headline (<= 8 words) + short sub-paragraph (<= 25 words) + one visual asset OR one CTA. Anything more must be justified by the section's job.
- <b>No data-dump sections.</b> A 20-row publication table, 30-row award list, giant pricing matrix on a marketing page = wrong layout. Use top 3-5 highlights + "View full list" link; marquee/carousel for breadth; a different page if the data is the product.
- <b>Long lists need a different UI component, not a longer list.</b> For > 5 items reach for: 2-column grouped split; card grid (image + label); tabs/accordion if categorisable; horizontal scroll-snap pills; carousel (testimonials, logos); marquee (lots-of-things-that-don't-need-individual-attention). A spec sheet with 10 rows + a hairline under every row is the WORST default.
- <b>Spec sheets specifically (the AI-default for cookware / hardware / apparel / artisan goods).</b> A long product spec table with `border-b` on every row is banned. Alternatives: 2-col card grid (spec name + large value + one-line "why it matters"); scroll-snap horizontal pills; grouped chunks (cluster specs into "Materials / Cooking / Warranty" with ONE soft divider + a cluster heading); featured-vs-rest (3-4 hero specs as large tiles, rest under "View full specifications").
- <b>COPY SELF-AUDIT (mandatory before ship):</b> re-read every visible string. Flag and rewrite any that are: grammatically broken; have unclear referents; sound like AI hallucination (cute-but-wrong wordplay, forced metaphors, "elegant nothing" phrases); read like an LLM trying to sound thoughtful (passive-aggressive humility, fake-craftsman labels, mock-poetic micro-meta). If unsure a string makes sense, replace it with a plain functional sentence. AI-generated cute copy is worse than boring copy.
- <b>Fake-precise numbers are flagged.</b> Numbers like `92%`, `4.1x`, `48k`, `5.8 mm` either come from real data (fine), are explicitly labeled mock (fine), or are AI-invented spec aesthetics (banned). Don't fake engineering precision the brand doesn't claim.
- <b>One copy register per page.</b> Don't mix technical mono, editorial prose, and marketing punch unless the brand voice explicitly calls for it.
</content_density>

<quotes>
- <b>Max 3 lines</b> of quote body. Never 6. Longer original quote -> cut it. A landing-page quote is a snippet, not the full review. (Small footer-style testimonials can stretch slightly.)
- <b>No em-dashes inside the quote text</b> (long pauses, kinetic em-dashes, em-dash-bullets). See ai-tells.md - em-dash is completely banned.
- <b>Attribution:</b> name + role + (optionally) company. Never name only ("- Sarah").
- <b>Quote marks:</b> real typographic quotes (" ") or none at all. Not straight ASCII (").
</quotes>

<theme_lock>
The page has ONE theme. Sections do not invert.

- If dark mode, ALL sections are dark. No light-mode-warm-paper section sandwiched between dark sections (or vice versa). The user must not feel they walked into a different website mid-scroll.
- Exception: if the brief explicitly calls for a "Color Block Story" or "Theme Switch on Scroll" device as a deliberate composition (one full theme switch with a strong transition, not random alternation), allowed once per page.
- Default: pick light, dark, or auto (`prefers-color-scheme`) at the page level and lock it. Section-level background tints within the same family are fine (`bg-zinc-950` next to `bg-zinc-900`); flipping to `bg-amber-50` mid-`bg-zinc-950` page is broken.
- With a themed design system (Radix Themes, shadcn/ui `<Theme>`), set the theme ONCE in the page root. Do not let sections override.
</theme_lock>

<writing_voice>
Words appear in a design to make it easier to understand, and therefore easier to use. They are design material, not decoration. Bring the same intentionality to copy that you bring to spacing and color.

- <b>Write from the end user's side of the screen.</b> Name things by what people control and recognize, never by how the system is built. A person manages notifications, not webhook config. Describe what something does in plain terms rather than selling it. Specific is always better than clever.
- <b>Active voice as default.</b> A control says exactly what happens when used: "Save changes," not "Submit." An action keeps the same name through the whole flow - the button that says "Publish" produces a toast that says "Published." Cohesion and consistency are how people learn their way around.
- <b>Treat failure and emptiness as moments for direction, not mood.</b> Explain what went wrong and how to fix it, in the interface's voice. Errors don't apologize, and they are never vague. An empty screen is an invitation to act.
- <b>Keep the register conversational and tuned:</b> plain verbs, sentence case, no filler, tone matched to brand and audience. Let each element do exactly one job. A label labels, an example demonstrates, and nothing quietly does double duty.
</writing_voice>

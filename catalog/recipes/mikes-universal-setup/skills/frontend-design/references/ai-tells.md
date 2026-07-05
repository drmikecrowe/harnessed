<overview>
AI Tells - the forbidden patterns that mark output as templated LLM design. Avoid these unless the brief explicitly asks for one. Section 9.F (production-test tells) and 9.G (em-dash ban) are hard bans enforced by the pre-flight check.
</overview>

<visual_css>
- NO neon / outer glows by default. Use inner borders or subtle tinted shadows.
- NO pure black (`#000000`). Off-black, zinc-950, or charcoal.
- NO oversaturated accents. Desaturate to blend with neutrals.
- NO excessive gradient text for large headers.
- NO custom mouse cursors. Outdated, accessibility-hostile, perf-hostile.
</visual_css>

<typography_tells>
- AVOID Inter as default (see design-directives.md typography). Override path exists.
- NO oversized H1s that just scream. Control hierarchy with weight + color, not raw scale.
- Serif constraints: serif for editorial / luxury / publication. Not for dashboards.
</typography_tells>

<layout_spacing>
- NO mathematically perfect padding and margins with floating elements in awkward gaps.
- NO 3-column equal feature cards. The generic "three identical cards horizontally" feature row is banned. Use 2-column zig-zag, asymmetric grid, scroll-pinned, or horizontal-scroll alternative.
</layout_spacing>

<content_data>
The "Jane Doe" effect - generic placeholder content reads as slop.
- NO generic names. "John Doe", "Sarah Chan", "Jack Su" -> use creative, realistic, locale-appropriate names.
- NO generic avatars. No SVG "egg" or Lucide user icons -> believable photo placeholders or specific styling.
- NO fake-perfect numbers. Avoid `99.99%`, `50%`, `1234567`. Use organic, messy data (`47.2%`, `+1 (312) 847-1928`).
- NO startup-slop brand names. "Acme", "Nexus", "SmartFlow", "Cloudly" -> invent contextual, premium names that sound real.
- NO filler verbs. "Elevate", "Seamless", "Unleash", "Next-Gen", "Revolutionize" -> concrete verbs only.
</content_data>

<external_resources>
- NO hand-rolled SVG icons. Use Phosphor / HugeIcons / Radix / Tabler. Lucide on explicit request only.
- Hand-rolled decorative SVGs strongly discouraged as default.
- NO div-based fake screenshots. Never build a fake product UI out of styled divs. Use real images, generated images, or skip the preview.
- NO broken Unsplash links. Use `https://picsum.photos/seed/{descriptive-string}/{w}/{h}`, or generated placeholders, or actual assets.
- shadcn/ui customization: allowed, but NEVER in default state. Customize radii, colors, shadows, typography.
- Production-Ready Cleanliness: code visually clean, memorable, meticulously refined.
</external_resources>

<production_test_tells>
These came out of real LLM-generated landing-page tests - the signatures the model defaults to when it tries to "look designed." Hard bans unless the brief explicitly calls for one.

<hero_top>
- NO version labels in the hero. `V0.6`, `v2.0`, `BETA`, `INVITE-ONLY PREVIEW`, `EARLY ACCESS`, `ALPHA` - banned as default eyebrows. Only when the brief is explicitly a product launch / preview status.
- NO "Brand . No. 01"-style sub-eyebrows ("Marrow . No. 01 . The 6-quart"). Skip them.
</hero_top>

<section_numbering_microlabels>
- NO section-number eyebrows. `00 / INDEX`, `001 . Capabilities`, `002 . Featured commission`, `06 . how it works` - banned. Eyebrows name the topic in plain language; they do not enumerate.
- NO `01 / 4`-style pagination on images or bento tiles. If the user can count, they don't need the label.
- NO `Scroll . 001 Capabilities`-style scroll cues. A simple arrow or "Scroll" is enough; no section-number prefix.
- NO "Index of Work, 2018 - 2026"-style range labels as eyebrows. Just say what the section is.
</section_numbering_microlabels>

<separators_dots>
- The middle-dot (`.`) is rationed. Maximum 1 per line in metadata strips. Do NOT use it as the default separator for everything ("foo . bar . baz . qux"). Prefer line breaks, hairlines, or columns.
- NO decorative colored status dots on every list/nav/badge. A dot before "ONE Q4 SLOT OPEN" or before every nav link / task row - banned by default. Acceptable only when the dot conveys actual semantic state (server status, availability flag) and used sparingly.
</separators_dots>

<typography_flourishes>
- NO `<br>`-broken-and-italicized headlines as a default "design move" ("for thirty&lt;br&gt;&lt;i&gt;years.&lt;/i&gt;"-type splits). Headlines read naturally first; get clever only when the brief demands it.
- NO vertical rotated text ("INDEX OF WORK, 2018 - 2026" rotated 90 degrees). Agency-portfolio cliche. Only when the brief is explicitly agency / Awwwards / experimental AND it serves a real composition purpose.
- NO crosshair / hairline grid lines as decoration. Vertical/horizontal lines drawn just to make the page "feel designed" - banned. Use them only to organize real content.
</typography_flourishes>

<fake_product_previews>
- NO div-based fake product UI in the hero (fake task list, fake terminal, fake dashboard built from styled divs). The #1 LLM-design Tell. Use a real screenshot, a generated image, a real component preview, or none.
- NO fake version footers ("v0.6.2-rc.1", "last sync 4s ago . main") inside fake screenshots. Adds nothing, screams AI.
</fake_product_previews>

<marketing_copy>
- NO "Quietly in use at" / "Quietly trusted by" social-proof headers. Use natural language ("Trusted by", "Used at", "Customers include") or skip the heading.
- NO "From the field" / "Field notes" / "Currently on the bench" / "On our desks" / "Loose plates" poetic labels on quote/blog/sidebar sections. Performative-craftsman. Use plain functional labels ("Testimonials", "Latest writing", "Now working on") or skip.
- NO mock-humble industry references in body copy. Cute and AI-y.
- NO weather / locale strips ("LIS 14:23 . 18C") in headers/footers unless the brief is explicitly about a place / timezone-distributed studio.
- NO micro-meta-sentences under eyebrows. Clutter. Eyebrow + Headline + Body is enough.
- NO generic step labels. "Stage 1 / Stage 2", "Step 1 / Step 2", "Phase 01 / Phase 02", "Pass One / Pass Two" - banned. The actual step content is the label. If you must show progression, use the verb-noun directly ("Install", "Configure", "Ship").
</marketing_copy>

<pills_labels_stamps>
- NO pills/labels/tags overlaid on images. No `<span>` overlays on photos with tags like `Brand . 02`, `PLATE . BRAND`, `Field notes - journal`. Let the image speak alone, or caption directly below (outside the image).
- NO photo-credit captions as decoration. "Field study no. 12 . Ines Caetano", "Plate 03 . House archive", "Frame XII . 35mm" under stock/picsum images are pretentious. Photo credit only when a real photographer is credited for a real photo (with permission). Otherwise skip or use a one-line functional caption ("The 6-quart, in Sage.").
- NO version footers on marketing pages. `v1.4.2`, `Build 0048`, `last sync 4s ago . main` are CLI/devtool fixtures, not landing-page content.
- NO "Reservation 412 of 800"-style live-stock counters as decoration. Only if the brief is a limited-run waitlist with real data.
</pills_labels_stamps>

<decoration_strips>
- NO decoration text strip at hero bottom. `BRAND. MOTION. SPATIAL.`, `TYPE / FORM / MOTION`, `DESIGN . BUILD . SHIP`, `ESTD. 2018 . LISBON . BRAND. MOTION. SPATIAL.` as a small mono-caps strip across hero bottom - agency-portfolio cliche. Only when the strip carries real navigable links (sticky bottom nav) or real status info (cookie banner, build info on a docs site).
- NO floating top-right sub-text in section headings. A giant left-aligned headline with a small explainer paragraph floating in the top-right corner with no clear alignment - that floater is the Tell. Put sub-text directly under the headline, or build a clean 2-column header (left: headline, right: aligned body), not a tiny corner paragraph.
</decoration_strips>

<lists_dividers_scoring>
- NO `border-t` + `border-b` on every row of a long list/spec table. Pick one (bottom-border between rows OR top-border above the group) and use it sparsely. A 10-row spec table with hairlines under each row is the laziest layout - see design-directives.md content_density for alternatives.
- NO scoring/progress bars with filled background tracks as comparison visuals. Prefer a number + small icon, or a tiny inline bar WITHOUT a background track. Big filled `bg-zinc-200` tracks with a partial fill are dashboard clutter on a landing page.
</lists_dividers_scoring>

<locale_time_scroll>
- Locale / city-name / time / weather strips are banned for 99% of briefs. "Lisbon, working with founders" in the hero, "1200-690 Lisbon, Portugal" in the footer, "Lisbon 14:23 . 18C" in the nav. Agency-portfolio decoration tells. Allowed ONLY when: the brief explicitly describes a globally-distributed studio, OR a travel-focused brand, OR a real-world physical venue. A single contact-address mention in the footer is fine; an atmospheric locale strip is not.
- Scroll cues are banned. `Scroll`, `scroll`, `Scroll to explore`, `Scroll to walk through it`, animated mouse-wheel icons. If the user has not scrolled yet, they are looking at the hero. They know what scroll is.
- ZERO decorative status dots by default. A coloured dot before nav items, list rows, badges, status labels is a Tell. Only when conveying real semantic state (live server indicator, live availability flag), limited to one per page section.
</locale_time_scroll>
</production_test_tells>

<em_dash_ban>
Em-dash (`-`) is COMPLETELY banned. It is the LLM's signature stylistic crutch and the #1 visual Tell in production tests. No "limited use" allowance, no "natural language frequency" allowance, no "body copy is fine" allowance. None.

- Banned in headlines. Use a period or a comma.
- Banned in eyebrows / labels / pills / button text / image captions / nav items. Replace with line breaks, columns, or hairlines.
- Banned in body copy. Restructure: two sentences with a period, OR a comma, OR parentheses, OR a colon.
- Banned in quote attribution. Use a normal hyphen with spaces (` - `) or a line break + smaller-weight name.
- Banned in en-dash form (`-`) when used as a separator. Date ranges (`2018-2026`) use a hyphen. Number ranges (`40-80k`) use a hyphen.

The ONLY permitted dash characters on the page:
- Regular hyphen `-` (compound words, ranges, line dividers in markup)
- Minus sign in math (`-5C`)

<b>If your output contains a single em-dash or en-dash-separator anywhere visible to the user, the output fails the Pre-Flight Check and must be rewritten.</b> This rule is binary: zero em-dashes.
</em_dash_ban>

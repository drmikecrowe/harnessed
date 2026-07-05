<overview>
When to reach for a real, official design system vs. build an aesthetic from native CSS. Plus install commands, canonical doc sources, and the honest truth about Apple Liquid Glass on the web.
</overview>

<system_map>
Once you have the design read and dials, pick the right foundation. Do not invent CSS for things that have an official package. Do not pretend an aesthetic trend is an official system.

<official_systems>
| Brief reads as... | Reach for | Why |
|---|---|---|
| Microsoft / enterprise SaaS / dashboards | `@fluentui/react-components` or `@fluentui/web-components` | Official Fluent UI, Microsoft tokens, a11y done |
| Google-ish UI, Material-flavored product | `@material/web` + Material 3 tokens | Official, theme-able via Material Theming |
| IBM-style B2B / enterprise analytics | `@carbon/react` + `@carbon/styles` | Official Carbon, mature data-density patterns |
| Shopify app surfaces | `polaris.js` web components / Polaris React | Required for Shopify admin UI |
| Atlassian / Jira-style product | `@atlaskit/*` + `@atlaskit/tokens` | Official Atlassian DS |
| GitHub-style devtool / community page | `@primer/css` or `@primer/react-brand` | Official Primer; Brand variant for marketing |
| Public-sector UK service | `govuk-frontend` | Legally / regulatorily expected |
| US public-sector / trust-first | `uswds` | Same |
| Fast local-business / agency MVP | Bootstrap 5.3 | Boring, fast, works |
| Modern accessible React foundation | `@radix-ui/themes` | Primitives + polished theme |
| Modern SaaS where you own the components | shadcn/ui (`npx shadcn@latest add ...`) | You own the code, easy to customise; never ship default state |
| Tailwind-based modern SaaS / AI marketing | Tailwind v4 utilities + `dark:` variant | Default for indie + small team builds |
</official_systems>
</system_map>

<honesty_rules>
- If the brief reads as one of the systems above, install and use the OFFICIAL package. Do not recreate its CSS by hand. Do not import a system's tokens but then override 90% of them.
- <b>One system per project.</b> Do not mix Fluent React with Carbon in the same tree. Do not import shadcn/ui components into a Material 3 app.
- For static / no-framework sites, prefer a CSS-only distribution of the system (GOV.UK Frontend, USWDS, Bootstrap, Primer CSS) rather than forcing a React dependency. See static-sites.md.
</honesty_rules>

<aesthetics_not_systems>
For these directions there is NO single official package. Build with native CSS (+ Tailwind if your build supports it) + a maintained component library. Be honest in code comments about borrowed inspiration vs. official material.

| Aesthetic | Honest implementation |
|---|---|
| Glassmorphism / "frosted glass" | `backdrop-filter`, layered borders, highlight overlays. Solid-fill fallback for `prefers-reduced-transparency`. |
| Bento (Apple-style tile grids) | CSS Grid with mixed cell sizes. No single library owns this. |
| Brutalism | Native CSS, monospace, raw borders. No library. |
| Editorial / magazine | Serif type, asymmetric grid, generous whitespace. No library. |
| Dark tech / hacker | Mono + accent neon, terminal motifs. No library. |
| Aurora / mesh gradients | SVG or layered radial gradients. No library. |
| Kinetic typography | Native CSS animations, scroll-driven animations, GSAP for hijacks. No library. |
| Apple Liquid Glass | Apple documents this for Apple platforms only. No official `liquid-glass.css`. Web implementations are approximations - label clearly. See liquid_glass below. |
</aesthetics_not_systems>

<install_commands>
```bash
# Material Web (Material 3)
npm install @material/web
# Fluent UI React (v9)
npm install @fluentui/react-components
# Fluent UI Web Components (framework-free)
npm install @fluentui/web-components @fluentui/tokens
# IBM Carbon
npm install @carbon/react @carbon/styles
# Radix Themes
npm install @radix-ui/themes
# shadcn/ui (open code, owned components)
npx shadcn@latest init && npx shadcn@latest add button card badge separator input
# Primer CSS (GitHub product/devtool UI)
npm install --save @primer/css
# Primer Brand (GitHub marketing UI)
npm install @primer/react-brand
# GOV.UK Frontend
npm install govuk-frontend
# USWDS (US Web Design System)
npm install uswds
# Atlassian Design System (Atlaskit)
yarn add @atlaskit/css-reset @atlaskit/tokens @atlaskit/button @atlaskit/badge @atlaskit/section-message @atlaskit/card
# Bootstrap 5.3
npm install bootstrap
# Shopify Polaris Web Components (Shopify apps only) - add to app HTML head:
#   <meta name="shopify-api-key" content="%SHOPIFY_API_KEY%" />
#   <script src="https://cdn.shopify.com/shopifycloud/polaris.js"></script>
```
</install_commands>

<canonical_sources>
Read the official docs before reinventing.

- <b>Material Web:</b> github.com/material-components/material-web, material-web.dev/theming/material-theming, m3.material.io/develop/web
- <b>Fluent UI:</b> fluent2.microsoft.design/get-started/develop, learn.microsoft.com/en-us/fluent-ui/web-components, github.com/microsoft/fluentui
- <b>Carbon:</b> carbondesignsystem.com, github.com/carbon-design-system/carbon
- <b>Shopify Polaris:</b> shopify.dev/docs/api/app-home/web-components, polaris-react.shopify.com/components
- <b>Atlassian:</b> atlassian.design/get-started/develop, atlassian.design/tokens/design-tokens
- <b>Primer:</b> primer.style, github.com/primer/css, github.com/primer/brand
- <b>GOV.UK:</b> design-system.service.gov.uk/components/button, github.com/alphagov/govuk-frontend
- <b>USWDS:</b> designsystem.digital.gov/documentation/developers, github.com/uswds/uswds
- <b>Bootstrap:</b> getbootstrap.com/docs/5.3/layout/grid
- <b>Tailwind:</b> tailwindcss.com/docs/dark-mode, tailwindcss.com/blog/tailwindcss-v4
- <b>Radix:</b> radix-ui.com/themes/docs/components/theme, github.com/radix-ui/themes
- <b>shadcn/ui:</b> ui.shadcn.com/docs, github.com/shadcn-ui/ui
- <b>Native CSS / W3C:</b> developer.mozilla.org backdrops, `prefers-color-scheme`, `prefers-reduced-motion`, Grid layout, Scroll-driven animations; drafts.csswg.org/scroll-animations-1
- <b>Apple Liquid Glass (Apple platforms only):</b> developer.apple.com/design/human-interface-guidelines/materials, developer.apple.com/documentation/TechnologyOverviews/liquid-glass, developer.apple.com/documentation/SwiftUI/Material
</canonical_sources>

<liquid_glass>
Do NOT treat random CSS snippets as official Apple Liquid Glass.

<b>What is official:</b> Apple documents Liquid Glass inside its HIG and Developer Documentation for Apple platforms. It is a dynamic material for Apple platform UI, not a public web CSS package.

<b>What is NOT official:</b> there is no `liquid-glass.css` from Apple for normal websites. A web approximation uses `backdrop-filter`, transparent backgrounds, layered borders, highlight overlays, gradients, motion, and strong-contrast fallbacks. That is web glassmorphism / frosted-glass approximation - label it as such in comments.

<approximation_skeleton>
```css
.liquid-glass-web-approx {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  border-radius: 999px;
  border: 1px solid rgb(255 255 255 / .32);
  background:
    linear-gradient(135deg, rgb(255 255 255 / .30), rgb(255 255 255 / .08)),
    rgb(255 255 255 / .12);
  backdrop-filter: blur(24px) saturate(180%) contrast(1.05);
  -webkit-backdrop-filter: blur(24px) saturate(180%) contrast(1.05);
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / .48),
    inset 0 -1px 0 rgb(255 255 255 / .12),
    0 18px 60px rgb(0 0 0 / .18);
}
.liquid-glass-web-approx::before {
  content: ""; position: absolute; inset: 0; z-index: -1; border-radius: inherit;
  background:
    radial-gradient(circle at 20% 0%, rgb(255 255 255 / .55), transparent 34%),
    linear-gradient(90deg, rgb(255 255 255 / .18), transparent 42%, rgb(255 255 255 / .14));
  pointer-events: none;
}
.liquid-glass-web-approx::after {
  content: ""; position: absolute; inset: 1px; border-radius: inherit;
  border: 1px solid rgb(255 255 255 / .14); pointer-events: none;
}
@media (prefers-color-scheme: dark) {
  .liquid-glass-web-approx {
    border-color: rgb(255 255 255 / .18);
    background:
      linear-gradient(135deg, rgb(255 255 255 / .16), rgb(255 255 255 / .04)),
      rgb(15 23 42 / .42);
    box-shadow: inset 0 1px 0 rgb(255 255 255 / .22), 0 18px 60px rgb(0 0 0 / .42);
  }
}
@media (prefers-reduced-transparency: reduce) {
  .liquid-glass-web-approx { background: rgb(255 255 255 / .96); backdrop-filter: none; -webkit-backdrop-filter: none; }
}
```
`prefers-reduced-transparency` has uneven browser support; test it. Always provide enough contrast even without blur. This skeleton works for static sites too - it is pure CSS.
</approximation_skeleton>
</liquid_glass>

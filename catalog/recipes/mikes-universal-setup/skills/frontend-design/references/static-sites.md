<overview>
Stack guidance for static websites: GitHub Pages, S3 + CloudFront, Netlify / Vercel / Cloudflare Pages, plain HTML/CSS/JS, and static site generators (Eleventy, Astro, Hugo, Jekyll). This is the IMPLEMENTATION layer for static deployments. The visual rules in design-directives.md, ai-tells.md, and motion.md apply identically - they are stack-agnostic. This reference only swaps how you build and ship.
</overview>

<when_this_applies>
Use this reference when the brief or repo signals a static deployment:
- "Deploy to GitHub Pages", "host on S3", "static site", "no backend", "just HTML/CSS".
- Repo has `_config.yml` (Jekyll), `.eleventy.js` / `eleventy.config.js` (11ty), `astro.config.*` (Astro), `config.toml`/`hugo.toml` (Hugo), a `.nojekyll` file, or a `CNAME` file.
- The goal is a marketing page, portfolio, blog, docs, or landing with no server-side logic.

<b>Do NOT default to React/Next for a static site.</b> A static site does not need RSC, `"use client"`, hydration, or a JS runtime. Reach for the lightest tool that ships the page. app-stack.md is for app/framework builds only.
</when_this_applies>

<stack_choice>
Pick the lightest layer that meets the need.

<plain_html_css_js>
Zero build. Best for single pages, one-pagers, simple multi-page sites. Plain HTML + CSS (or one minified CSS file) + vanilla JS. No framework, no bundler, no `node_modules`. Fastest to ship, smallest payload, trivial to host anywhere. Default to this for anything under ~5 pages with no templating needs.
</plain_html_css_js>

<static_site_generators>
For multi-page sites, shared layouts, content collections, or a blog, use an SSG. These compile to plain static HTML you deploy the same way.

- <b>Eleventy (11ty)</b> - the preferred default for content sites. Templating in Liquid / Nunjucks / Markdown, zero JS shipped by default, data cascade, fast. Excellent for blogs, portfolios, docs. (The author of this skill runs an 11ty blog - this is a well-trodden path.)
- <b>Astro</b> - component-based (`.astro` files, can embed React/Vue/Svelte as opt-in islands). Ships zero JS by default; add interactivity only where needed via "client directives". Best when you want component ergonomics but a static output, or marketing sites with a few interactive islands.
- <b>Hugo</b> - Go binary, extremely fast builds, Go templates. Great for very large content sites; steeper template learning curve.
- <b>Jekyll</b> - Ruby, GitHub Pages' DEFAULT builder (no Actions needed). Liquid templates. Use when you want zero-config GitHub Pages and are OK with Ruby.
- <b>MkDocs (Material)</b> / <b>Docusaurus</b> - purpose-built for docs.

<b>Rule:</b> one generator per project. Do not mix Astro islands with a Jekyll template layer.
</static_site_generators>
</stack_choice>

<css_strategy>
- <b>Plain CSS</b> is the best default for small static sites. Use CSS custom properties (variables) for your token system - this is how you implement the palette/type scale from design-directives.md without Tailwind.
- <b>Tailwind</b> is fine IF you have a build step: Astro, 11ty+PostCSS, or the standalone Tailwind CLI (`npx @tailwindcss/cli -i in.css -o out.css --watch`) work without a JS framework. Tailwind v4 standalone CLI is genuinely build-light. Tailwind classes used as examples elsewhere in this skill (e.g. `text-4xl md:text-6xl`) are illustrative - translate to plain CSS (`font-size`, media queries) when not using Tailwind.
- <b>Sass/SCSS</b> if the SSG supports it (11ty, Hugo, Jekyll all do) and you want nesting/mixins without a utility framework.
- Whichever you pick, define one token layer (colors, type scale, spacing, radii) as variables and reference it everywhere - this is how you enforce the color/shape consistency locks.
</css_strategy>

<animation_without_react>
Static sites have every animation primitive the app stack has, minus React state. Prefer the lightest tool that works.

- <b>CSS scroll-driven animations (no JS):</b> `animation-timeline: view()` for scroll-reveal, `animation-timeline: scroll()` for scroll-linked effects. Native, progressive-enhancement-friendly. Pair with a `@media (prefers-reduced-motion: reduce)` override that disables.
- <b>IntersectionObserver (tiny vanilla JS):</b> add a class when an element enters the viewport; let CSS handle the transition. ~15 lines, no library. This is the static-site equivalent of Motion's `whileInView`.
- <b>GSAP + ScrollTrigger (standalone):</b> load via `<script type="module">` or npm, no React needed. Use for the sticky-stack / horizontal-pan patterns in motion.md - those skeletons are vanilla GSAP and work as-is if you drop the `'use client'` line.
- <b>Motion One (`motion`) vanilla API:</b> `animate()`, `inView()`, `scroll()`, `stagger()` work on plain DOM nodes. Lighter than GSAP for simple tweens.
- <b>Lenis / native `scroll-behavior`:</b> smooth scroll without hijacking. Prefer CSS `scroll-behavior: smooth` + anchor links over a JS smooth-scroll lib unless you need inertia.
- <b>STILL BANNED:</b> `window.addEventListener('scroll', ...)` and `requestAnimationFrame` loops touching layout. See motion.md forbidden patterns.
- <b>Reduced motion is mandatory</b> for MOTION_INTENSITY > 3. Gate with `@media (prefers-reduced-motion: reduce)` and a JS feature-detect; collapse loops, parallax, scroll-hijack, and magnetic physics to static/instant.
</animation_without_react>

<fonts>
Self-host. Never `<link>` Google Fonts in production (render-blocking + privacy).
- Self-host woff2 with `@font-face { font-display: swap; }`. Preload the critical (above-fold) face: `<link rel="preload" as="font" type="font/woff2" href="/fonts/..." crossorigin>`.
- If you have a build step, Fontsource (`@fontsource/geist`, etc.) gives self-hosted bundles of the same families referenced in design-directives.md (Geist, Satoshi, Cabinet Grotesk).
- Subset to the glyphs/weights you actually use to cut payload.
</fonts>

<icons_static>
- Inline the SVG sources from the same libraries the app stack uses (Phosphor, HugeIcons, Tabler) - copy the path data into `<svg>` or build an SVG sprite. These libs publish raw SVG.
- <b>Iconify</b> (`@iconify/json` or the Iconify API/CDN) gives on-demand SVG from hundreds of sets with no framework lock-in.
- Same rules: never hand-roll icon paths, one family per project, never `lucide` unless explicitly requested.
</icons_static>

<images>
- Real images first: generate with the image tool when available, else `https://picsum.photos/seed/{descriptive-seed}/{w}/{h}`. Never div-based fake screenshots, never pure-text "minimalism".
- Always set explicit `width` and `height` (or `aspect-ratio`) to prevent CLS.
- `loading="lazy"` on below-fold images; preload the hero: `<link rel="preload" as="image" ...>`.
- Optimize at build (sharp / imagemin / squoosh) or pre-export WebP/AVIF. For zero-build plain-HTML, pre-optimize manually and serve modern formats with a `<picture>` fallback.
</images>

<hosting_github_pages>
- <b>Two site types:</b> user/org site (`<user>.github.io` repo, served from root, no path prefix) vs. project site (`<user>.github.io/<repo>`, needs a base path). Set the base path in your generator: 11ty `pathPrefix: "/repo/"`, Astro `base: "/repo/"`, Hugo `baseURL`, Jekyll `baseurl: "/repo"`. Every internal link and asset URL must honor it - getting this wrong is the #1 broken-static-site bug.
- <b>Jekyll is the default builder.</b> Add an empty `.nojekyll` file to serve raw files as-is (use this for every non-Jekyll SSG so GitHub doesn't try to run Jekyll and drop your `_assets`/`_*` dirs).
- <b>Non-Jekyll SSGs:</b> deploy via GitHub Actions. Astro, 11ty, and Hugo all publish official Actions workflows - use them rather than hand-rolling. Typical flow: build on push, upload `dist/` as Pages artifact, deploy.
- <b>Custom domain:</b> commit a `CNAME` file containing the bare/apex or www domain; configure DNS (ALIAS/ANAME or CNAME). HTTPS is auto-provisioned - enable "Enforce HTTPS" in repo Settings > Pages.
- <b>Limits:</b> ~1 GB published size, ~100 GB/month bandwidth, ~10 builds/hour. Fine for marketing/portfolio/blog; not for heavy media.
- <b>SPA-on-Pages:</b> only if you must. GitHub Pages serves real files; for client-side routing add a 404.html that redirects to index.html (hacky). Prefer multi-page static or Astro for routing.
</hosting_github_pages>

<hosting_s3_cloudfront>
- <b>Bucket:</b> do NOT make it world-public if you use CloudFront. Grant access via <b>Origin Access Control (OAC)</b> (preferred over the legacy OAI). Set index document (and error document if SPA).
- <b>Content-Type matters:</b> S3 serves whatever `Content-Type` the object has. `aws s3 sync` guesses MIME from extension - usually fine; verify CSS/JS/woff2 get correct types, else browsers reject them. Set `--content-type` explicitly for edge cases, or use `--acl public-read` only for the legacy public-bucket pattern (deprecated; prefer OAC).
- <b>Cache strategy:</b> long-lived (`Cache-Control: public, max-age=31536000, immutable`) for hashed/fingerprinted assets; short (`max-age=300` or `s-maxage=600, stale-while-revalidate`) for HTML so deploys are visible fast. CloudFront cache policy should honor these or you set TTLs at the distribution.
- <b>Deploy:</b> `aws s3 sync ./dist s3://bucket --delete` then `aws cloudfront create-invalidation --distribution-id ... --paths "/*"` (or scope invalidation to changed HTML only to save cost).
- <b>HTTPS:</b> ACM certificate on CloudFront (us-east-1), redirect HTTP to HTTPS at the distribution. Map apex via Route53 ALIAS.
- <b>Routing:</b> for multi-page static, every route is a real `.html` file (S3 serves it). For a SPA, use a CloudFront custom error response: 403/404 -> `/index.html` with 200. Prefer multi-page static for marketing sites.
</hosting_s3_cloudfront>

<hosting_netlify_vercel_cf>
Git-connected, zero-config deploys with framework auto-detection. Set build command + publish directory (e.g. 11ty: `npx @11ty/eleventy` / `_site`; Astro: `astro build` / `dist`; Hugo: `hugo` / `public`). Free TLS, global CDN, and optional serverless functions / forms if you later need a contact form or edge logic. For a pure static site these are the lowest-ops option.
</hosting_netlify_vercel_cf>

<perf_notes>
Static sites have a natural Core Web Vitals advantage (no hydration, no runtime JS). Protect it:
- Ship near-zero JS. Every script must earn its bytes. A reveal animation does not need a 40 KB framework.
- Inline critical CSS for the above-the-fold, defer the rest.
- Reserve image space (`width`/`height`/`aspect-ratio`) to hold CLS near 0.
- LCP is usually the hero image or headline font - preload both.
- Run Lighthouse before declaring done; the targets (LCP &lt; 2.5s, INP &lt; 200ms, CLS &lt; 0.1) are easiest to hit here.
</perf_notes>

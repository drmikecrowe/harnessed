<overview>
Default architecture for app/framework builds (React / Next.js / Tailwind / Motion). These are the DEFAULTS when the design read picks a real framework build, NOT a static site. For static sites (GitHub Pages, S3, plain HTML, SSGs) see static-sites.md instead.
</overview>

<stack>
- <b>Framework:</b> React or Next.js. Default to Server Components (RSC).
  - <b>RSC SAFETY:</b> Global state works ONLY in Client Components. In Next.js, wrap providers in a `"use client"` component.
  - <b>INTERACTIVITY ISOLATION:</b> Any component using Motion, scroll listeners, or pointer physics MUST be an isolated leaf with `'use client'` at the top. Server Components render static layouts only.
- <b>Styling:</b> <b>Tailwind v4</b> (default). Tailwind v3 only if the existing project demands it.
  - For v4: do NOT use the `tailwindcss` plugin in `postcss.config.js`. Use `@tailwindcss/postcss` or the Vite plugin.
- <b>Animation:</b> <b>Motion</b> (the library formerly known as Framer Motion). Import from `motion/react` (`import { motion } from "motion/react"`). The `framer-motion` package still works as a legacy alias; prefer `motion/react` in new code.
- <b>Fonts:</b> Always use `next/font` (Next.js) or self-host with `@font-face` + `font-display: swap`. Never link Google Fonts via `<link>` in production.
</stack>

<state>
- Local `useState` / `useReducer` for isolated UI.
- Global state ONLY for deep prop-drilling avoidance: Zustand, Jotai, or React context.
- <b>NEVER</b> use `useState` to track continuous values driven by user input (mouse position, scroll progress, pointer physics, magnetic hover). Use Motion's `useMotionValue` / `useTransform` / `useScroll`. `useState` re-renders the React tree on every change and collapses on mobile.
</state>

<icons>
- <b>Allowed libraries (priority order):</b> `@phosphor-icons/react`, `hugeicons-react`, `@radix-ui/react-icons`, `@tabler/icons-react`.
- <b>Discouraged:</b> `lucide-react`. Acceptable only when the user explicitly asks or the project already depends on it.
- <b>NEVER hand-roll SVG icons.</b> If a glyph is missing, install a second library or compose from primitives; do not draw icon paths from scratch.
- <b>One family per project.</b> Do not mix Phosphor with Lucide in the same tree.
- <b>Standardize `strokeWidth` globally</b> (e.g. `1.5` or `2.0`).
- For static sites, inline the SVG sources from these same libraries (or use Iconify) rather than pulling a React dependency.
</icons>

<emoji_policy>
Discouraged by default in code, markup, and visible text. Replace symbols with icon-library glyphs. <b>Override:</b> allow emojis only when the user explicitly asks for a playful / chat-style / social-native vibe, and even then use them sparingly with intent.
</emoji_policy>

<responsiveness>
- Standardize breakpoints (`sm 640`, `md 768`, `lg 1024`, `xl 1280`, `2xl 1536`).
- Contain page layouts using `max-w-[1400px] mx-auto` or `max-w-7xl`.
- <b>Viewport Stability:</b> NEVER use `h-screen` for full-height Hero sections. ALWAYS use `min-h-[100dvh]` to prevent layout jumping on mobile (iOS Safari address bar).
- <b>Grid over Flex-Math:</b> NEVER use complex flexbox percentage math (`w-[calc(33%-1rem)]`). ALWAYS use CSS Grid (`grid grid-cols-1 md:grid-cols-3 gap-6`).
</responsiveness>

<dependency_verification>
Before importing ANY 3rd-party library, check `package.json`. If the package is missing, output the install command first. <b>Never</b> assume a library exists.
</dependency_verification>

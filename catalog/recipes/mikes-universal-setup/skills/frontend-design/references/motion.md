<overview>
Context-aware motion patterns and canonical code skeletons. Motion is a tool, not a default - none of this fires automatically. Use only what the design read (see brief-and-dials.md MOTION_INTENSITY dial) calls for. The GSAP skeletons below are framework-free vanilla TypeScript/JSX and work on static sites (drop the `'use client'` line); the Motion (`whileInView`) skeleton is React - for static sites use the IntersectionObserver equivalent noted in static-sites.md.
</overview>

<context_aware_proactivity>
- <b>Liquid Glass / Glassmorphism:</b> appropriate for premium consumer, Apple-adjacent, luxury brand, media-overlay. Inappropriate for dashboards, public-sector, "boring B2B." When used, go beyond `backdrop-blur`: add a 1px inner border (`border-white/10`) and a subtle inner shadow (`shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]`) for physical edge refraction. Provide a solid-fill fallback under `prefers-reduced-transparency`.
- <b>Magnetic Micro-physics:</b> use when MOTION_INTENSITY > 5 AND the brief reads premium / playful / agency. Implement EXCLUSIVELY with Motion's `useMotionValue` / `useTransform` outside the React render cycle. Never `useState`. (App stack only; for static sites use GSAP's quickTo or a rAF-free transform.)
- <b>Perpetual Micro-Interactions</b> (Pulse, Typewriter, Float, Shimmer, Carousel): use when MOTION_INTENSITY > 5 AND the section actively benefits (status indicators, live feeds, AI-feel). Not every card needs an infinite loop. Informational sections stay still. Apply spring physics (`type: "spring", stiffness: 100, damping: 20`) - no linear easing.
- <b>"Motion claimed, motion shown."</b> If MOTION_INTENSITY > 4, the page must actually move: entry transitions on hero, scroll-reveal on key sections, hover physics on CTAs, at minimum. A static page claiming MOTION_INTENSITY: 7 is broken. If you cannot ship working motion, drop the dial to 3 and ship a clean static page. Never half-build motion that breaks (cut-off ScrollTriggers, jumpy enters, missing cleanups).
- <b>MOTION MUST BE MOTIVATED (mandatory).</b> Before any animation ask: "what does this communicate?" Valid: hierarchy, storytelling, feedback, state transition. Invalid: "it looked cool." GSAP everywhere because it is available is amateur. Each ScrollTrigger, marquee, pinned section needs a reason you can state in one sentence, or drop it.
- <b>MARQUEE MAX-ONE-PER-PAGE (mandatory).</b> Horizontal scrolling text marquees ("logos endlessly scrolling", "manifesto scrolling sideways", "kinetic word strip") are appropriate at most ONCE per page. Two or more reads as lazy filler.
- <b>GSAP Sticky-Stack / Horizontal-Pan</b> must be a REAL sticky-stack / real pin, not a sequential reveal list. Common failure: trigger fires halfway through scroll instead of pinning at viewport top. Fix: `start: "top top"` not `"top center"` or `"top 80%"`.
</context_aware_proactivity>

<sticky_stack>
Canonical sticky card-stack skeleton (vanilla GSAP, works on static sites and in React client leaves):

```tsx
"use client"; // drop this line for static/vanilla usage
import { useRef, useEffect } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useReducedMotion } from "motion/react"; // for React only; gate manually on static

gsap.registerPlugin(ScrollTrigger);

export function StickyStack({ cards }: { cards: React.ReactNode[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce || !ref.current) return;
    const ctx = gsap.context(() => {
      const cardEls = gsap.utils.toArray<HTMLElement>(".stack-card");
      cardEls.forEach((card, i) => {
        if (i === cardEls.length - 1) return;
        ScrollTrigger.create({
          trigger: card,
          start: "top top",               // pin at viewport top
          endTrigger: cardEls[cardEls.length - 1],
          end: "top top",
          pin: true,
          pinSpacing: false,
        });
        gsap.to(card, {
          scale: 0.92,
          opacity: 0.55,
          ease: "none",
          scrollTrigger: {
            trigger: cardEls[i + 1],
            start: "top bottom",
            end: "top top",
            scrub: true,
          },
        });
      });
    }, ref);
    return () => ctx.revert();
  }, [reduce]);

  return (
    <div ref={ref} className="relative">
      {cards.map((card, i) => (
        <div key={i} className="stack-card sticky top-0 min-h-[100dvh] flex items-center justify-center">
          {card}
        </div>
      ))}
    </div>
  );
}
```

Critical points: `start: "top top"`, `pin: true`, every card except the last is pinned, the scale/opacity transform is driven by the NEXT card's scroll trigger (so the previous card shrinks as the next arrives).
</sticky_stack>

<horizontal_pan>
Canonical horizontal-scroll-hijack skeleton (vanilla GSAP):

```tsx
"use client"; // drop this line for static/vanilla usage
import { useRef, useEffect } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useReducedMotion } from "motion/react";

gsap.registerPlugin(ScrollTrigger);

export function HorizontalPan({ children }: { children: React.ReactNode }) {
  const wrap = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce || !wrap.current || !track.current) return;
    const ctx = gsap.context(() => {
      const distance = track.current!.scrollWidth - window.innerWidth;
      gsap.to(track.current, {
        x: -distance,
        ease: "none",
        scrollTrigger: {
          trigger: wrap.current,
          start: "top top",               // pin when section top hits viewport top
          end: () => `+=${distance}`,     // scroll distance = track width minus viewport
          pin: true,
          scrub: 1,
          invalidateOnRefresh: true,
        },
      });
    }, wrap);
    return () => ctx.revert();
  }, [reduce]);

  return (
    <section ref={wrap} className="relative overflow-hidden">
      <div ref={track} className="flex h-[100dvh] items-center">{children}</div>
    </section>
  );
}
```

Critical points: `start: "top top"`, `pin: true`, `end: "+=${distance}"` (scroll length = horizontal travel), `scrub: 1`. The wrapper pins, the inner track slides horizontally as the user scrolls vertically.
</horizontal_pan>

<scroll_reveal_stagger>
Lighter alternative for simple "items appear as they enter viewport" (no pinning). In React prefer Motion's `whileInView` over GSAP. For static sites, the equivalent is a 15-line IntersectionObserver that adds an `is-visible` class; CSS handles the transition.

```tsx
"use client";
import { motion, useReducedMotion } from "motion/react";

export function RevealStagger({ items }: { items: string[] }) {
  const reduce = useReducedMotion();
  return (
    <ul className="grid gap-6">
      {items.map((item, i) => (
        <motion.li
          key={item}
          initial={reduce ? false : { opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.6, delay: i * 0.06, ease: [0.16, 1, 0.3, 1] }}
        >
          {item}
        </motion.li>
      ))}
    </ul>
  );
}
```

Use for: feature lists, testimonial grids, logo walls, anything that just needs "enter on scroll." Save GSAP for actual pin/scrub work.
</scroll_reveal_stagger>

<forbidden_animation>
- <b>`window.addEventListener("scroll", ...)` is banned.</b> Runs on every scroll frame, jank-prone, no batching. Use Motion's `useScroll()`, GSAP's `ScrollTrigger`, IntersectionObserver, or CSS scroll-driven animations (`animation-timeline: view()`).
- <b>Custom scroll progress using `window.scrollY` in React state.</b> Same reason. Re-renders every frame.
- <b>`requestAnimationFrame` loops that touch React state.</b> Use motion values (`useMotionValue` + `useTransform`) instead.
- <b>Layout Transitions:</b> use Motion's `layout` and `layoutId` for visible state changes (re-ordering lists, expanding modals, shared elements between routes). Do not wrap static content in `layout` props "for safety" - it costs measurement work.
- <b>Staggered Orchestration:</b> use `staggerChildren` (Motion) or CSS cascade (`animation-delay: calc(var(--index) * 100ms)`) for reveal moments. For `staggerChildren`, parent (`variants`) and children MUST share the same Client Component tree.
- <b>Animation library choice:</b> Motion (`motion/react`) for UI/bento/state-change motion. GSAP + ScrollTrigger for full-page scrolltelling and scroll hijacks (isolate in a dedicated leaf with cleanup). Three.js / WebGL for canvas/3D. NEVER mix GSAP / Three.js with Motion in the same component tree - they fight over frames.
</forbidden_animation>

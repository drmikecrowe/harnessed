// @ts-check
import path from "node:path";
import { defineConfig } from "astro/config";

// Project GitHub Pages site → served at /harnessed/
// base is mandatory: every internal URL Astro generates is prefixed with it.
const BASE = "/harnessed/";

// Rewrites relative *.md links inside the synced wiki docs to their rendered
// route (/harnessed/docs/<slug>), matching Astro's glob-loader slug (each path
// segment lowercased, joined by "/"). Links that resolve outside the docs tree
// (e.g. ../../CLAUDE.md) or are already absolute/external/anchors are left alone.
function remarkDocsLinks() {
  const docsRoot = path.resolve(process.cwd(), "src", "content", "docs");
  const docsBase = BASE.replace(/\/$/, "") + "/docs";

  return (/** @type {any} */ tree, /** @type {any} */ file) => {
    const fromDir = file?.path ? path.dirname(file.path) : null;

    const rewrite = (/** @type {string} */ url) => {
      // Leave scheme://, //protocol-relative, /absolute, and #anchor links.
      if (/^([a-z][a-z0-9+.-]*:|\/\/|\/|#)/i.test(url)) return url;
      const [p, hash] = url.split("#");
      if (!p.toLowerCase().endsWith(".md") || !fromDir) return url;
      const rel = path.relative(docsRoot, path.resolve(fromDir, p));
      if (rel.startsWith("..") || path.isAbsolute(rel)) return url; // outside docs
      const slug = rel
        .replace(/\.md$/i, "")
        .split(path.sep)
        .map((s) => s.toLowerCase())
        .join("/");
      return `${docsBase}/${slug}${hash ? "#" + hash : ""}`;
    };

    const walk = (/** @type {any} */ node) => {
      if (node.type === "link" && typeof node.url === "string") {
        node.url = rewrite(node.url);
      }
      if (Array.isArray(node.children)) node.children.forEach(walk);
    };

    walk(tree);
  };
}

export default defineConfig({
  site: "https://drmikecrowe.github.io",
  base: BASE,
  trailingSlash: "ignore",
  markdown: {
    remarkPlugins: [remarkDocsLinks],
  },
});

// @ts-check
import { existsSync } from "node:fs";
import path from "node:path";
import { defineConfig } from "astro/config";

// Project GitHub Pages site → served at /harnessed/
// base is mandatory: every internal URL Astro generates is prefixed with it.
const BASE = "/harnessed/";

// GitHub wiki web base. The wiki flattens subdirectories to the bare page name
// (codebase/ARCHITECTURE.md → /wiki/ARCHITECTURE), so a link to a page that isn't
// published on the site still resolves to its canonical wiki location.
const WIKI_BASE = "https://github.com/drmikecrowe/harnessed/wiki";

// Rewrites relative *.md links inside the synced wiki docs. A link whose target IS
// published on the site (present under the synced content dir — see sync-docs.mjs) is
// rewritten to its rendered route (/harnessed/docs/<slug>, each segment lowercased). A
// link to a page the site does NOT publish (e.g. research/, codebase/, harnessed-design)
// is pointed at the canonical GitHub wiki page instead, so nothing 404s. Links that resolve
// outside the docs tree (e.g. ../../CLAUDE.md) or are already absolute/external/anchors are
// left alone.
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
      const abs = path.resolve(fromDir, p);
      const rel = path.relative(docsRoot, abs);
      if (rel.startsWith("..") || path.isAbsolute(rel)) return url; // outside docs
      const suffix = hash ? "#" + hash : "";
      // Not synced into the site → link to the canonical wiki page (flattened basename).
      if (!existsSync(abs)) {
        return `${WIKI_BASE}/${path.basename(p).replace(/\.md$/i, "")}${suffix}`;
      }
      const slug = rel
        .replace(/\.md$/i, "")
        .split(path.sep)
        .map((s) => s.toLowerCase())
        .join("/");
      return `${docsBase}/${slug}${suffix}`;
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

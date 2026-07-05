// Sync the wiki markdown (../docs) into the Astro content collection.
// Zero deps, Node ESM. Runs before `astro dev` / `astro build`.
//
// - Copies top-level *.md plus the guides/, research/, codebase/ subdirs.
// - Excludes _Sidebar.md (GitHub-wiki nav, not a page).
// - Wipes + recreates the target dir each run (generated, gitignored).
// - If ../docs is missing, warns and exits 0 (never hard-fail the build).

import { cp, mkdir, rm, readdir, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(__dirname, "..");
const docsSrc = path.resolve(webRoot, "..", "docs");
const target = path.join(webRoot, "src", "content", "docs");

// Subdirectories to mirror (matches the DocsLayout sidebar groups).
const INCLUDE_DIRS = ["guides", "research", "codebase"];
const EXCLUDE_FILES = new Set(["_Sidebar.md"]);

async function copyMarkdown(fromDir, toDir) {
  await mkdir(toDir, { recursive: true });
  const entries = await readdir(fromDir);
  let count = 0;
  for (const name of entries) {
    if (EXCLUDE_FILES.has(name)) continue;
    if (!name.toLowerCase().endsWith(".md")) continue;
    const from = path.join(fromDir, name);
    const s = await stat(from);
    if (!s.isFile()) continue;
    await cp(from, path.join(toDir, name));
    count += 1;
  }
  return count;
}

async function main() {
  if (!existsSync(docsSrc)) {
    console.warn(
      `[sync-docs] WARNING: ${docsSrc} not found. Skipping docs sync (site builds without the user-docs section).`,
    );
    process.exit(0);
  }

  await rm(target, { recursive: true, force: true });
  await mkdir(target, { recursive: true });

  let total = await copyMarkdown(docsSrc, target);

  for (const dir of INCLUDE_DIRS) {
    const src = path.join(docsSrc, dir);
    if (!existsSync(src)) continue;
    total += await copyMarkdown(src, path.join(target, dir));
  }

  console.log(`[sync-docs] Synced ${total} markdown file(s) into ${path.relative(webRoot, target)}`);
}

main().catch((err) => {
  console.error("[sync-docs] Failed:", err);
  process.exit(1);
});

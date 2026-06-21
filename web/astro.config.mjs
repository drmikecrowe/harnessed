// @ts-check
import { defineConfig } from "astro/config";

// Project GitHub Pages site → served at /harnessed/
// base is mandatory: every internal URL Astro generates is prefixed with it.
export default defineConfig({
  site: "https://drmikecrowe.github.io",
  base: "/harnessed/",
  trailingSlash: "ignore",
});

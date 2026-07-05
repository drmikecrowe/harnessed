import { glob } from "astro/loaders";
import { defineCollection } from "astro:content";

const docs = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/docs" }),
});

export const collections = { docs };

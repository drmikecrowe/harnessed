export interface NavLink {
  label: string;
  href: string;
}

/** In-page anchor nav */
export const navLinks: NavLink[] = [
  { label: "Modes", href: "#modes" },
  { label: "Harnesses", href: "#harnesses" },
  { label: "How it works", href: "#how" },
  { label: "Security", href: "#security" },
  { label: "Quickstart", href: "#quickstart" },
];

export const repoUrl = "https://github.com/drmikecrowe/harnessed";

export const docsUrls = {
  design:
    "https://github.com/drmikecrowe/harnessed/blob/main/docs/harnessed-design.md",
  recipe:
    "https://github.com/drmikecrowe/harnessed/blob/main/docs/guides/recipe-authoring.md",
  stacks:
    "https://github.com/drmikecrowe/harnessed/blob/main/docs/guides/stacks.md",
  secrets:
    "https://github.com/drmikecrowe/harnessed/blob/main/docs/guides/secrets.md",
  troubleshooting:
    "https://github.com/drmikecrowe/harnessed/blob/main/docs/guides/troubleshooting.md",
};

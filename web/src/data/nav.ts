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
  { label: "Docs", href: "/harnessed/docs" },
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
  awsSso:
    "https://github.com/drmikecrowe/harnessed/blob/main/docs/guides/aws-sso.md",
  egress:
    "https://github.com/drmikecrowe/harnessed/blob/main/docs/guides/egress.md",
  troubleshooting:
    "https://github.com/drmikecrowe/harnessed/blob/main/docs/guides/troubleshooting.md",
};

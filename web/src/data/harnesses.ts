export interface Harness {
  name: string;
  /** card variant → brand-color identity */
  variant:
    | "coral"
    | "magenta"
    | "blue"
    | "purple"
    | "cyan"
    | "blue-deep";
  tagline: string;
  /** claude gets the oversized wordmark treatment */
  hero?: boolean;
}

export const harnesses: Harness[] = [
  {
    name: "claude",
    variant: "coral",
    tagline: "Native. Mounts the profile directly.",
    hero: true,
  },
  {
    name: "opencode",
    variant: "blue",
    tagline: "Reads .claude/skills natively.",
  },
  {
    name: "omp",
    variant: "magenta",
    tagline: "Via claude-hooks-bridge.",
  },
  {
    name: "gemini",
    variant: "purple",
    tagline: "MCP wired to hatago.",
  },
  {
    name: "antigravity",
    variant: "cyan",
    tagline: "MCP wired to hatago.",
  },
  {
    name: "codex",
    variant: "blue-deep",
    tagline: "MCP wired to hatago.",
  },
];

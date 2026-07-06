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
    name: "omp",
    variant: "magenta",
    tagline: "Via claude-hooks-bridge.",
  },
  {
    name: "opencode",
    variant: "blue",
    tagline: "Planned — adapts the .claude profile.",
  },
  {
    name: "antigravity",
    variant: "cyan",
    tagline: "Planned — MCP via hatago.",
  },
  {
    name: "codex",
    variant: "blue-deep",
    tagline: "Planned — MCP via hatago.",
  },
];

export interface SecurityFeature {
  icon: string;
  title: string;
  desc: string;
}

export const securityFeatures: SecurityFeature[] = [
  {
    icon: "package",
    title: "pnpm everywhere",
    desc: "No npm or npx. pnpm dlx replaces npx; minimumReleaseAge cooldowns and lifecycle-script default-deny ship in the base image.",
  },
  {
    icon: "shield-check",
    title: "Build-time scan gate",
    desc: "osv-scanner and pip-audit run always; snyk and Socket.dev when a token is present. Builds fail on high severity.",
  },
  {
    icon: "shield-lock",
    title: "Egress firewall",
    desc: "Per-instance iptables allow-list via NET_ADMIN. The harness reaches only what you permit.",
  },
  {
    icon: "key-off",
    title: "Secrets never baked",
    desc: "Auth, scanner tokens, and 1Password refs reach the instance as env or read-only mounts, never an image layer or repo file.",
  },
  {
    icon: "refresh",
    title: "Nightly re-scan",
    desc: "A systemd user timer re-scans installed images online so a CVE disclosed after build still surfaces.",
  },
  {
    icon: "container",
    title: "One host dependency",
    desc: "Podman or Docker is all you need. Apple container support is a tracked follow-up.",
  },
];

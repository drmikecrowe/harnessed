export interface Stat {
  value: string;
  label: string;
}

export const stats: Stat[] = [
  { value: "3", label: "launchable harnesses" },
  { value: "2", label: "modes" },
  { value: "1", label: "host dependency" },
  { value: "0", label: "secrets baked" },
];

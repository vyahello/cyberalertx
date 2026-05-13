import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Bug,
  Database,
  Eye,
  Fish,
  Lock,
  Network,
  Server,
  Shield,
  ShieldAlert,
  UserX,
  Zap,
} from "lucide-react";
import type { Category } from "./types";

/**
 * Category-driven visual identity for cards and detail pages.
 *
 * Why this exists instead of AI-generated images:
 *   * Zero cost, zero latency — pure SVG via lucide-react.
 *   * Consistent — every phishing post looks like every other phishing
 *     post; AI image gen drifts in style across calls.
 *   * No hallucination risk — no wrong logos, no wrong CVE numbers, no
 *     accidental nudity / brand misuse.
 *   * Future-proof — when we eventually want AI hero images for top
 *     posts (threat_level Critical, say), they layer ON TOP of this
 *     floor; rule-based posts keep the SVG hero, AI posts swap it.
 *
 * `accent` is a color *token name*, not a hex value — the consuming
 * component composes it into the right Tailwind class. We use a small
 * fixed palette so the feed never looks like a clown's pocket.
 */
export type AccentToken =
  | "red"
  | "orange"
  | "amber"
  | "yellow"
  | "purple"
  | "blue"
  | "slate";

export interface CategoryVisual {
  icon: LucideIcon;
  /** Color token. Maps to bg/text/border classes in the components below. */
  accent: AccentToken;
}

const VISUALS: Record<Category, CategoryVisual> = {
  // Consumer-facing scams — amber/orange (warning, not alarm).
  phishing:               { icon: Fish,           accent: "amber"  },
  scam:                   { icon: AlertTriangle,  accent: "orange" },
  "social engineering":   { icon: UserX,          accent: "amber"  },

  // Critical / destructive — red.
  ransomware:             { icon: Lock,           accent: "red"    },
  exploit:                { icon: Zap,            accent: "red"    },
  "zero-day":             { icon: Zap,            accent: "red"    },
  breach:                 { icon: Database,       accent: "red"    },

  // Data exposure — yellow.
  "data leak":            { icon: Database,       accent: "yellow" },

  // Malicious code — orange family.
  malware:                { icon: Bug,            accent: "orange" },
  spyware:                { icon: Eye,            accent: "purple" },

  // Infrastructure — blue/purple.
  botnet:                 { icon: Network,        accent: "purple" },
  vulnerability:          { icon: ShieldAlert,    accent: "yellow" },

  // Catch-all.
  other:                  { icon: Shield,         accent: "slate"  },
};

/**
 * Tailwind class fragments per accent token. Co-located so a designer
 * editing the palette touches one place. Each token has:
 *   bg          — soft background tint behind the icon
 *   fg          — icon stroke color
 *   border      — thin border for the chip
 *   gradientFrom / gradientTo — used by the detail-page hero block
 *
 * Tokens use Tailwind's stock palette by default — they're available
 * without extending tailwind.config. If the design system later swaps
 * to custom tokens, this is the only place to change.
 */
export const ACCENT_CLASSES: Record<
  AccentToken,
  {
    bg: string;
    fg: string;
    border: string;
    gradientFrom: string;
    gradientTo: string;
  }
> = {
  red:    { bg: "bg-red-500/10",    fg: "text-red-400",    border: "border-red-500/30",
            gradientFrom: "from-red-500/20",    gradientTo: "to-red-500/0" },
  orange: { bg: "bg-orange-500/10", fg: "text-orange-400", border: "border-orange-500/30",
            gradientFrom: "from-orange-500/20", gradientTo: "to-orange-500/0" },
  amber:  { bg: "bg-amber-500/10",  fg: "text-amber-400",  border: "border-amber-500/30",
            gradientFrom: "from-amber-500/20",  gradientTo: "to-amber-500/0" },
  yellow: { bg: "bg-yellow-500/10", fg: "text-yellow-400", border: "border-yellow-500/30",
            gradientFrom: "from-yellow-500/20", gradientTo: "to-yellow-500/0" },
  purple: { bg: "bg-purple-500/10", fg: "text-purple-400", border: "border-purple-500/30",
            gradientFrom: "from-purple-500/20", gradientTo: "to-purple-500/0" },
  blue:   { bg: "bg-blue-500/10",   fg: "text-blue-400",   border: "border-blue-500/30",
            gradientFrom: "from-blue-500/20",   gradientTo: "to-blue-500/0" },
  slate:  { bg: "bg-slate-500/10",  fg: "text-slate-400",  border: "border-slate-500/30",
            gradientFrom: "from-slate-500/20",  gradientTo: "to-slate-500/0" },
};

export function visualForCategory(category: Category | string): CategoryVisual {
  return VISUALS[category as Category] ?? VISUALS.other;
}

export function accentClasses(token: AccentToken) {
  return ACCENT_CLASSES[token];
}

// Server icon left in imports for future use (e.g. supply-chain category).
void Server;

import type { Config } from "tailwindcss";

/**
 * CyberAlertX Design Tokens
 *
 * Influences: Linear (graphite + restraint), Stripe (color clarity),
 * Apple (spacing rhythm). Explicitly NOT: terminal green, cyberpunk neon,
 * matrix glow.
 *
 * Naming convention:
 *   - bg.{base|elevated|elevated-2}  — page → card → hover surface
 *   - border.{subtle|strong|focus}   — hierarchy of separators
 *   - text.{primary|secondary|tertiary} — readability rungs
 *   - accent.{DEFAULT|soft}          — the single brand accent (calm blue)
 *   - level.{critical|high|medium|low}.{fg|bg|border} — threat colors
 *   - trust.{trusted|verified|unverified}.{fg|bg}   — credibility colors
 *   - signal.live                    — the "currently active" pulse green
 *
 * All threat / trust colors live below ~50% saturation by design: the
 * product feels alert, not alarmed.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#0A0C10",
          elevated: "#11141B",
          "elevated-2": "#181C25",
          inset: "#070910",
        },
        border: {
          subtle: "#1F242E",
          strong: "#2A303C",
          focus: "#5B8DEF",
        },
        text: {
          primary: "#E8ECF2",
          secondary: "#8B94A4",
          tertiary: "#5A6573",
        },
        accent: {
          DEFAULT: "#5B8DEF",
          soft: "rgba(91, 141, 239, 0.10)",
          ring: "rgba(91, 141, 239, 0.35)",
        },
        level: {
          critical: {
            fg: "#FF6B6E",
            bg: "rgba(229, 72, 77, 0.10)",
            border: "rgba(229, 72, 77, 0.30)",
          },
          high: {
            fg: "#F5A623",
            bg: "rgba(245, 166, 35, 0.10)",
            border: "rgba(245, 166, 35, 0.28)",
          },
          medium: {
            fg: "#ECCB38",
            bg: "rgba(236, 203, 56, 0.08)",
            border: "rgba(236, 203, 56, 0.22)",
          },
          low: {
            fg: "#A0A8B5",
            bg: "rgba(160, 168, 181, 0.06)",
            border: "rgba(160, 168, 181, 0.22)",
          },
        },
        trust: {
          trusted: {
            fg: "#4FCB9C",
            bg: "rgba(79, 203, 156, 0.10)",
          },
          verified: {
            fg: "#7B9CE0",
            bg: "rgba(123, 156, 224, 0.10)",
          },
          unverified: {
            fg: "#8B94A4",
            bg: "rgba(139, 148, 164, 0.08)",
          },
        },
        signal: {
          live: "#4FCB9C",
        },
      },
      fontFamily: {
        // Body & display — single typeface, varies by weight. Inter is the
        // closest open-source equivalent to the Linear/Stripe register.
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      fontSize: {
        // A modest 7-step scale; we don't need a 12-step type ramp on a
        // single-feed product. Numbers picked to play well with 1.5rem
        // baseline spacing.
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.01em" }],
        xs: ["0.75rem", { lineHeight: "1.1rem", letterSpacing: "0.005em" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.9375rem", { lineHeight: "1.5rem" }],
        lg: ["1.0625rem", { lineHeight: "1.6rem" }],
        xl: ["1.25rem", { lineHeight: "1.7rem", letterSpacing: "-0.01em" }],
        "2xl": ["1.5rem", { lineHeight: "1.95rem", letterSpacing: "-0.015em" }],
        "3xl": ["1.875rem", { lineHeight: "2.25rem", letterSpacing: "-0.02em" }],
        "4xl": ["2.375rem", { lineHeight: "2.7rem", letterSpacing: "-0.025em" }],
        "5xl": ["3.25rem", { lineHeight: "3.45rem", letterSpacing: "-0.03em" }],
      },
      borderRadius: {
        // 8pt-grid radii. The product reads modern, not pillowy — caps at lg.
        sm: "4px",
        md: "8px",
        lg: "12px",
        xl: "16px",
      },
      boxShadow: {
        // Soft drop shadows, not "glow" effects.
        card: "0 1px 2px rgba(0, 0, 0, 0.25), 0 1px 1px rgba(0, 0, 0, 0.15)",
        elevated:
          "0 8px 24px -8px rgba(0, 0, 0, 0.5), 0 2px 4px rgba(0, 0, 0, 0.3)",
        "focus-ring": "0 0 0 3px rgba(91, 141, 239, 0.35)",
      },
      animation: {
        // Two motion primitives — both subtle, both purposeful.
        "pulse-live": "pulse-live 2.4s ease-in-out infinite",
        "pulse-ring": "pulse-ring 2.4s ease-out infinite",
        "fade-up": "fade-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) backwards",
        "bg-drift": "bg-drift 20s ease-in-out infinite",
      },
      keyframes: {
        "pulse-live": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
        "pulse-ring": {
          "0%": { transform: "scale(0.85)", opacity: "0.7" },
          "70%": { transform: "scale(2.2)", opacity: "0" },
          "100%": { transform: "scale(2.2)", opacity: "0" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "bg-drift": {
          "0%, 100%": { transform: "translate(0, 0)" },
          "50%": { transform: "translate(-2%, -1%)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;

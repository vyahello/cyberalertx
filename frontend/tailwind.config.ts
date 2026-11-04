import type { Config } from "tailwindcss";

/**
 * CyberAlertX design tokens — "field guide on the axis".
 *
 * Full rationale: docs/design/DESIGN_SYSTEM.md. Short version:
 *
 *   ground  — graphite page and its two tone steps. Surfaces are told apart
 *             by tone, never by outlines or shadows.
 *   ink     — text. Running text is always `ink` (full); `muted` is for
 *             secondary notes; `faint` is the floor for metadata and still
 *             clears 4.5:1 on every ground step.
 *   signal  — the brand cyan. Marks the primary action, links in running
 *             text, focus, and the one whole-field section (footer).
 *   sev     — severity. Always paired with a word and a segment count
 *             (SeverityMark), never carried by colour alone.
 *
 * Every value here has a CSS custom property twin in app/globals.css for
 * contexts Tailwind doesn't reach (SVG, inline styles, third-party widgets).
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ground: {
          DEFAULT: "#0E1116",
          raised: "#161B22",
          high: "#1E242D",
          sunk: "#0A0D11",
        },
        ink: {
          DEFAULT: "#ECEEF1",
          muted: "#A6AEBA",
          faint: "#8C95A3",
        },
        signal: {
          DEFAULT: "#06B6D4",
          hover: "#22D3EE",
          // Text on the cyan field.
          ink: "#071318",
          // Secondary text on the cyan field (5.2:1 on #06B6D4).
          deep: "#0B3A44",
        },
        sev: {
          critical: "#FF5C6C",
          high: "#FF9F43",
          medium: "#EDE58A",
          low: "#8C95A3",
        },
        // Only for real tables and form fields.
        line: "#2A313B",
      },
      fontFamily: {
        // Literata — the reading face: headlines, standfirsts, article text.
        // Optical sizing is on, so the same family is a crisp display face
        // at 44px and a sturdy text face at 17px. Latin + Cyrillic.
        serif: ["var(--font-serif)", "Georgia", "Cambria", "serif"],
        // Fira Sans Condensed — field marks, navigation, controls. Standard
        // Cyrillic forms (Sofia Sans defaulted to Bulgarian letter shapes).
        sans: [
          "var(--font-sans)",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        // The logotype only ("cyberalert" in the header and footer lockup).
        logo: ["var(--font-logo)", "var(--font-sans)", "sans-serif"],
        // Code, commands, hashes and indicators only.
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        // Five steps. Nothing meant to be read goes below `small` (14px).
        small: ["0.875rem", { lineHeight: "1.35rem" }],
        body: ["clamp(1.0625rem, 1rem + 0.2vw, 1.125rem)", { lineHeight: "1.6" }],
        lead: ["clamp(1.1875rem, 1.05rem + 0.4vw, 1.375rem)", { lineHeight: "1.35" }],
        head: [
          "clamp(1.75rem, 1.15rem + 1.9vw, 2.75rem)",
          { lineHeight: "1.12", letterSpacing: "-0.015em" },
        ],
        display: [
          "clamp(3rem, 1.8rem + 4.2vw, 5.5rem)",
          { lineHeight: "0.98", letterSpacing: "-0.03em" },
        ],
      },
      spacing: {
        // Section rhythm: one value for the gap between page sections,
        // clearly larger than any gap inside a section.
        section: "clamp(4.5rem, 3rem + 5vw, 8rem)",
        gutter: "var(--gutter)",
        margin: "var(--margin)",
      },
      maxWidth: {
        page: "90rem",
        measure: "68ch",
      },
      borderRadius: {
        // Square-cornered system; one small radius for focus-ring harmony.
        none: "0",
        sm: "2px",
      },
      keyframes: {
        reveal: {
          from: { clipPath: "inset(0 0 100% 0)", transform: "translateY(0.35em)" },
          to: { clipPath: "inset(0 0 0 0)", transform: "translateY(0)" },
        },
        rise: {
          from: { opacity: "0", transform: "translateY(18px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "sheet-in": {
          from: { transform: "translateY(100%)" },
          to: { transform: "translateY(0)" },
        },
      },
      animation: {
        reveal: "reveal 0.9s cubic-bezier(0.16, 1, 0.3, 1) both",
        rise: "rise 0.7s cubic-bezier(0.16, 1, 0.3, 1) both",
        "sheet-in": "sheet-in 0.32s cubic-bezier(0.16, 1, 0.3, 1) both",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [],
};

export default config;

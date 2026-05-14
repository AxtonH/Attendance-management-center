import type { Config } from "tailwindcss";

// Design tokens mirror the CSS variables in the original mockup so the visual
// language is centralized here instead of scattered across components.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./features/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          page: "#F5F5F4",
          surface: "#FFFFFF",
          muted: "#EFEFED",
          subtle: "#F9F9F8",
          dark: "#0A0A0B",
        },
        text: {
          primary: "#111113",
          secondary: "#5F5F63",
          tertiary: "#8C8C90",
          "on-dark": "#F4F4F5",
          "on-dark-muted": "#A1A1A6",
        },
        border: {
          DEFAULT: "rgba(0,0,0,0.07)",
          strong: "rgba(0,0,0,0.14)",
          "on-dark": "rgba(255,255,255,0.08)",
        },
        accent: {
          DEFAULT: "#4F46E5",
          soft: "rgba(79, 70, 229, 0.1)",
        },
        warning: { bg: "#FEF3C7", text: "#92400E" },
        danger: { bg: "#FEE2E2", text: "#991B1B" },
        severity: {
          high: "#B91C1C",
          med: "#B45309",
          low: "#8C8C90",
        },
        hist: {
          1: "#C7D2FE",
          2: "#A5B4FC",
          3: "#818CF8",
          4: "#4F46E5",
        },
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
      },
      borderRadius: {
        md: "8px",
        lg: "12px",
      },
    },
  },
  plugins: [],
};

export default config;

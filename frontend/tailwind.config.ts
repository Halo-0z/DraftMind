import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        court: {
          black: "rgb(var(--court-black) / <alpha-value>)",
          panel: "rgb(var(--court-panel) / <alpha-value>)",
          line: "rgb(var(--court-line) / <alpha-value>)",
          text: "rgb(var(--court-text) / <alpha-value>)",
          muted: "rgb(var(--court-muted) / <alpha-value>)",
          border: "rgb(var(--court-border) / <alpha-value>)",
          faint: "rgb(var(--court-faint) / <alpha-value>)",
        },
      },
      boxShadow: {
        glow: "var(--court-shadow-glow)",
      },
    },
  },
  plugins: [],
};

export default config;

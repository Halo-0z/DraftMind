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
          black: "#07080a",
          panel: "#111418",
          line: "#d6b35a",
          text: "#f4f1e8",
          muted: "#9da3ad",
        },
      },
      boxShadow: {
        glow: "0 1px 0 rgba(255, 255, 255, 0.06)",
      },
    },
  },
  plugins: [],
};

export default config;

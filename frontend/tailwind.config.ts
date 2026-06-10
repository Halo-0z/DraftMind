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
          black: "#060807",
          panel: "#101410",
          line: "#a3ff24",
          text: "#f7fff2",
          muted: "#9aa79a",
        },
      },
      boxShadow: {
        glow: "0 0 32px rgba(163, 255, 36, 0.28)",
      },
    },
  },
  plugins: [],
};

export default config;

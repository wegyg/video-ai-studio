import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#7c5cff",
          dark: "#5b3fd6",
        },
      },
    },
  },
  plugins: [],
};

export default config;

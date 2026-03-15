import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "#11212D",
        mist: "#E9EEF2",
        sand: "#F5E7D3",
        ember: "#E0712C",
        spruce: "#234C5A",
        cream: "#FFF9F0"
      },
      boxShadow: {
        paper: "0 16px 40px rgba(17, 33, 45, 0.12)"
      },
      borderRadius: {
        xl2: "1.5rem"
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(17,33,45,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(17,33,45,0.06) 1px, transparent 1px)"
      }
    }
  },
  plugins: []
};

export default config;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0f172a",
          soft: "#111827",
          card: "#1e293b",
        },
        accent: {
          DEFAULT: "#38bdf8",
          strong: "#0ea5e9",
        },
      },
    },
  },
  plugins: [],
};

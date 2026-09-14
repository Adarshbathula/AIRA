/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0b1220",
          900: "#101a2e",
          850: "#16233c",
          800: "#1d2c4a",
          700: "#2a3d61",
        },
        brand: {
          50: "#eef4ff",
          100: "#dbe6fe",
          400: "#5b8def",
          500: "#3b70e3",
          600: "#2b5ac4",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

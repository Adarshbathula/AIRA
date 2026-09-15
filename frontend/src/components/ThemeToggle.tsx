import { useState } from "react";
import { preferredTheme, toggleTheme, type Theme } from "../utils/theme";

/** Light/dark switch. Defaults to the dark ("ChatGPT-style") theme. */
export default function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>(() =>
    typeof document !== "undefined" && document.documentElement.classList.contains("dark") ? "dark" : preferredTheme(),
  );

  return (
    <button
      type="button"
      title={`${theme === "dark" ? "Switch to light" : "Switch to dark"} theme`}
      aria-label="Toggle colour theme"
      onClick={() => setTheme(toggleTheme())}
      className={`btn btn-ghost !px-2.5 !py-1.5 text-base leading-none ${className}`}
    >
      <span aria-hidden>{theme === "dark" ? "\u263C" : "\u263E"}</span>
      <span className="hidden text-xs font-medium sm:inline">{theme === "dark" ? "Light" : "Dark"}</span>
    </button>
  );
}

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ThemeProvider, useTheme } from "./ThemeContext";

function ThemeProbe() {
  const { preference, resolvedTheme, setPreference } = useTheme();
  return <><output>{preference}:{resolvedTheme}</output><button onClick={() => setPreference("dark")}>Use dark</button></>;
}

describe("ThemeProvider", () => {
  it("supports system preference and persists only the selected theme", async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    expect(screen.getByText("system:light")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use dark" }));
    expect(screen.getByText("dark:dark")).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("budget-theme")).toBe("dark");
    expect(localStorage.length).toBe(1);
  });
});

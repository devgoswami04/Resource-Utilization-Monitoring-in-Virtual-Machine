import { useEffect, useState } from "react";
import LandingPage from "./components/LandingPage";
import Dashboard from "./components/Dashboard";
import "./App.css";


const PAGE_KEY = "aegis-page";
const THEME_KEY = "aegis-theme";


export default function App() {
  const [page, setPage] = useState(() => window.localStorage.getItem(PAGE_KEY) ?? "landing");
  const [theme, setTheme] = useState(() => window.localStorage.getItem(THEME_KEY) ?? "dark");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    window.localStorage.setItem(PAGE_KEY, page);
  }, [page]);

  return (
    <div className="app-shell">
      {page === "landing" ? (
        <LandingPage onEnter={() => setPage("dashboard")} />
      ) : (
        <Dashboard
          theme={theme}
          onBack={() => setPage("landing")}
          onToggleTheme={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
        />
      )}
    </div>
  );
}

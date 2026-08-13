import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "./Brand";
import { Icon, type IconName } from "./Icon";
import { useState } from "react";
import { ApiError } from "../api/client";

const navigation: Array<{ to: string; label: string; icon: IconName }> = [
  { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { to: "/accounts", label: "Accounts", icon: "accounts" },
  { to: "/transactions", label: "Transactions", icon: "transactions" },
  { to: "/budget", label: "Budget", icon: "wallet" },
  { to: "/plan", label: "Plan", icon: "target" },
  { to: "/recurring", label: "Recurring", icon: "repeat" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

function NavItems() {
  return navigation.map((item) => (
    <NavLink key={item.to} to={item.to} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
      <Icon name={item.icon} />
      <span>{item.label}</span>
    </NavLink>
  ));
}

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [logoutBusy, setLogoutBusy] = useState(false);

  const signOut = async () => {
    setLogoutBusy(true);
    setLogoutError(null);
    try {
      await logout();
      navigate("/login", { replace: true, state: { from: location.pathname } });
    } catch (error) {
      setLogoutError(error instanceof ApiError ? error.message : "Sign out could not be completed. Please try again.");
    } finally {
      setLogoutBusy(false);
    }
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar">
        <Brand />
        <nav className="primary-nav" aria-label="Primary navigation"><NavItems /></nav>
        <div className="sidebar-user">
          <div className="user-avatar" aria-hidden="true">{user?.username.slice(0, 1).toUpperCase()}</div>
          <div className="user-summary"><strong>{user?.username}</strong><span>{user?.email}</span></div>
          <button type="button" className="icon-button" disabled={logoutBusy} onClick={() => void signOut()} aria-label="Sign out"><Icon name="logout" /></button>
        </div>
      </aside>
      <header className="mobile-topbar">
        <Brand />
        <button type="button" className="icon-button" disabled={logoutBusy} onClick={() => void signOut()} aria-label="Sign out"><Icon name="logout" /></button>
      </header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        {logoutError && <div className="logout-alert" role="alert"><span>{logoutError}</span><button type="button" onClick={() => void signOut()}>Try again</button></div>}
        <Outlet />
      </main>
      <nav className="mobile-nav" aria-label="Primary navigation"><NavItems /></nav>
    </div>
  );
}

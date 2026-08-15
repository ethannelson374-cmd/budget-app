import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "./Brand";
import { Icon, type IconName } from "./Icon";
import { useState } from "react";
import { ApiError, apiRequest } from "../api/client";
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../api/queries";
import type { NotificationCount } from "../api/types";

const navigation: Array<{ to: string; label: string; icon: IconName }> = [
  { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { to: "/accounts", label: "Accounts", icon: "accounts" },
  { to: "/transactions", label: "Transactions", icon: "transactions" },
  { to: "/budget", label: "Budget", icon: "wallet" },
  { to: "/plan", label: "Plan", icon: "target" },
  { to: "/recurring", label: "Recurring", icon: "repeat" },
  { to: "/insights", label: "Insights", icon: "sparkles" },
  { to: "/advisor", label: "Advisor", icon: "message" },
  { to: "/reports", label: "Reports", icon: "reports" },
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
  const notificationCount = useQuery({ queryKey: queryKeys.notificationCount, queryFn: () => apiRequest<NotificationCount>("/notifications/unread-count"), refetchInterval: 60_000, enabled: Boolean(user) });
  const unread = notificationCount.data?.unread_count ?? 0;

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
          <NavLink className="notification-bell" to="/notifications" aria-label={unread ? `${unread} unread notifications` : "Notifications"}><Icon name="bell" />{unread > 0 && <span>{unread > 99 ? "99+" : unread}</span>}</NavLink>
          <div className="user-avatar" aria-hidden="true">{user?.username.slice(0, 1).toUpperCase()}</div>
          <div className="user-summary"><strong>{user?.username}</strong><span>{user?.email}</span></div>
          <button type="button" className="icon-button" disabled={logoutBusy} onClick={() => void signOut()} aria-label="Sign out"><Icon name="logout" /></button>
        </div>
      </aside>
      <header className="mobile-topbar">
        <Brand />
        <div className="mobile-topbar-actions"><NavLink className="notification-bell" to="/notifications" aria-label={unread ? `${unread} unread notifications` : "Notifications"}><Icon name="bell" />{unread > 0 && <span>{unread > 99 ? "99+" : unread}</span>}</NavLink><button type="button" className="icon-button" disabled={logoutBusy} onClick={() => void signOut()} aria-label="Sign out"><Icon name="logout" /></button></div>
      </header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        {logoutError && <div className="logout-alert" role="alert"><span>{logoutError}</span><button type="button" onClick={() => void signOut()}>Try again</button></div>}
        <Outlet />
      </main>
      <nav className="mobile-nav" aria-label="Primary navigation"><NavItems /></nav>
    </div>
  );
}

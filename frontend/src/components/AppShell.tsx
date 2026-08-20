import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiRequest, ApiError } from "../api/client";
import { queryKeys } from "../api/queries";
import type { NotificationCount } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "./Brand";
import { Icon, type IconName } from "./Icon";

const navigation: Array<{ to: string; label: string; icon: IconName }> = [
  { to: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { to: "/accounts", label: "Accounts", icon: "accounts" },
  { to: "/transactions", label: "Transactions", icon: "transactions" },
  { to: "/plan", label: "Plan", icon: "target" },
  { to: "/calendar", label: "Calendar", icon: "calendar" },
  { to: "/analytics", label: "Analytics", icon: "trends" },
  { to: "/advisor", label: "Advisor", icon: "message" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

const NAV_SNAP_WIDTHS = [78, 164, 252] as const;
const NAV_STORAGE_KEY = "budget-liquid-nav-width";

type NavMode = "compact" | "peek" | "full";

function clampNavWidth(width: number): number {
  return Math.max(NAV_SNAP_WIDTHS[0], Math.min(NAV_SNAP_WIDTHS[NAV_SNAP_WIDTHS.length - 1], width));
}

function nearestNavWidth(width: number): number {
  return NAV_SNAP_WIDTHS.reduce((nearest, candidate) =>
    Math.abs(candidate - width) < Math.abs(nearest - width) ? candidate : nearest,
  );
}

function navMode(width: number): NavMode {
  if (width < 122) return "compact";
  if (width < 210) return "peek";
  return "full";
}

function readNavWidth(): number {
  const stored = Number(localStorage.getItem(NAV_STORAGE_KEY));
  return Number.isFinite(stored) && stored >= NAV_SNAP_WIDTHS[0] && stored <= NAV_SNAP_WIDTHS[2]
    ? nearestNavWidth(stored)
    : NAV_SNAP_WIDTHS[0];
}

function NavItems({ onNavigate }: { onNavigate?: () => void } = {}) {
  return navigation.map((item) => (
    <NavLink
      key={item.to}
      to={item.to}
      title={item.label}
      data-label={item.label}
      className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
      onClick={onNavigate}
    >
      <span className="nav-icon" aria-hidden="true"><Icon name={item.icon} /></span>
      <span className="nav-label">{item.label}</span>
    </NavLink>
  ));
}

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [navWidth, setNavWidth] = useState(readNavWidth);
  const [resizingNav, setResizingNav] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const mobileMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const mobileDrawerRef = useRef<HTMLElement | null>(null);
  const liveNavWidth = useRef(navWidth);
  const dragStart = useRef<{ x: number; width: number } | null>(null);
  const notificationCount = useQuery({ queryKey: queryKeys.notificationCount, queryFn: () => apiRequest<NotificationCount>("/notifications/unread-count"), refetchInterval: 60_000, enabled: Boolean(user) });
  const unread = notificationCount.data?.unread_count ?? 0;
  const mode = navMode(navWidth);

  useEffect(() => {
    document.documentElement.style.setProperty("--sidebar-width", `${navWidth}px`);
    return () => {
      document.documentElement.style.removeProperty("--sidebar-width");
    };
  }, [navWidth]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => {
      mobileDrawerRef.current?.querySelector<HTMLAnchorElement>("a.nav-link")?.focus();
    }, 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMobileNavOpen(false);
      window.setTimeout(() => mobileMenuButtonRef.current?.focus(), 0);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [mobileNavOpen]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  const closeMobileNavigation = (restoreFocus = false) => {
    setMobileNavOpen(false);
    if (restoreFocus) window.setTimeout(() => mobileMenuButtonRef.current?.focus(), 0);
  };

  const commitNavWidth = (width: number) => {
    const next = nearestNavWidth(width);
    liveNavWidth.current = next;
    setNavWidth(next);
    localStorage.setItem(NAV_STORAGE_KEY, String(next));
  };

  const moveNavBySnap = (delta: number) => {
    const snapped = nearestNavWidth(navWidth);
    const index = NAV_SNAP_WIDTHS.findIndex((width) => width === snapped);
    const nextIndex = Math.max(0, Math.min(NAV_SNAP_WIDTHS.length - 1, index + delta));
    commitNavWidth(NAV_SNAP_WIDTHS[nextIndex]);
  };

  const beginNavResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStart.current = { x: event.clientX, width: navWidth };
    setResizingNav(true);
  };

  const resizeNav = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragStart.current) return;
    const next = clampNavWidth(dragStart.current.width + event.clientX - dragStart.current.x);
    liveNavWidth.current = next;
    setNavWidth(next);
  };

  const endNavResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragStart.current) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    dragStart.current = null;
    setResizingNav(false);
    commitNavWidth(liveNavWidth.current);
  };

  const navKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowRight") {
      event.preventDefault();
      moveNavBySnap(1);
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveNavBySnap(-1);
    }
    if (event.key === "Home") {
      event.preventDefault();
      commitNavWidth(NAV_SNAP_WIDTHS[0]);
    }
    if (event.key === "End") {
      event.preventDefault();
      commitNavWidth(NAV_SNAP_WIDTHS[2]);
    }
  };

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

  const shellStyle = { "--sidebar-width": `${navWidth}px` } as CSSProperties;

  return (
    <div className={`app-shell liquid-shell${resizingNav ? " nav-resizing" : ""}`} style={shellStyle} data-nav-mode={mode}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar liquid-sidebar" data-mode={mode} aria-label="Budget navigation rail">
        <Brand />
        <nav className="primary-nav" aria-label="Primary navigation"><NavItems /></nav>
        <div className="sidebar-user">
          <NavLink className="notification-bell" to="/notifications" aria-label={unread ? `${unread} unread notifications` : "Notifications"}><Icon name="bell" />{unread > 0 && <span>{unread > 99 ? "99+" : unread}</span>}</NavLink>
          <div className="user-avatar" aria-hidden="true">{user?.username.slice(0, 1).toUpperCase()}</div>
          <div className="user-summary"><strong>{user?.username}</strong><span>{user?.email}</span></div>
          <button type="button" className="icon-button" disabled={logoutBusy} onClick={() => void signOut()} aria-label="Sign out"><Icon name="logout" /></button>
        </div>
        <div
          className="sidebar-resizer"
          role="separator"
          tabIndex={0}
          aria-label="Resize navigation"
          aria-orientation="vertical"
          aria-valuemin={NAV_SNAP_WIDTHS[0]}
          aria-valuemax={NAV_SNAP_WIDTHS[2]}
          aria-valuenow={Math.round(navWidth)}
          aria-valuetext={mode === "compact" ? "Icons only" : mode === "peek" ? "Compact labels" : "Full navigation"}
          title="Drag to expand navigation"
          onPointerDown={beginNavResize}
          onPointerMove={resizeNav}
          onPointerUp={endNavResize}
          onPointerCancel={endNavResize}
          onDoubleClick={() => commitNavWidth(mode === "full" ? NAV_SNAP_WIDTHS[0] : NAV_SNAP_WIDTHS[2])}
          onKeyDown={navKeyDown}
        ><span aria-hidden="true" /></div>
      </aside>
      <header className="mobile-topbar">
        <button
          ref={mobileMenuButtonRef}
          type="button"
          className="mobile-menu-button"
          aria-label="Open navigation"
          aria-expanded={mobileNavOpen}
          aria-controls="mobile-navigation-drawer"
          onClick={() => setMobileNavOpen(true)}
        ><span className="mobile-menu-glyph" aria-hidden="true"><i /><i /><i /></span></button>
        <Brand />
        <div className="mobile-topbar-actions"><NavLink className="notification-bell" to="/notifications" aria-label={unread ? `${unread} unread notifications` : "Notifications"}><Icon name="bell" />{unread > 0 && <span>{unread > 99 ? "99+" : unread}</span>}</NavLink><button type="button" className="icon-button" disabled={logoutBusy} onClick={() => void signOut()} aria-label="Sign out"><Icon name="logout" /></button></div>
      </header>
      <div className={`mobile-nav-layer${mobileNavOpen ? " open" : ""}`} aria-hidden={!mobileNavOpen}>
        <button type="button" className="mobile-nav-scrim" aria-label="Close navigation" onClick={() => closeMobileNavigation(true)} />
        <aside ref={mobileDrawerRef} id="mobile-navigation-drawer" className="mobile-nav-drawer" aria-label="Mobile navigation menu">
          <div className="mobile-drawer-header">
            <Brand />
            <button type="button" className="mobile-drawer-close" aria-label="Close navigation" onClick={() => closeMobileNavigation(true)}>×</button>
          </div>
          <nav className="mobile-drawer-nav primary-nav" aria-label="Primary navigation"><NavItems onNavigate={() => closeMobileNavigation()} /></nav>
          <div className="mobile-drawer-user">
            <div className="user-avatar" aria-hidden="true">{user?.username.slice(0, 1).toUpperCase()}</div>
            <div className="user-summary"><strong>{user?.username}</strong><span>{user?.email}</span></div>
            <button type="button" className="icon-button" disabled={logoutBusy} onClick={() => void signOut()} aria-label="Sign out"><Icon name="logout" /></button>
          </div>
        </aside>
      </div>
      <main id="main-content" className="main-content" tabIndex={-1}>
        {logoutError && <div className="logout-alert" role="alert"><span>{logoutError}</span><button type="button" onClick={() => void signOut()}>Try again</button></div>}
        <Outlet />
      </main>
    </div>
  );
}

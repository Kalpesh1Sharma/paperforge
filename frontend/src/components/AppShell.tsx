import { useState, type ReactNode } from "react";
import { Brand } from "./Brand";
import { FileIcon, FolderIcon, GridIcon, MenuIcon, PlusIcon, TemplateIcon } from "./Icons";

type Props = {
  children: ReactNode;
  current: "dashboard" | "projects" | "new" | "report" | "processing";
  connection: "checking" | "connected" | "unavailable";
  onNavigate: (path: string) => void;
};

export function AppShell({ children, current, connection, onNavigate }: Props) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const navigate = (path: string) => { setMobileOpen(false); setProfileOpen(false); onNavigate(path); };
  return (
    <div className="product-shell">
      {mobileOpen && <button className="mobile-backdrop" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
      <aside className={`app-sidebar ${mobileOpen ? "open" : ""}`}>
        <button className="sidebar-brand" onClick={() => navigate("/")}><Brand compact /></button>
        <nav aria-label="Workspace navigation">
          <button className={current === "dashboard" ? "active" : ""} onClick={() => navigate("/app")}><GridIcon />Overview</button>
          <button className={current === "new" ? "active" : ""} onClick={() => navigate("/app/new")}><PlusIcon />New report</button>
          <button className={current === "projects" ? "active" : ""} onClick={() => navigate("/app/projects")}><FolderIcon />Projects</button>
          <button disabled><TemplateIcon />Templates<span className="soon">Soon</span></button>
        </nav>
        <div className="sidebar-bottom">
          <div className={`backend-state backend-state--${connection}`}><i /><span><b>{connection === "connected" ? "Connected" : connection === "checking" ? "Connecting" : "Backend offline"}</b><small>{connection === "unavailable" ? "Check local service" : "Private workspace"}</small></span></div>
          {profileOpen && <div className="profile-menu" role="menu" aria-label="Workspace actions"><div><strong>Kalpesh Sharma</strong><small>Personal workspace</small></div><button role="menuitem" onClick={() => navigate("/app/new")}><PlusIcon />Create new report</button><button role="menuitem" onClick={() => navigate("/")}><FileIcon />PaperForge home</button></div>}
          <button className="profile-button" type="button" aria-label="Kalpesh Personal workspace" aria-haspopup="menu" aria-expanded={profileOpen} onClick={() => setProfileOpen((open) => !open)}><span>KS</span><span><b>Kalpesh</b><small>Personal workspace</small></span><MenuIcon /></button>
        </div>
      </aside>
      <div className="app-content">
        <header className="mobile-header"><button aria-label="Open navigation" aria-expanded={mobileOpen} onClick={() => setMobileOpen(true)}><MenuIcon /></button><Brand compact /><span /></header>
        {children}
      </div>
    </div>
  );
}

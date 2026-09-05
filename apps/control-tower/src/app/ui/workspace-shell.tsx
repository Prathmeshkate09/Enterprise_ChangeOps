import Link from "next/link";
import type { ReactNode } from "react";

import { logout } from "@/app/access-actions";

export function WorkspaceShell({
  title,
  subtitle,
  links,
  children,
}: {
  title: string;
  subtitle: string;
  links: { href: string; label: string }[];
  children: ReactNode;
}) {
  return (
    <div className="access-root workspace-shell">
      <a href="#workspace-main" className="access-skip">
        Skip to content
      </a>
      <aside className="workspace-sidebar">
        <Link href="/access-status" className="workspace-brand">
          <span className="workspace-mark">C</span>
          <span>
            ChangeOps<small>Enterprise operations</small>
          </span>
        </Link>
        <div className="workspace-context">
          <small>{subtitle}</small>
          <strong>{title}</strong>
        </div>
        <nav aria-label={`${subtitle} navigation`}>
          {links.map((link) => (
            <Link key={link.href} href={link.href}>
              {link.label}
              <span aria-hidden="true">↗</span>
            </Link>
          ))}
        </nav>
        <div className="workspace-sidebar-bottom">
          <span className="access-pill">Invitation only</span>
          <Link href="/access-status">Switch workspace</Link>
          <form action={logout}>
            <button className="access-text-button">Sign out</button>
          </form>
        </div>
      </aside>
      <div className="workspace-content">
        <header className="workspace-topbar">
          <span>
            {subtitle} <span aria-hidden="true">/</span> {title}
          </span>
          <span className="workspace-status">
            <i />
            Access controlled
          </span>
        </header>
        <main id="workspace-main" className="workspace-main">
          {children}
        </main>
      </div>
    </div>
  );
}

export function PageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="access-heading">
      <p className="access-eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  );
}

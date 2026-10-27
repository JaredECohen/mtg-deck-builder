import Link from "next/link";

import { AuthNav } from "@/components/auth-nav";

export function SiteHeader() {
  return (
    <header className="site-header">
      <nav className="site-header-nav" aria-label="Main">
        <Link href="/" className="site-header-brand">
          MTG Deck Lab
        </Link>
        <div className="site-header-links">
          <Link href="/#builder">Deck Builder</Link>
          <Link href="/library">Library</Link>
          <Link href="/blog">Guides</Link>
          <Link href="/about">About</Link>
          <AuthNav />
        </div>
      </nav>
    </header>
  );
}

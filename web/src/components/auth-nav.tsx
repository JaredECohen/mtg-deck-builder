"use client";

import Link from "next/link";

import { useAccount } from "@/hooks/use-account";

export function AuthNav() {
  const account = useAccount();
  if (account.status === "in") {
    return (
      <form action="/api/auth/logout" method="post" className="auth-nav">
        <span className="site-header-email">{account.email}</span>
        <button type="submit" className="site-header-text-button">Sign out</button>
      </form>
    );
  }
  return <Link href="/signin">Sign in</Link>;
}

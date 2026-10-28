import type { Metadata } from "next";
import Link from "next/link";

import { SignInForm } from "@/components/sign-in-form";

export const metadata: Metadata = {
  title: "Sign in | MTG Deck Lab",
  description: "Optional sign-in for a personal deck library. The deck builder still works without an account.",
  robots: { index: false, follow: false },
  alternates: { canonical: "/signin" }
};

export default async function SignInPage({
  searchParams
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  return (
    <main className="shell legal-page">
      <h1>Sign in</h1>
      <p>
        An account is optional. You can keep building and sharing decks without one. Sign in to save decks to a
        library you can reopen, rename, and delete from any browser.
      </p>
      <p className="muted">We email you a one-time link. There is no password.</p>
      <SignInForm notice={error === "invalid" ? "invalid" : error === "expired" ? "expired" : null} />
      <p>
        <Link href="/">Back to the Deck Lab</Link>
      </p>
    </main>
  );
}

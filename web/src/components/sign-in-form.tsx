"use client";

import { useState, type FormEvent } from "react";

type Props = { invalidLink: boolean };

export function SignInForm({ invalidLink }: Props) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");
  const [debugUrl, setDebugUrl] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus("sending");
    setMessage("");
    setDebugUrl(null);
    try {
      const response = await fetch("/api/auth/magic-link", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email })
      });
      const body = (await response.json().catch(() => null)) as { detail?: string; debug_url?: string } | null;
      if (!response.ok) {
        setStatus("error");
        setMessage(body?.detail ?? "Could not send the sign-in link.");
        return;
      }
      setStatus("sent");
      setMessage("Check your email for a sign-in link. It expires in 20 minutes.");
      if (typeof body?.debug_url === "string") setDebugUrl(body.debug_url);
    } catch {
      setStatus("error");
      setMessage("Could not send the sign-in link.");
    }
  }

  return (
    <form className="sign-in-form" onSubmit={(event) => void onSubmit(event)}>
      {invalidLink ? (
        <p className="workflow-error" role="alert">That sign-in link is invalid or has expired. Request a new one.</p>
      ) : null}
      <label className="label" htmlFor="sign-in-email">Email</label>
      <input
        id="sign-in-email"
        className="input"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="you@example.com"
      />
      <button type="submit" className="button button-compact" disabled={status === "sending"}>
        {status === "sending" ? "Sending…" : "Email me a sign-in link"}
      </button>
      {message ? <p className={status === "error" ? "workflow-error" : "muted"} role="status">{message}</p> : null}
      {debugUrl ? (
        <p className="muted">
          Development only: <a href={debugUrl}>open the sign-in link</a>
        </p>
      ) : null}
    </form>
  );
}

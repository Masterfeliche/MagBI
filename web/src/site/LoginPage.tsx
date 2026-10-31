/** Sign in to MagBI. On success it opens the page the user came from, or their workspaces. */

import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { SignInError, signIn } from "../shared/session";
import { Logo } from "./Logo";
import "./site.css";

const STEPS = ["Connect", "Model", "Design", "Check", "Embed"];

/** Only same-site paths, so a crafted link cannot send a user elsewhere after sign-in. */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/workspaces";
  return next;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; detail: string; credentials: boolean } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError({ title: "Enter your email and password.", detail: "Both are needed to sign in.", credentials: false });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password, remember);
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (reason) {
      const wrong = reason instanceof SignInError && reason.wrongCredentials;
      setError(
        wrong
          ? { title: "That email and password don't match.", detail: "Check both and try again.", credentials: true }
          : { title: "MagBI could not sign you in.", detail: reason instanceof Error ? reason.message : "Try again in a moment.", credentials: false },
      );
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin">
      <aside className="signin-brand">
        <Link to="/" className="site-brand" aria-label="MagBI home">
          <Logo size={40} />
          <span>MagBI</span>
        </Link>
        <div className="signin-pitch">
          <div className="site-eyebrow site-eyebrow-warm">Business intelligence platform</div>
          <h1>Business intelligence, built into your product.</h1>
          <p>Sign in to build, check and publish dashboards on your own data.</p>
          <ol className="signin-steps" aria-label="How MagBI works">
            {STEPS.map((step) => (
              <li key={step} className={step === "Check" ? "on" : undefined}>{step}</li>
            ))}
          </ol>
        </div>
        <div className="signin-note">Need an account? Ask your MagBI administrator.</div>
      </aside>

      <main className="signin-main">
        <form className="signin-form" aria-labelledby="signin-title" onSubmit={submit} noValidate>
          <div>
            <h2 id="signin-title">Sign in</h2>
            <p className="signin-lede">Use the email your MagBI administrator registered for you.</p>
          </div>

          {error && (
            <div id="signin-error" className="signin-alert" role="alert">
              <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" style={{ flex: "0 0 auto", marginTop: 1 }}>
                <circle cx="12" cy="12" r="9.5" fill="none" stroke="#9A4442" strokeWidth="2" />
                <path d="M12 7v6" stroke="#9A4442" strokeWidth="2" strokeLinecap="round" />
                <circle cx="12" cy="16.5" r="1.2" fill="#9A4442" />
              </svg>
              <span><b>{error.title}</b>{error.detail}</span>
            </div>
          )}

          <div className="signin-field">
            <label htmlFor="signin-email">Email</label>
            <input
              id="signin-email"
              className="signin-input"
              type="email"
              autoComplete="username"
              placeholder="name@company.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-describedby={error ? "signin-error" : undefined}
            />
          </div>

          <div className="signin-field">
            <label htmlFor="signin-password">Password</label>
            <div className={error?.credentials ? "signin-pass invalid" : "signin-pass"}>
              <input
                id="signin-password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-invalid={error?.credentials ? true : undefined}
                aria-describedby={error ? "signin-error" : undefined}
              />
              <button type="button" onClick={() => setShowPassword((shown) => !shown)} aria-pressed={showPassword}>
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
          </div>

          <label className="signin-remember" htmlFor="signin-remember">
            <input id="signin-remember" type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
            Keep me signed in on this computer
          </label>

          <button type="submit" className="signin-submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>

          <p className="signin-help">Forgot your password? Ask your MagBI administrator to reset it.</p>
        </form>
      </main>
    </div>
  );
}

import { ArrowLeft, LockKeyhole, ShieldCheck, UserPlus } from "lucide-react";
import { useState } from "react";
import { api, setTokens } from "../lib/api.js";

export default function Login({ initialMode = "signin", onBack, onLogin }) {
  const [mode, setMode] = useState(initialMode || "signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const isSignup = mode === "signup";

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (isSignup && password !== confirmPassword) {
        throw new Error("Passwords do not match");
      }
      if (isSignup && password.length < 8) {
        throw new Error("Password must be at least 8 characters");
      }
      const result = await api(isSignup ? "/auth/signup" : "/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, remember_me: rememberMe }),
      });
      setTokens(result.access_token, result.refresh_token);
      onLogin(result.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="loginScreen">
      <form className="loginPanel" onSubmit={submit}>
        <button className="backToLanding" type="button" onClick={onBack}>
          <ArrowLeft size={16} />
          Back
        </button>
        <div className="loginHead">
          <div className="brandMark">
            <ShieldCheck size={26} />
          </div>
          <div>
            <h1>Government Tender Intelligence Platform</h1>
            <p>{isSignup ? "Create an account to monitor live tenders." : "Sign in to your tender operations workspace."}</p>
          </div>
        </div>
        <div className="authSwitch" role="tablist" aria-label="Authentication mode">
          <button type="button" className={!isSignup ? "active" : ""} onClick={() => setMode("signin")}>
            <LockKeyhole size={16} />
            Sign in
          </button>
          <button type="button" className={isSignup ? "active" : ""} onClick={() => setMode("signup")}>
            <UserPlus size={16} />
            Sign up
          </button>
        </div>
        <label>
          Email
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" required />
        </label>
        <label>
          Password
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete={isSignup ? "new-password" : "current-password"}
            minLength={isSignup ? 8 : undefined}
            required
          />
        </label>
        {isSignup && (
          <label>
            Confirm password
            <input
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
            />
          </label>
        )}
        {!isSignup && (
          <label className="rememberToggle">
            <input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} />
            <span>
              <strong>Remember this device</strong>
              <em>Keep this session active with secure refresh tokens.</em>
            </span>
          </label>
        )}
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={loading}>
          {loading ? (isSignup ? "Creating account..." : "Signing in...") : isSignup ? "Create account" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

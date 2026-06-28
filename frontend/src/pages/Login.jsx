import { ArrowLeft, DatabaseZap, LockKeyhole, ShieldCheck, UserPlus, CheckCircle2, Eye, EyeOff } from "lucide-react";
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
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
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
    <main className="authPage">
      {/* Nav matching Landing page */}
      <nav className="landingNav authNav" aria-label="Auth navigation">
        <div className="landingBrand" style={{ cursor: "pointer" }} onClick={onBack}>
          <DatabaseZap size={24} />
          <span>Tender Intel</span>
        </div>
        <div className="landingNavActions">
          <button className="btn-outline authBackBtn" type="button" onClick={onBack}>
            <ArrowLeft size={16} />
            Back to Home
          </button>
        </div>
      </nav>

      {/* Auth card */}
      <div className="authWrapper">
        <div className="authCard">
          {/* Header */}
          <div className="authCardHead">
            <div className="authBrandMark">
              <ShieldCheck size={22} />
            </div>
            <div>
              <h1 className="authTitle">Government Tender Intelligence</h1>
              <p className="authSubtitle">
                {isSignup
                  ? "Create your account to monitor live tenders."
                  : "Sign in to your secure procurement workspace."}
              </p>
            </div>
          </div>

          {/* Tab switch */}
          <div className="authTabs" role="tablist" aria-label="Authentication mode">
            <button
              type="button"
              role="tab"
              aria-selected={!isSignup}
              className={`authTab ${!isSignup ? "active" : ""}`}
              onClick={() => setMode("signin")}
            >
              <LockKeyhole size={15} />
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={isSignup}
              className={`authTab ${isSignup ? "active" : ""}`}
              onClick={() => setMode("signup")}
            >
              <UserPlus size={15} />
              Sign up
            </button>
          </div>

          {/* Form */}
          <form className="authForm" onSubmit={submit}>
            <div className="authField">
              <label htmlFor="auth-email" className="authLabel">Email address</label>
              <input
                id="auth-email"
                className="authInput"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                type="email"
                autoComplete="email"
                placeholder="you@organisation.com"
                required
              />
            </div>

            <div className="authField">
              <label htmlFor="auth-password" className="authLabel">Password</label>
              <div className="authInputWrap">
                <input
                  id="auth-password"
                  className="authInput"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  type={showPassword ? "text" : "password"}
                  autoComplete={isSignup ? "new-password" : "current-password"}
                  minLength={isSignup ? 8 : undefined}
                  placeholder={isSignup ? "Min. 8 characters" : "Your password"}
                  required
                />
                <button
                  type="button"
                  className="authEyeBtn"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {isSignup && (
              <div className="authField">
                <label htmlFor="auth-confirm" className="authLabel">Confirm password</label>
                <div className="authInputWrap">
                  <input
                    id="auth-confirm"
                    className="authInput"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    type={showConfirm ? "text" : "password"}
                    autoComplete="new-password"
                    minLength={8}
                    placeholder="Repeat your password"
                    required
                  />
                  <button
                    type="button"
                    className="authEyeBtn"
                    onClick={() => setShowConfirm((v) => !v)}
                    aria-label={showConfirm ? "Hide" : "Show"}
                  >
                    {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            )}

            {!isSignup && (
              <label className="authRemember">
                <input
                  type="checkbox"
                  className="authCheckbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                />
                <span>
                  <strong>Remember this device</strong>
                  <em>Keep session active with secure refresh tokens.</em>
                </span>
              </label>
            )}

            {error && (
              <div className="authError" role="alert">
                {error}
              </div>
            )}

            <button
              type="submit"
              className="authSubmitBtn"
              disabled={loading}
            >
              {loading
                ? isSignup ? "Creating account…" : "Signing in…"
                : isSignup ? "Create account" : "Sign in"}
            </button>
          </form>

          {/* Trust signals */}
          <div className="authTrust">
            <span><CheckCircle2 size={14} /> JWT secured sessions</span>
            <span><CheckCircle2 size={14} /> 23 government portals</span>
            <span><CheckCircle2 size={14} /> Live tender data</span>
          </div>
        </div>
      </div>
    </main>
  );
}

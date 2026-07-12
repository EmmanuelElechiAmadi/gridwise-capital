"use client";

import { useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff, Loader2, TrendingUp, Shield, Zap } from "lucide-react";

interface AuthFormProps {
  mode: "login" | "signup";
}

export default function AuthForm({ mode }: AuthFormProps) {
  const { login, register } = useAuth();
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
    investorType: "individual",
    acceptTerms: false,
  });

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    if (mode === "signup") {
      const result = await register(formData.name, formData.email, formData.password);
      setIsLoading(false);
      if (result.success) {
        router.push("/dashboard");
      } else {
        setError(result.error || "Registration failed.");
      }
      return;
    }
    const result = await login(formData.email, formData.password);
    setIsLoading(false);
    if (result.success) {
      if (formData.email.toLowerCase() === "admin@seekquant.com") {
        router.push("/admin");
      } else {
        router.push("/dashboard");
      }
    } else {
      setError(result.error || "Login failed.");
    }
  };

  const updateField = (field: string, value: string | boolean) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)" }}>
      {/* Left panel */}
      <div
        style={{
          flex: "0 0 420px",
          background: "var(--surface)",
          borderRight: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "48px 40px",
        }}
      >
        {/* Logo */}
        <div>
          <Link href="/" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none", marginBottom: 64 }}>
            <div style={{ width: 36, height: 36, borderRadius: 10, background: "linear-gradient(135deg, #e8c97a, #c9a84c)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span style={{ color: "#000", fontWeight: 900, fontSize: 13 }}>SQ</span>
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 15, color: "var(--text)" }}>Seek Quant</div>
              <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Capital Management</div>
            </div>
          </Link>

          <h2 style={{ fontSize: 28, fontWeight: 800, color: "var(--text)", letterSpacing: "-0.02em", lineHeight: 1.2, marginBottom: 16 }}>
            Precision trading,<br />
            <span style={{ background: "linear-gradient(135deg, #e8c97a, #c9a84c)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
              data-driven alpha.
            </span>
          </h2>
          <p style={{ fontSize: 14, color: "var(--text-muted)", lineHeight: 1.7 }}>
            Join institutional investors who trust Seek Quant for consistent, risk-adjusted returns.
          </p>

          {/* Stats */}
          <div style={{ marginTop: 40, display: "flex", flexDirection: "column", gap: 16 }}>
            {[
              { icon: TrendingUp, label: "YTD Return", value: "+34.2%" },
              { icon: Shield, label: "Sharpe Ratio", value: "2.41" },
              { icon: Zap, label: "Win Rate", value: "72.1%" },
            ].map((s) => (
              <div key={s.label} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ width: 36, height: 36, borderRadius: 10, background: "rgba(201,168,76,0.1)", border: "1px solid rgba(201,168,76,0.15)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <s.icon size={16} color="var(--gold)" />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{s.label}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>{s.value}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Demo credentials */}
        {mode === "login" && (
          <div style={{ background: "rgba(201,168,76,0.06)", border: "1px solid rgba(201,168,76,0.15)", borderRadius: 12, padding: "16px 20px" }}>
            <p style={{ fontSize: 11, fontWeight: 700, color: "var(--gold)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>Demo Access</p>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>Admin: admin@seekquant.com / admin123</p>
            <p style={{ fontSize: 12, color: "var(--text-muted)" }}>Trader: john@example.com / trader123</p>
          </div>
        )}
      </div>

      {/* Right panel - Form */}
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "48px 40px" }}>
        <div style={{ width: "100%", maxWidth: 400 }}>
          <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text)", letterSpacing: "-0.02em", marginBottom: 8 }}>
            {mode === "login" ? "Welcome back" : "Create account"}
          </h1>
          <p style={{ fontSize: 14, color: "var(--text-muted)", marginBottom: 32 }}>
            {mode === "login" ? "Sign in to access your dashboard" : "Start your journey with Seek Quant"}
          </p>

          {error && (
            <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 10, padding: "12px 16px", marginBottom: 20 }}>
              <p style={{ fontSize: 13, color: "#ef4444" }}>{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {mode === "signup" && (
              <div>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, letterSpacing: "0.04em" }}>FULL NAME</label>
                <input type="text" required value={formData.name} onChange={(e) => updateField("name", e.target.value)} className="input-field" placeholder="John Carter" />
              </div>
            )}

            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, letterSpacing: "0.04em" }}>EMAIL ADDRESS</label>
              <input type="email" required value={formData.email} onChange={(e) => updateField("email", e.target.value)} className="input-field" placeholder="you@example.com" />
            </div>

            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, letterSpacing: "0.04em" }}>PASSWORD</label>
              <div style={{ position: "relative" }}>
                <input type={showPassword ? "text" : "password"} required minLength={6} value={formData.password} onChange={(e) => updateField("password", e.target.value)} className="input-field" placeholder="••••••••" style={{ paddingRight: 44 }} />
                <button type="button" onClick={() => setShowPassword(!showPassword)} style={{ position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", display: "flex" }}>
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {mode === "signup" && (
              <>
                <div>
                  <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, letterSpacing: "0.04em" }}>CONFIRM PASSWORD</label>
                  <input type="password" required minLength={6} value={formData.confirmPassword} onChange={(e) => updateField("confirmPassword", e.target.value)} className="input-field" placeholder="••••••••" />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, letterSpacing: "0.04em" }}>INVESTOR TYPE</label>
                  <select value={formData.investorType} onChange={(e) => updateField("investorType", e.target.value)} className="input-field">
                    <option value="individual">Individual Investor</option>
                    <option value="accredited">Accredited Investor</option>
                    <option value="institutional">Institutional Investor</option>
                  </select>
                </div>
                <label style={{ display: "flex", alignItems: "flex-start", gap: 10, cursor: "pointer" }}>
                  <input type="checkbox" required checked={formData.acceptTerms} onChange={(e) => updateField("acceptTerms", e.target.checked)} style={{ marginTop: 2, accentColor: "var(--gold)" }} />
                  <span style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.6 }}>
                    I agree to the Terms of Service, Privacy Policy, and Risk Disclosure. I confirm I am a qualified investor.
                  </span>
                </label>
              </>
            )}

            {mode === "login" && (
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                <input type="checkbox" style={{ accentColor: "var(--gold)" }} />
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Remember me for 30 days</span>
              </label>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="btn-gold"
              style={{ padding: "14px", borderRadius: 10, fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 8 }}
            >
              {isLoading ? (
                <><Loader2 size={16} className="animate-spin" />{mode === "login" ? "Signing in..." : "Creating account..."}</>
              ) : mode === "login" ? "Sign In →" : "Create Account →"}
            </button>
          </form>

          <p style={{ marginTop: 24, fontSize: 13, color: "var(--text-muted)", textAlign: "center" }}>
            {mode === "login" ? "Don't have an account? " : "Already have an account? "}
            <Link href={mode === "login" ? "/signup" : "/login"} style={{ color: "var(--gold)", textDecoration: "none", fontWeight: 600 }}>
              {mode === "login" ? "Sign up" : "Sign in"}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

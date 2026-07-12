import Link from "next/link";

export default function Footer() {
  return (
    <footer style={{ background: "var(--surface)", borderTop: "1px solid var(--border)", marginTop: "auto" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "64px 32px 32px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 48, marginBottom: 48 }}>
          {/* Brand */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: "linear-gradient(135deg, #e8c97a, #c9a84c)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span style={{ color: "#000", fontWeight: 900, fontSize: 11 }}>SQ</span>
              </div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 14, color: "var(--text)" }}>Seek Quant</div>
                <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Capital Management</div>
              </div>
            </div>
            <p style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.7, maxWidth: 280 }}>
              A data-driven hedge fund leveraging machine learning and quantitative strategies to deliver superior risk-adjusted returns.
            </p>
          </div>

          {/* Quick Links */}
          <div>
            <h4 style={{ fontSize: 11, fontWeight: 700, color: "var(--text)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 16 }}>Navigation</h4>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[["Home", "/"], ["Login", "/login"], ["Sign Up", "/signup"]].map(([label, href]) => (
                <Link key={label} href={href} style={{ fontSize: 13, color: "var(--text-muted)", textDecoration: "none", transition: "color 0.15s" }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = "var(--gold)")}
                  onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
                >{label}</Link>
              ))}
            </div>
          </div>

          {/* Strategies */}
          <div>
            <h4 style={{ fontSize: 11, fontWeight: 700, color: "var(--text)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 16 }}>Strategies</h4>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {["ML Models", "Risk Management", "Global Markets", "Security"].map((item) => (
                <span key={item} style={{ fontSize: 13, color: "var(--text-muted)" }}>{item}</span>
              ))}
            </div>
          </div>

          {/* Legal */}
          <div>
            <h4 style={{ fontSize: 11, fontWeight: 700, color: "var(--text)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 16 }}>Legal</h4>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {["Privacy Policy", "Terms of Service", "Risk Disclosure"].map((item) => (
                <span key={item} style={{ fontSize: 13, color: "var(--text-muted)" }}>{item}</span>
              ))}
            </div>
          </div>
        </div>

        <div style={{ height: 1, background: "linear-gradient(90deg, transparent, var(--border), transparent)", marginBottom: 24 }} />
        <p style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "center" }}>
          © {new Date().getFullYear()} Seek Quant Capital Management. All rights reserved. Past performance is not indicative of future results.
        </p>
      </div>
    </footer>
  );
}

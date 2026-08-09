"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Mail, MessageSquare, Phone, ArrowLeft, Send, Check } from "lucide-react";

export default function ContactPage() {
  const [sent, setSent] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", company: "", message: "" });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    // Demo contact form — wire to an email/CRM service in production.
    setSent(true);
  };

  return (
    <main style={{ minHeight: "100vh", background: "var(--bg)", padding: "80px 24px 40px" }}>
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <Link
          href="/"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 13,
            color: "var(--text-muted)",
            textDecoration: "none",
            marginBottom: 24,
          }}
        >
          <ArrowLeft size={14} />
          Back to Home
        </Link>

        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            background: "rgba(201,168,76,0.08)",
            border: "1px solid rgba(201,168,76,0.2)",
            borderRadius: 100,
            padding: "4px 14px",
            marginBottom: 20,
          }}
        >
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--gold)", letterSpacing: "0.12em", textTransform: "uppercase" }}>
            Contact Sales
          </span>
        </div>
        <h1
          style={{
            fontSize: "clamp(28px, 4vw, 42px)",
            fontWeight: 800,
            letterSpacing: "-0.02em",
            color: "var(--text)",
            lineHeight: 1.1,
            marginBottom: 16,
          }}
        >
          Talk to the{" "}
          <span style={{ background: "linear-gradient(135deg, #e8c97a, #c9a84c)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
            Seek Quant
          </span>{" "}
          team
        </h1>
        <p style={{ fontSize: 15, color: "var(--text-muted)", lineHeight: 1.7, marginBottom: 40 }}>
          Interested in enterprise access, white-label dashboards, or institutional
          allocations? Send us a message and we will respond within one business day.
        </p>

        <div style={{ display: "grid", gap: 12, marginBottom: 40 }}>
          {[
            { icon: Mail, label: "Email", value: "invest@seekquant.com" },
            { icon: Phone, label: "Phone", value: "+1 (415) 555-0182" },
            { icon: MessageSquare, label: "Response time", value: "Within 1 business day" },
          ].map((c) => (
            <div key={c.label} style={{ display: "flex", alignItems: "center", gap: 14, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 12, padding: "14px 18px" }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: "rgba(201,168,76,0.1)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <c.icon size={16} color="var(--gold)" />
              </div>
              <div>
                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>{c.label}</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginTop: 1 }}>{c.value}</div>
              </div>
            </div>
          ))}
        </div>

        {sent ? (
          <div style={{ background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.25)", borderRadius: 16, padding: "40px 32px", textAlign: "center" }}>
            <div style={{ width: 48, height: 48, borderRadius: "50%", background: "rgba(34,197,94,0.15)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
              <Check size={22} color="#22c55e" />
            </div>
            <h3 style={{ fontSize: 18, fontWeight: 700, color: "var(--text)", marginBottom: 8 }}>Message received</h3>
            <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
              Thank you for reaching out. Our team will get back to you within one business day.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, padding: "28px", display: "grid", gap: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div>
                <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, display: "block" }}>Name</label>
                <input className="input-field" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Jane Smith" />
              </div>
              <div>
                <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, display: "block" }}>Email</label>
                <input className="input-field" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="jane@fund.com" />
              </div>
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, display: "block" }}>Company / Organisation</label>
              <input className="input-field" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} placeholder="Acme Capital" />
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6, display: "block" }}>Message</label>
              <textarea className="input-field" required rows={5} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} placeholder="Tell us about your requirements…" style={{ resize: "vertical" }} />
            </div>
            <button
              type="submit"
              className="btn-gold"
              style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8, padding: "14px 28px", borderRadius: 10, fontSize: 14 }}
            >
              <Send size={15} />
              Send Message
            </button>
          </form>
        )}
      </div>
    </main>
  );
}


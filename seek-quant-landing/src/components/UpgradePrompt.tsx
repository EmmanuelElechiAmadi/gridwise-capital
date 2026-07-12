"use client";

import Link from "next/link";
import { ArrowRight, Lock } from "lucide-react";

interface Props {
  title?: string;
  description?: string;
  actionLabel?: string;
  actionHref?: string;
}

export default function UpgradePrompt({
  title = "Upgrade Required",
  description = "This feature is available on a paid plan.",
  actionLabel = "View Plans",
  actionHref = "/pricing",
}: Props) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "60px 24px",
        textAlign: "center",
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: "50%",
          background: "rgba(201, 168, 76, 0.1)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 20,
        }}
      >
        <Lock size={24} color="var(--gold)" />
      </div>
      <h3
        style={{
          fontSize: 18,
          fontWeight: 700,
          color: "var(--text)",
          marginBottom: 8,
        }}
      >
        {title}
      </h3>
      <p
        style={{
          fontSize: 13,
          color: "var(--text-muted)",
          maxWidth: 360,
          lineHeight: 1.5,
          marginBottom: 24,
        }}
      >
        {description}
      </p>
      <Link
        href={actionHref}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 24px",
          borderRadius: 10,
          background: "linear-gradient(135deg, #e8c97a, #c9a84c)",
          color: "#000",
          fontWeight: 600,
          fontSize: 14,
          textDecoration: "none",
          transition: "opacity 0.2s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.9")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
      >
        {actionLabel}
        <ArrowRight size={14} />
      </Link>
    </div>
  );
}
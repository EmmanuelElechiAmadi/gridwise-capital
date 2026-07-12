"use client";

import AuthForm from "@/components/AuthForm";
import { AuthProvider } from "@/lib/auth";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function LoginContent() {
  const searchParams = useSearchParams();
  const registered = searchParams.get("registered");
  return (
    <AuthProvider>
      {registered === "true" && (
        <div style={{ position: "fixed", top: 20, left: "50%", transform: "translateX(-50%)", zIndex: 100, background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.3)", borderRadius: 10, padding: "12px 24px" }}>
          <p style={{ fontSize: 13, color: "#22c55e", fontWeight: 600 }}>Account created! Please sign in.</p>
        </div>
      )}
      <AuthForm mode="login" />
    </AuthProvider>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginContent />
    </Suspense>
  );
}

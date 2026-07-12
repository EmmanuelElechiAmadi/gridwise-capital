"use client";

import AuthForm from "@/components/AuthForm";
import { AuthProvider } from "@/lib/auth";

export default function SignupPage() {
  return (
    <AuthProvider>
      <AuthForm mode="signup" />
    </AuthProvider>
  );
}

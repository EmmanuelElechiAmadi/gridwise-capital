"use client";

import PricingSection from "@/components/PricingSection";
import Footer from "@/components/Footer";

export default function PricingPage() {
  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "var(--bg)" }}>
      <div style={{ height: 72 }} />
      <PricingSection />
      <Footer />
    </main>
  );
}

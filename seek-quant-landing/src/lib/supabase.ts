/**
 * Supabase client singleton.
 * When NEXT_PUBLIC_SUPABASE_URL is empty, the app runs in DEMO mode
 * with in-memory/localStorage storage instead.
 */

import { createBrowserClient } from "@supabase/ssr";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);

let supabaseClient: ReturnType<typeof createBrowserClient> | null = null;

export function getSupabaseClient() {
  if (!isSupabaseConfigured) return null;
  if (!supabaseClient) {
    supabaseClient = createBrowserClient(supabaseUrl, supabaseAnonKey);
  }
  return supabaseClient;
}
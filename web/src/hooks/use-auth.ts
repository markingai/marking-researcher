"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { isAuthenticated, clearToken } from "@/lib/api";

export function useAuth() {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
    } else {
      setChecked(true);
    }
  }, [router]);

  const logout = useCallback(() => {
    clearToken();
    router.replace("/login");
  }, [router]);

  return { authenticated: checked, logout };
}

"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { subscribeToRunEvents } from "@/lib/api";

export interface ProgressEvent {
  strategy: string;
  completed: number;
  total: number;
  completed_overall: number;
  total_overall: number;
  error: boolean;
}

export interface StrategyCompleteEvent {
  strategy: string;
  metrics: {
    n: number;
    exact_match_pct: number;
    within_1_pct: number;
    mae: number;
    mean_signed_error: number;
  };
}

export interface RunCompleteEvent {
  run_id: string;
  status: string;
}

interface UseRunProgressOptions {
  onProgress?: (data: ProgressEvent) => void;
  onStrategyStart?: (data: { strategy: string; total_rows: number }) => void;
  onStrategyComplete?: (data: StrategyCompleteEvent) => void;
  onRunComplete?: (data: RunCompleteEvent) => void;
  onError?: (data: { message: string }) => void;
}

export function useRunProgress(
  runId: string | null,
  options: UseRunProgressOptions = {},
) {
  const [connected, setConnected] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    if (!runId) return;

    const cleanup = subscribeToRunEvents(runId, (event, data) => {
      setConnected(true);
      const opts = optionsRef.current;
      switch (event) {
        case "progress":
          opts.onProgress?.(data as unknown as ProgressEvent);
          break;
        case "strategy_start":
          opts.onStrategyStart?.(data as unknown as { strategy: string; total_rows: number });
          break;
        case "strategy_complete":
          opts.onStrategyComplete?.(data as unknown as StrategyCompleteEvent);
          break;
        case "run_complete":
          opts.onRunComplete?.(data as unknown as RunCompleteEvent);
          break;
        case "error":
          opts.onError?.(data as unknown as { message: string });
          break;
      }
    });

    cleanupRef.current = cleanup;

    return () => {
      cleanup();
      setConnected(false);
    };
  }, [runId]);

  return { connected };
}

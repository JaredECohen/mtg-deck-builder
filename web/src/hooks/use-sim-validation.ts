"use client";

import { useEffect, useRef, useState } from "react";

import { fetchJob } from "@/lib/api";
import type { SimValidationStatus } from "@/lib/types";

/** Optimizer result deck card shape. */
type OptDeckCard = { name: string; type_line?: string; cmc?: number };

export type SimValidationResult = {
  status: SimValidationStatus;
  /** Optimizer-improved mainboard (one entry per card, may include duplicates). */
  optimizedDeck?: OptDeckCard[] | null;
  /** Optimizer-reported fitness score for the BEST deck after annealing. */
  optimizerScore?: number | null;
  /** Optimizer's score for the seed deck BEFORE annealing — used to compute
   *  improvement delta so we only surface the Apply button when the sim
   *  actually found something better. */
  baselineScore?: number | null;
  /** Relative improvement: (best - baseline) / |baseline|. Between 0 and 1
   *  typically. 0.10 = 10% better. Null when baseline is missing or zero. */
  improvement?: number | null;
};

/**
 * Polls a sim-validation job until it terminates, then fetches the
 * optimizer's improved deck so the UI can offer an "Apply sim-optimized
 * version" button. ProvenanceBanner consumes this. Polls every 3s and
 * gives up after ~90s.
 */
export function useSimValidation(jobId: string | null | undefined): SimValidationResult {
  const [status, setStatus] = useState<SimValidationStatus>("unknown");
  const [optimizedDeck, setOptimizedDeck] = useState<OptDeckCard[] | null>(null);
  const [optimizerScore, setOptimizerScore] = useState<number | null>(null);
  const [baselineScore, setBaselineScore] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) {
      setStatus("unknown");
      setOptimizedDeck(null);
      setOptimizerScore(null);
      setBaselineScore(null);
      return;
    }
    setStatus("running");
    setOptimizedDeck(null);
    setOptimizerScore(null);
    setBaselineScore(null);
    // Pending fetches can resolve after jobId changes or the component
    // unmounts; this flag makes those stale responses no-ops.
    let cancelled = false;
    let attempts = 0;
    const tick = async () => {
      attempts += 1;
      try {
        const record: any = await fetchJob(jobId);
        if (cancelled) return;
        const s = String(record?.status ?? "").toLowerCase();
        if (s === "completed" || s === "succeeded" || s === "cached") {
          setStatus("succeeded");
          // Result payload may live on .result or .raw — check both.
          const result = record?.result ?? record?.raw ?? null;
          if (result && Array.isArray(result.deck)) {
            setOptimizedDeck(result.deck as OptDeckCard[]);
          }
          if (result && typeof result.score === "number") {
            setOptimizerScore(result.score);
          }
          if (result && typeof result.baseline_score === "number") {
            setBaselineScore(result.baseline_score);
          }
          if (timer.current) clearInterval(timer.current);
        } else if (s === "failed" || s === "error") {
          setStatus("failed");
          if (timer.current) clearInterval(timer.current);
        } else if (attempts >= 30) {
          setStatus("failed");
          if (timer.current) clearInterval(timer.current);
        }
      } catch {
        if (cancelled) return;
        if (attempts >= 30) {
          setStatus("failed");
          if (timer.current) clearInterval(timer.current);
        }
      }
    };
    void tick();
    timer.current = setInterval(() => void tick(), 3000);
    return () => {
      cancelled = true;
      if (timer.current) clearInterval(timer.current);
    };
  }, [jobId]);

  // Improvement delta. Null when we can't compute a meaningful comparison
  // (no baseline, or baseline ≈ 0). Negative when the optimizer's best
  // somehow underperformed the seed (shouldn't happen but we still don't
  // surface the Apply button in that case).
  let improvement: number | null = null;
  if (
    optimizerScore != null &&
    baselineScore != null &&
    Math.abs(baselineScore) > 1e-6
  ) {
    improvement = (optimizerScore - baselineScore) / Math.abs(baselineScore);
  }

  return { status, optimizedDeck, optimizerScore, baselineScore, improvement };
}

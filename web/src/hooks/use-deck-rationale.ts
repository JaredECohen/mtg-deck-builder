"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJob, submitOptimizerJob } from "@/lib/api";
import type { DeckRationaleData, OptimizerJobRequest, SideboardPlanData } from "@/lib/types";

export type RationaleStatus = "idle" | "submitting" | "polling" | "succeeded" | "failed";

const POLL_INTERVAL_MS = 600;
const POLL_TIMEOUT_MS = 90_000;

export function useDeckRationale() {
  const [rationale, setRationale] = useState<DeckRationaleData | null>(null);
  const [sideboard, setSideboard] = useState<SideboardPlanData | null>(null);
  const [status, setStatus] = useState<RationaleStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTime = useRef<number | null>(null);
  // Every submit/reset bumps the generation; a poll or submit response from an
  // older generation (or another job id) is ignored.
  const generation = useRef(0);
  const activeJob = useRef<string | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
  }, []);

  useEffect(() => {
    return () => {
      generation.current += 1;
      activeJob.current = null;
      stopPolling();
    };
  }, [stopPolling]);

  const reset = useCallback(() => {
    generation.current += 1;
    activeJob.current = null;
    stopPolling();
    setRationale(null);
    setSideboard(null);
    setStatus("idle");
    setError(null);
    setJobId(null);
  }, [stopPolling]);

  const pollJob = useCallback(
    async (id: string, gen: number) => {
      const isCurrent = () => generation.current === gen && activeJob.current === id;
      if (!isCurrent()) return;
      try {
        const job = await fetchJob(id);
        if (!isCurrent()) return;
        if (job.status === "succeeded" || job.status === "cached") {
          const result = (job.result ?? {}) as { rationale?: DeckRationaleData; sideboard?: SideboardPlanData };
          setRationale(result.rationale ?? null);
          setSideboard(result.sideboard ?? null);
          setStatus("succeeded");
          return;
        }
        if (job.status === "failed") {
          setError(job.error ?? "Optimizer job failed");
          setStatus("failed");
          return;
        }
        if (startTime.current && Date.now() - startTime.current > POLL_TIMEOUT_MS) {
          setError("Optimizer job timed out");
          setStatus("failed");
          return;
        }
        pollTimer.current = setTimeout(() => void pollJob(id, gen), POLL_INTERVAL_MS);
      } catch (err) {
        if (!isCurrent()) return;
        setError(err instanceof Error ? err.message : "Job poll failed");
        setStatus("failed");
      }
    },
    []
  );

  const submit = useCallback(
    async (payload: OptimizerJobRequest) => {
      generation.current += 1;
      const gen = generation.current;
      activeJob.current = null;
      stopPolling();
      setStatus("submitting");
      setError(null);
      setRationale(null);
      setSideboard(null);
      try {
        const response = await submitOptimizerJob(payload);
        if (generation.current !== gen) return;
        activeJob.current = response.job_id;
        setJobId(response.job_id);
        startTime.current = Date.now();
        setStatus("polling");
        void pollJob(response.job_id, gen);
      } catch (err) {
        if (generation.current !== gen) return;
        setError(err instanceof Error ? err.message : "Optimizer submission failed");
        setStatus("failed");
      }
    },
    [pollJob, stopPolling]
  );

  return { rationale, sideboard, status, error, jobId, submit, reset };
}

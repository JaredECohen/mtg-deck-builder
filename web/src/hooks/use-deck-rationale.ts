"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJob, submitOptimizerJob } from "@/lib/api";
import type { DeckRationaleData, JobRecord, OptimizerJobRequest } from "@/lib/types";

type Status = "idle" | "submitting" | "polling" | "succeeded" | "failed";

const POLL_INTERVAL_MS = 600;
const POLL_TIMEOUT_MS = 90_000;

export function useDeckRationale() {
  const [rationale, setRationale] = useState<DeckRationaleData | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTime = useRef<number | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    return () => {
      cancelled.current = true;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  const reset = useCallback(() => {
    cancelled.current = true;
    if (pollTimer.current) clearTimeout(pollTimer.current);
    setRationale(null);
    setStatus("idle");
    setError(null);
    setJobId(null);
  }, []);

  const submit = useCallback(async (payload: OptimizerJobRequest) => {
    cancelled.current = false;
    setStatus("submitting");
    setError(null);
    setRationale(null);
    try {
      const response = await submitOptimizerJob(payload);
      if (cancelled.current) return;
      setJobId(response.job_id);
      startTime.current = Date.now();
      // If the server returned a cached result already, the next poll
      // will pick it up. Otherwise begin polling.
      setStatus("polling");
      void pollJob(response.job_id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Optimizer submission failed";
      setError(msg);
      setStatus("failed");
    }
  }, []);

  const pollJob = useCallback(async (id: string) => {
    if (cancelled.current) return;
    try {
      const job: JobRecord = await fetchJob(id);
      if (cancelled.current) return;
      if (job.status === "succeeded" || job.status === "cached") {
        const result = (job.result ?? {}) as { rationale?: DeckRationaleData };
        setRationale(result.rationale ?? null);
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
      pollTimer.current = setTimeout(() => void pollJob(id), POLL_INTERVAL_MS);
    } catch (err) {
      if (cancelled.current) return;
      const msg = err instanceof Error ? err.message : "Job poll failed";
      setError(msg);
      setStatus("failed");
    }
  }, []);

  return { rationale, status, error, jobId, submit, reset };
}

"use client";

import { useEffect, useState } from "react";

import { fetchDataStatus } from "@/lib/api";
import type { DataStatusResponse } from "@/lib/types";

export function useDataStatus(): DataStatusResponse | null {
  const [status, setStatus] = useState<DataStatusResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void fetchDataStatus(controller.signal).then((value) => {
      if (!controller.signal.aborted) {
        setStatus(value);
      }
    });
    return () => controller.abort();
  }, []);

  return status;
}

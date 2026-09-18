"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  GenerationTaskStatus,
  PresentationGenerationApi,
} from "../../services/api/presentation-generation";

const POLL_INTERVAL_MS = 3000;

const SkyworkResultPage = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const taskId = searchParams.get("task");

  const [task, setTask] = useState<GenerationTaskStatus | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!taskId) return;

    const poll = async () => {
      try {
        const latest = await PresentationGenerationApi.getGenerationTaskStatus(
          taskId
        );
        setTask(latest);
        if (latest.status === "completed" || latest.status === "error") {
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
      } catch (error) {
        setPollError(
          error instanceof Error ? error.message : "Failed to check status"
        );
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    };

    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [taskId]);

  // Skywork's .pptx was successfully bridged into an editable Smart-mode
  // deck — open it the same way local Smart mode does, instead of showing
  // the download-only "ready" screen.
  useEffect(() => {
    if (
      task?.status === "completed" &&
      task.data?.editable &&
      task.data?.presentation_id
    ) {
      router.push(
        `/presentation?id=${task.data.presentation_id}&stream=true&type=smart`
      );
    }
  }, [task, router]);

  if (!taskId) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-lg font-medium text-[#333333]">
          No generation task specified.
        </p>
        <Button onClick={() => router.push("/upload")}>Go to Upload</Button>
      </div>
    );
  }

  const status = task?.status ?? "pending";
  const data = task?.data;
  const progress = Math.min(Math.max(data?.progress ?? 0, 0), 100);

  if (status === "error" || pollError) {
    const message =
      pollError || task?.error?.detail || task?.message || "Generation failed.";
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-lg font-medium text-red-600">Something went wrong</p>
        <p className="max-w-md text-sm text-[#666666]">{message}</p>
        <Button onClick={() => router.push("/upload")}>Try again</Button>
      </div>
    );
  }

  if (status === "completed" && data?.editable && data?.presentation_id) {
    // Redirect handled by the effect above; avoid flashing the download UI.
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#EBE9FE] border-t-[#7A5AF8]" />
        <p className="text-lg font-medium text-[#333333]">Opening in the editor...</p>
      </div>
    );
  }

  if (status === "completed" && data?.path) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-xl font-medium text-[#333333]">
          Your deck is ready
        </p>
        {data.title && (
          <p className="max-w-md text-sm text-[#666666]">{data.title}</p>
        )}
        <p className="max-w-md text-sm text-[#999999]">
          Couldn't be opened as an editable deck this time — here's the file.
        </p>
        <a
          href={data.path}
          download={data.filename}
          className="rounded-[80px] bg-[#7A5AF8] px-6 py-2.5 text-base font-medium text-white hover:bg-[#6938EF]/90"
        >
          Download .pptx
        </a>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#EBE9FE] border-t-[#7A5AF8]" />
      <p className="text-lg font-medium text-[#333333]">
        {data?.message || task?.message || "Generating via Skywork..."}
      </p>
      <div className="h-2 w-64 overflow-hidden rounded-full bg-[#EBE9FE]">
        <div
          className="h-full rounded-full bg-[#7A5AF8] transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
};

export default SkyworkResultPage;

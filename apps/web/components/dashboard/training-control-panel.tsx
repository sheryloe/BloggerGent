"use client";

import { useEffect, useMemo, useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { TrainingStatus } from "@/lib/types";

function resolveApiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
}

function formatSeconds(value?: number | null) {
  if (!value || value <= 0) return "-";
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function stateLabel(state: string) {
  switch (state) {
    case "running":
      return "Running";
    case "queued":
      return "Queued";
    case "paused":
      return "Paused";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    default:
      return "Idle";
  }
}

function stateTone(state: string) {
  if (state === "running") return "bg-emerald-500/10 text-emerald-700";
  if (state === "queued") return "bg-indigo-500/10 text-indigo-700";
  if (state === "paused") return "bg-amber-500/10 text-amber-700";
  if (state === "completed") return "bg-sky-500/10 text-sky-700";
  if (state === "failed") return "bg-rose-500/10 text-rose-700";
  return "bg-slate-200 text-slate-700";
}

type Props = {
  initialStatus: TrainingStatus;
  providerMode: string;
};

export function TrainingControlPanel({ initialStatus, providerMode }: Props) {
  const [status, setStatus] = useState<TrainingStatus>(initialStatus);
  const [sessionHours, setSessionHours] = useState(String(initialStatus.session_hours || 4));
  const [saveEveryMinutes, setSaveEveryMinutes] = useState(String(initialStatus.save_every_minutes || 20));
  const [scheduleEnabled, setScheduleEnabled] = useState(initialStatus.schedule.enabled ? "true" : "false");
  const [scheduleTime, setScheduleTime] = useState(initialStatus.schedule.time || "03:00");
  const [scheduleTimezone, setScheduleTimezone] = useState(initialStatus.schedule.timezone || "Asia/Seoul");
  const [message, setMessage] = useState("");
  const [isPending, startTransition] = useTransition();

  const progress = useMemo(() => {
    if (!status.total_steps || status.total_steps <= 0) return 0;
    const percent = (status.current_step / status.total_steps) * 100;
    return Math.max(0, Math.min(100, Math.round(percent)));
  }, [status.current_step, status.total_steps]);

  useEffect(() => {
    const timer = setInterval(() => {
      fetch(`${resolveApiBaseUrl()}/training/status`, { cache: "no-store" })
        .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
        .then((payload: TrainingStatus) => setStatus(payload))
        .catch(() => undefined);
    }, 8000);
    return () => clearInterval(timer);
  }, []);

  async function applyAction(path: string, method: "POST" | "PUT", payload: Record<string, unknown> = {}) {
    const response = await fetch(`${resolveApiBaseUrl()}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`;
      throw new Error(detail);
    }
    setStatus(body as TrainingStatus);
    return body as TrainingStatus;
  }

  function onStart() {
    setMessage("");
    startTransition(() => {
      void applyAction("/training/start", "POST", {
        session_hours: Number(sessionHours),
        save_every_minutes: Number(saveEveryMinutes),
      })
        .then(() => setMessage("Training started."))
        .catch((error: Error) => setMessage(error.message));
    });
  }

  function onPause() {
    setMessage("");
    startTransition(() => {
      void applyAction("/training/pause", "POST")
        .then(() => setMessage("Pause requested."))
        .catch((error: Error) => setMessage(error.message));
    });
  }

  function onResume() {
    setMessage("");
    startTransition(() => {
      void applyAction("/training/resume", "POST", {
        session_hours: Number(sessionHours),
        save_every_minutes: Number(saveEveryMinutes),
      })
        .then(() => setMessage("Training resumed from latest checkpoint."))
        .catch((error: Error) => setMessage(error.message));
    });
  }

  function onSaveSchedule() {
    setMessage("");
    startTransition(() => {
      void applyAction("/training/schedule", "PUT", {
        enabled: scheduleEnabled === "true",
        time: scheduleTime,
        timezone: scheduleTimezone,
      })
        .then(() => setMessage("Schedule saved."))
        .catch((error: Error) => setMessage(error.message));
    });
  }

  const isActive = status.state === "running" || status.state === "queued";

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Training Session</CardTitle>
          <CardDescription>4-hour session mode with periodic checkpoint save and resume support.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={stateTone(status.state)}>{stateLabel(status.state)}</Badge>
            <Badge className="border border-ink/15 bg-white text-ink">Provider mode: {providerMode || "unknown"}</Badge>
            <Badge className="border border-ink/15 bg-white text-ink">Model: {status.model_name || "not set"}</Badge>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between text-sm text-slate-600">
              <span>Progress</span>
              <span>
                {status.current_step} / {status.total_steps || 0} ({progress}%)
              </span>
            </div>
            <div className="h-3 w-full overflow-hidden rounded-full bg-slate-200">
              <div className="h-full bg-emerald-500 transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-[20px] border border-ink/10 bg-white/70 p-3 text-sm">
              <p className="text-slate-500">Elapsed</p>
              <p className="mt-1 font-semibold text-ink">{formatSeconds(status.elapsed_seconds)}</p>
            </div>
            <div className="rounded-[20px] border border-ink/10 bg-white/70 p-3 text-sm">
              <p className="text-slate-500">ETA</p>
              <p className="mt-1 font-semibold text-ink">{formatSeconds(status.eta_seconds)}</p>
            </div>
            <div className="rounded-[20px] border border-ink/10 bg-white/70 p-3 text-sm">
              <p className="text-slate-500">Dataset items</p>
              <p className="mt-1 font-semibold text-ink">{status.dataset_item_count}</p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto_auto]">
            <div className="space-y-2">
              <Label htmlFor="session_hours">Session Hours</Label>
              <Input
                id="session_hours"
                type="number"
                min={0.1}
                max={24}
                step={0.1}
                value={sessionHours}
                onChange={(event) => setSessionHours(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="save_every_minutes">Save Every (minutes)</Label>
              <Input
                id="save_every_minutes"
                type="number"
                min={1}
                max={180}
                value={saveEveryMinutes}
                onChange={(event) => setSaveEveryMinutes(event.target.value)}
              />
            </div>
            <div className="flex items-end">
              <Button type="button" onClick={onStart} disabled={isPending || isActive}>
                Start
              </Button>
            </div>
            <div className="flex items-end gap-2">
              <Button type="button" variant="outline" onClick={onResume} disabled={isPending || isActive}>
                Resume
              </Button>
              <Button type="button" variant="outline" onClick={onPause} disabled={isPending || !isActive}>
                Pause
              </Button>
            </div>
          </div>

          <div className="rounded-[20px] border border-dashed border-ink/15 bg-slate-50 p-3 text-sm text-slate-600">
            <p>Data scope: {status.data_scope}</p>
            <p className="mt-1 break-all">Last checkpoint: {status.last_checkpoint || "-"}</p>
            <p className="mt-1">Next schedule: {status.next_scheduled_at || "-"}</p>
            {status.last_error ? <p className="mt-2 text-rose-700">Last error: {status.last_error}</p> : null}
            {message ? <p className="mt-2 text-ink">{message}</p> : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scheduled Training</CardTitle>
          <CardDescription>Automatic daily start at the configured local time.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-[180px_160px_1fr_auto]">
          <div className="space-y-2">
            <Label htmlFor="schedule_enabled">Enabled</Label>
            <select
              id="schedule_enabled"
              className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm"
              value={scheduleEnabled}
              onChange={(event) => setScheduleEnabled(event.target.value)}
            >
              <option value="false">Disabled</option>
              <option value="true">Enabled</option>
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="schedule_time">Time (HH:MM)</Label>
            <Input id="schedule_time" value={scheduleTime} onChange={(event) => setScheduleTime(event.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="schedule_timezone">Timezone</Label>
            <Input
              id="schedule_timezone"
              value={scheduleTimezone}
              onChange={(event) => setScheduleTimezone(event.target.value)}
            />
          </div>
          <div className="flex items-end">
            <Button type="button" onClick={onSaveSchedule} disabled={isPending}>
              Save Schedule
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent Logs</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-[320px] space-y-2 overflow-y-auto rounded-[20px] border border-ink/10 bg-white/70 p-3">
            {status.recent_logs.length ? (
              status.recent_logs
                .slice()
                .reverse()
                .map((line) => (
                  <p key={line} className="font-mono text-xs leading-6 text-slate-700">
                    {line}
                  </p>
                ))
            ) : (
              <p className="text-sm text-slate-500">No logs yet.</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}


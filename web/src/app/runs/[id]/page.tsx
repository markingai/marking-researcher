"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { ArrowLeft, Square, BarChart3 } from "lucide-react";
import { toast } from "sonner";
import { getRun, cancelRun, type RunDetail, type RunStrategyStatus } from "@/lib/api";
import {
  useRunProgress,
  type ProgressEvent,
  type StrategyCompleteEvent,
} from "@/hooks/use-run-progress";

export default function RunMonitorPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;

  const [run, setRun] = useState<RunDetail | null>(null);
  const [completedOverall, setCompletedOverall] = useState(0);
  const [totalOverall, setTotalOverall] = useState(0);
  const [strategyMetrics, setStrategyMetrics] = useState<
    Record<string, StrategyCompleteEvent["metrics"]>
  >({});
  const [cancelling, setCancelling] = useState(false);

  // Load initial state
  useEffect(() => {
    getRun(runId)
      .then((d) => {
        setRun(d);
        setCompletedOverall(d.completed_rows);
        setTotalOverall(d.total_rows);
      })
      .catch(() => toast.error("Failed to load run"));
  }, [runId]);

  const isActive = run?.status === "running" || run?.status === "pending";

  // SSE progress
  const onProgress = useCallback((data: ProgressEvent) => {
    setCompletedOverall(data.completed_overall);
    setTotalOverall(data.total_overall);

    // Update strategy progress
    setRun((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        strategies: prev.strategies.map((s) =>
          s.strategy_name === data.strategy
            ? { ...s, rows_completed: data.completed, status: "running" }
            : s,
        ),
      };
    });
  }, []);

  const onStrategyComplete = useCallback((data: StrategyCompleteEvent) => {
    setStrategyMetrics((prev) => ({ ...prev, [data.strategy]: data.metrics }));
    setRun((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        strategies: prev.strategies.map((s) =>
          s.strategy_name === data.strategy
            ? { ...s, status: "completed" }
            : s,
        ),
      };
    });
  }, []);

  const onRunComplete = useCallback(() => {
    getRun(runId).then(setRun).catch(() => {});
  }, [runId]);

  const onError = useCallback((data: { message: string }) => {
    toast.error(data.message);
    getRun(runId).then(setRun).catch(() => {});
  }, [runId]);

  useRunProgress(isActive ? runId : null, {
    onProgress,
    onStrategyComplete,
    onRunComplete,
    onError,
  });

  async function handleCancel() {
    setCancelling(true);
    try {
      await cancelRun(runId);
      toast.success("Run cancelled");
      getRun(runId).then(setRun).catch(() => {});
    } catch {
      toast.error("Failed to cancel run");
    } finally {
      setCancelling(false);
    }
  }

  if (!run) return <AppShell><p>Loading...</p></AppShell>;

  const overallPct = totalOverall > 0 ? (completedOverall / totalOverall) * 100 : 0;

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="sm" onClick={() => router.back()}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h1 className="text-2xl font-semibold">
                {run.name || run.id.slice(0, 8)}
              </h1>
              <p className="text-sm text-muted-foreground capitalize">
                {run.subject} &middot; {run.input_mode}
                {run.model_override && ` &middot; ${run.model_override}`}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            {isActive && (
              <Button
                variant="destructive"
                size="sm"
                onClick={handleCancel}
                disabled={cancelling}
              >
                <Square className="mr-2 h-3 w-3" />
                {cancelling ? "Cancelling..." : "Cancel"}
              </Button>
            )}
            {run.status === "completed" && (
              <Link href={`/runs/${runId}/results`} className={buttonVariants()}>
                <BarChart3 className="mr-2 h-4 w-4" />
                View Results
              </Link>
            )}
          </div>
        </div>

        {/* Overall progress */}
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Overall Progress</CardTitle>
              <div className="flex items-center gap-2">
                <Badge
                  variant={
                    run.status === "completed"
                      ? "default"
                      : run.status === "failed"
                        ? "destructive"
                        : "secondary"
                  }
                >
                  {run.status}
                </Badge>
                <span className="text-sm text-muted-foreground">
                  ${run.total_cost_usd.toFixed(4)}
                </span>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <Progress value={overallPct} className="mb-2" />
            <p className="text-sm text-muted-foreground">
              {completedOverall} / {totalOverall} rows ({overallPct.toFixed(0)}%)
            </p>
          </CardContent>
        </Card>

        {/* Per-strategy cards */}
        <div className="space-y-3">
          {run.strategies.map((s) => (
            <StrategyProgressCard
              key={s.strategy_name}
              strategy={s}
              metrics={strategyMetrics[s.strategy_name]}
            />
          ))}
        </div>
      </div>
    </AppShell>
  );
}

function StrategyProgressCard({
  strategy,
  metrics,
}: {
  strategy: RunStrategyStatus;
  metrics?: StrategyCompleteEvent["metrics"];
}) {
  const pct =
    strategy.rows_total > 0
      ? (strategy.rows_completed / strategy.rows_total) * 100
      : 0;

  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{strategy.strategy_name}</span>
            <Badge
              variant={
                strategy.status === "completed"
                  ? "default"
                  : strategy.status === "running"
                    ? "secondary"
                    : "outline"
              }
              className="text-xs"
            >
              {strategy.status}
            </Badge>
          </div>
          <span className="text-xs text-muted-foreground">
            {strategy.rows_completed}/{strategy.rows_total}
            {strategy.errors > 0 && ` (${strategy.errors} errors)`}
            {" "}
            &middot; ${strategy.cost_usd.toFixed(4)}
          </span>
        </div>
        <Progress value={pct} className="h-1.5" />
        {metrics && (
          <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
            <span>Exact: {metrics.exact_match_pct}%</span>
            <span>Within 1: {metrics.within_1_pct}%</span>
            <span>MAE: {metrics.mae}</span>
            <span>Bias: {metrics.mean_signed_error > 0 ? "+" : ""}{metrics.mean_signed_error}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

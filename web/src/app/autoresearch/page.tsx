"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  FlaskConical,
  Bot,
  Play,
  Square,
  Check,
  X,
  Trophy,
  Loader2,
  DollarSign,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import {
  startAutoresearchSession,
  getAutoresearchSessions,
  getAutoresearchSession,
  stopAutoresearchSession,
  subscribeToAutoresearchEvents,
  type AutoresearchSession,
  type AutoresearchExperiment,
} from "@/lib/api";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function AutoresearchPage() {
  const [sessions, setSessions] = useState<AutoresearchSession[]>([]);
  const [activeSession, setActiveSession] = useState<AutoresearchSession | null>(null);
  const [experiments, setExperiments] = useState<AutoresearchExperiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);

  // Config
  const [budget, setBudget] = useState(20);
  const [sampleSize, setSampleSize] = useState(30);
  const [model, setModel] = useState("gemini-2.5-pro");

  const cleanupRef = useRef<(() => void) | null>(null);

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    try {
      const data = await getAutoresearchSessions();
      setSessions(data);

      // Find running or most recent session
      const running = data.find((s) => s.status === "running");
      if (running) {
        await loadSessionDetail(running.id);
      } else if (data.length > 0) {
        await loadSessionDetail(data[0].id);
      }
    } catch {
      // First time — no sessions yet
    } finally {
      setLoading(false);
    }
  };

  const loadSessionDetail = async (id: string) => {
    try {
      const detail = await getAutoresearchSession(id);
      setActiveSession(detail.session);
      setExperiments(detail.experiments);

      // Subscribe to SSE if running
      if (detail.session.status === "running") {
        subscribeToSession(detail.session.id);
      }
    } catch {
      toast.error("Failed to load session");
    }
  };

  const subscribeToSession = useCallback((sessionId: string) => {
    // Clean up existing subscription
    if (cleanupRef.current) {
      cleanupRef.current();
    }

    const cleanup = subscribeToAutoresearchEvents(sessionId, (event, data) => {
      if (event === "experiment_complete") {
        const exp = data as unknown as AutoresearchExperiment & {
          spent_so_far: number;
          budget_usd: number;
        };
        setExperiments((prev) => [
          ...prev,
          {
            id: (data as Record<string, unknown>).experiment_id as string,
            session_id: sessionId,
            description: exp.description,
            strategy_name: exp.strategy_name,
            exact_match: exp.exact_match,
            within_1: exp.within_1,
            mae: exp.mae,
            bias: exp.bias,
            cost_usd: exp.cost_usd,
            n: exp.n,
            model: null,
            kept: exp.kept,
            per_question: exp.per_question as Record<string, { n: number; exact_match: number; mae: number }> | null,
            created_at: new Date().toISOString(),
          },
        ]);
        setActiveSession((prev) =>
          prev
            ? {
                ...prev,
                spent_usd: (data as Record<string, unknown>).spent_so_far as number,
                experiments_run: prev.experiments_run + 1,
                best_exact_match: Math.max(
                  prev.best_exact_match,
                  (exp.exact_match as number) ?? 0,
                ),
              }
            : prev,
        );
      } else if (event === "experiment_start") {
        // Could show a "running" indicator
      } else if (event === "session_complete") {
        setActiveSession((prev) =>
          prev ? { ...prev, status: (data as Record<string, unknown>).status as string } : prev,
        );
        toast.success("Research session completed!");
      } else if (event === "error") {
        setActiveSession((prev) => (prev ? { ...prev, status: "failed" } : prev));
        toast.error(`Session error: ${(data as Record<string, unknown>).message}`);
      }
    });

    cleanupRef.current = cleanup;
  }, []);

  // Clean up SSE on unmount
  useEffect(() => {
    return () => {
      if (cleanupRef.current) cleanupRef.current();
    };
  }, []);

  const handleStart = async () => {
    setStarting(true);
    try {
      const result = await startAutoresearchSession({
        budget_usd: budget,
        sample_size: sampleSize,
        model,
      });
      const newSession: AutoresearchSession = {
        id: result.session_id,
        status: "running",
        budget_usd: budget,
        spent_usd: 0,
        model,
        sample_size: sampleSize,
        experiments_run: 0,
        best_exact_match: 0,
        best_experiment_id: null,
        created_at: new Date().toISOString(),
        completed_at: null,
      };
      setActiveSession(newSession);
      setExperiments([]);
      setSessions((prev) => [newSession, ...prev]);
      subscribeToSession(result.session_id);
      toast.success("Research session started!");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start session");
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    if (!activeSession) return;
    try {
      await stopAutoresearchSession(activeSession.id);
      toast.info("Stopping session...");
    } catch (err) {
      toast.error("Failed to stop session");
    }
  };

  const isRunning = activeSession?.status === "running";
  const bestExperiment = experiments.find((e) => e.kept && e.exact_match === activeSession?.best_exact_match);

  // Per-question chart data from best experiment
  const perQuestionData = bestExperiment?.per_question
    ? Object.entries(bestExperiment.per_question)
        .map(([qn, m]) => ({
          question: qn.replace("Question ", "Q"),
          exact_match: m.exact_match,
          mae: m.mae,
          n: m.n,
        }))
        .sort((a, b) => a.question.localeCompare(b.question))
    : [];

  if (loading) {
    return (
      <AppShell>
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FlaskConical className="h-6 w-6 text-violet-500" />
            <div>
              <h1 className="text-2xl font-bold">Autoresearch</h1>
              <p className="text-sm text-muted-foreground">
                Autonomous strategy optimization for GCSE English marking
              </p>
            </div>
          </div>
          <Badge
            variant="outline"
            className="gap-1.5 border-violet-500/30 bg-violet-500/10 text-violet-600 dark:text-violet-400"
          >
            <Bot className="h-3.5 w-3.5" />
            {isRunning ? (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-violet-500" />
                </span>
                Autonomous Agent Running
              </>
            ) : (
              "Autonomous Agent"
            )}
          </Badge>
        </div>

        {/* Section 1: Session Control */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-4 w-4" />
              Research Session
            </CardTitle>
            <CardDescription>
              The agent will test multiple marking strategies and find the most
              accurate one within your budget.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isRunning ? (
              // Running state
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="text-sm font-medium">
                      Experiment {activeSession.experiments_run} running...
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Model: {activeSession.model} | Sample: {activeSession.sample_size} rows
                    </div>
                  </div>
                  <Button variant="destructive" size="sm" onClick={handleStop}>
                    <Square className="mr-1.5 h-3.5 w-3.5" />
                    Stop
                  </Button>
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between text-sm">
                    <span>Budget</span>
                    <span className="font-medium">
                      ${activeSession.spent_usd.toFixed(2)} / ${activeSession.budget_usd.toFixed(2)}
                    </span>
                  </div>
                  <Progress
                    value={(activeSession.spent_usd / activeSession.budget_usd) * 100}
                    className="h-2"
                  />
                </div>
              </div>
            ) : (
              // Config + start state
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="budget">Budget ($)</Label>
                    <Input
                      id="budget"
                      type="number"
                      min={1}
                      max={50}
                      value={budget}
                      onChange={(e) => setBudget(Number(e.target.value))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="sample">Sample Size</Label>
                    <Input
                      id="sample"
                      type="number"
                      min={10}
                      max={214}
                      value={sampleSize}
                      onChange={(e) => setSampleSize(Number(e.target.value))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Model</Label>
                    <Select value={model} onValueChange={setModel}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="gemini-2.5-pro">Gemini 2.5 Pro</SelectItem>
                        <SelectItem value="gemini-2.5-flash">Gemini 2.5 Flash</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <Button onClick={handleStart} disabled={starting} className="w-full">
                  {starting ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-2 h-4 w-4" />
                  )}
                  Start Research Session
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Section 2: Experiment Log */}
        {experiments.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Experiment Log</span>
                <Badge variant="secondary">
                  {experiments.length} experiments
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8">#</TableHead>
                    <TableHead>Strategy</TableHead>
                    <TableHead className="text-right">Exact %</TableHead>
                    <TableHead className="text-right">Within 1</TableHead>
                    <TableHead className="text-right">MAE</TableHead>
                    <TableHead className="text-right">Bias</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                    <TableHead className="text-center">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {experiments.map((exp, i) => {
                    const isBest =
                      exp.kept &&
                      exp.exact_match === activeSession?.best_exact_match;
                    return (
                      <TableRow
                        key={exp.id}
                        className={
                          exp.kept
                            ? "bg-emerald-500/5"
                            : "opacity-60"
                        }
                      >
                        <TableCell className="font-mono text-xs">
                          {i + 1}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {isBest && (
                              <Trophy className="h-3.5 w-3.5 text-amber-500" />
                            )}
                            <div>
                              <div className="font-medium text-sm">
                                {exp.description}
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {exp.strategy_name}
                              </div>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {exp.exact_match != null
                            ? `${exp.exact_match.toFixed(1)}%`
                            : "-"}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {exp.within_1 != null
                            ? `${exp.within_1.toFixed(1)}%`
                            : "-"}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {exp.mae != null ? exp.mae.toFixed(2) : "-"}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {exp.bias != null
                            ? `${exp.bias >= 0 ? "+" : ""}${exp.bias.toFixed(2)}`
                            : "-"}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          ${exp.cost_usd.toFixed(2)}
                        </TableCell>
                        <TableCell className="text-center">
                          {exp.kept ? (
                            <Badge
                              variant="outline"
                              className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                            >
                              <Check className="mr-1 h-3 w-3" />
                              Kept
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-muted-foreground">
                              <X className="mr-1 h-3 w-3" />
                              Discarded
                            </Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        {/* Section 3: Best Strategy + Per-Question Chart */}
        {bestExperiment && (
          <div className="grid gap-6 md:grid-cols-2">
            {/* Best strategy card */}
            <Card className="border-amber-500/30">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Trophy className="h-5 w-5 text-amber-500" />
                  Best Strategy
                </CardTitle>
                <CardDescription>{bestExperiment.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Exact Match</div>
                    <div className="text-2xl font-bold">
                      {bestExperiment.exact_match?.toFixed(1)}%
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Within 1 Mark</div>
                    <div className="text-2xl font-bold">
                      {bestExperiment.within_1?.toFixed(1)}%
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">MAE</div>
                    <div className="text-2xl font-bold">
                      {bestExperiment.mae?.toFixed(2)}
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Bias</div>
                    <div className="text-2xl font-bold">
                      {bestExperiment.bias != null
                        ? `${bestExperiment.bias >= 0 ? "+" : ""}${bestExperiment.bias.toFixed(2)}`
                        : "-"}
                    </div>
                  </div>
                </div>
                <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                  <DollarSign className="h-3 w-3" />
                  Cost: ${bestExperiment.cost_usd.toFixed(2)} | {bestExperiment.n} rows evaluated
                </div>
              </CardContent>
            </Card>

            {/* Per-question breakdown */}
            {perQuestionData.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Per-Question Exact Match %
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={perQuestionData}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                      <XAxis
                        dataKey="question"
                        className="text-xs"
                        tick={{ fontSize: 11 }}
                      />
                      <YAxis
                        domain={[0, 100]}
                        className="text-xs"
                        tick={{ fontSize: 11 }}
                      />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const d = payload[0].payload;
                          return (
                            <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
                              <div className="font-medium">{d.question}</div>
                              <div>Exact: {d.exact_match.toFixed(1)}%</div>
                              <div>MAE: {d.mae.toFixed(2)}</div>
                              <div>n={d.n}</div>
                            </div>
                          );
                        }}
                      />
                      <Bar dataKey="exact_match" fill="hsl(var(--chart-1))" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Session History */}
        {sessions.length > 1 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Session History</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {sessions.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => loadSessionDetail(s.id)}
                    className={`flex w-full items-center justify-between rounded-md border p-3 text-left text-sm transition-colors hover:bg-accent ${
                      activeSession?.id === s.id ? "border-primary bg-accent" : ""
                    }`}
                  >
                    <div>
                      <div className="font-medium">
                        {new Date(s.created_at).toLocaleDateString()} —{" "}
                        {s.experiments_run} experiments
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Best: {s.best_exact_match.toFixed(1)}% | Spent: $
                        {s.spent_usd.toFixed(2)} / ${s.budget_usd.toFixed(2)}
                      </div>
                    </div>
                    <Badge
                      variant={
                        s.status === "running"
                          ? "default"
                          : s.status === "completed"
                            ? "secondary"
                            : "destructive"
                      }
                    >
                      {s.status}
                    </Badge>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </AppShell>
  );
}

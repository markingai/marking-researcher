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
  ChevronRight,
  ChevronDown,
  FileText,
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
  Legend,
} from "recharts";

export default function AutoresearchPage() {
  const [sessions, setSessions] = useState<AutoresearchSession[]>([]);
  const [activeSession, setActiveSession] = useState<AutoresearchSession | null>(null);
  const [experiments, setExperiments] = useState<AutoresearchExperiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [expandedExperiment, setExpandedExperiment] = useState<string | null>(null);

  // Progress tracking
  const [currentProgress, setCurrentProgress] = useState<{
    experiment_id: string;
    rows_completed: number;
    rows_total: number;
  } | null>(null);

  // Config
  const [budget, setBudget] = useState(20);
  const [sampleSize, setSampleSize] = useState(50);
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
      if (event === "experiment_progress") {
        setCurrentProgress({
          experiment_id: data.experiment_id as string,
          rows_completed: data.rows_completed as number,
          rows_total: data.rows_total as number,
        });
      } else if (event === "experiment_start") {
        setCurrentProgress({
          experiment_id: data.experiment_id as string,
          rows_completed: 0,
          rows_total: data.rows_total as number || 0,
        });
      } else if (event === "experiment_complete") {
        setCurrentProgress(null);
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
            per_question: exp.per_question as AutoresearchExperiment["per_question"],
            prompt_text: (data as Record<string, unknown>).prompt_text as string || null,
            config_json: (data as Record<string, unknown>).config_json as string || null,
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
      } else if (event === "session_complete") {
        setCurrentProgress(null);
        setActiveSession((prev) =>
          prev
            ? {
                ...prev,
                status: (data as Record<string, unknown>).status as string,
                report_md: ((data as Record<string, unknown>).report_md as string) || null,
              }
            : prev,
        );
        toast.success("Research session completed!");
      } else if (event === "error") {
        setCurrentProgress(null);
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
        report_md: null,
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
    } catch {
      toast.error("Failed to stop session");
    }
  };

  const isRunning = activeSession?.status === "running";
  const isCompleted = activeSession?.status === "completed" || activeSession?.status === "stopped";
  const bestExperiment = experiments.find((e) => e.kept && e.exact_match === activeSession?.best_exact_match);

  // Per-question chart data from best experiment
  const perQuestionData = bestExperiment?.per_question
    ? Object.entries(bestExperiment.per_question)
        .map(([qn, m]) => ({
          question: qn.replace("Question ", "Q"),
          exact_match: m.exact_match,
          within_1: m.within_1 ?? 0,
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
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-500" />
                      {currentProgress ? (
                        <>
                          Experiment {activeSession.experiments_run + 1} — Evaluating row{" "}
                          {currentProgress.rows_completed}/{currentProgress.rows_total}
                        </>
                      ) : (
                        <>Experiment {activeSession.experiments_run + 1} — Starting...</>
                      )}
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

                {/* Row-level progress */}
                {currentProgress && currentProgress.rows_total > 0 && (
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>Evaluation progress</span>
                      <span>
                        {currentProgress.rows_completed}/{currentProgress.rows_total} rows
                      </span>
                    </div>
                    <Progress
                      value={(currentProgress.rows_completed / currentProgress.rows_total) * 100}
                      className="h-1.5"
                    />
                  </div>
                )}

                {/* Budget progress */}
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
        {(experiments.length > 0 || (isRunning && currentProgress)) && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>Experiment Log</span>
                <Badge variant="secondary">
                  {experiments.length} experiment{experiments.length !== 1 ? "s" : ""}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">#</TableHead>
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
                    const isExpanded = expandedExperiment === exp.id;
                    return (
                      <>
                        <TableRow
                          key={exp.id}
                          className={`cursor-pointer transition-colors ${
                            exp.kept
                              ? "bg-emerald-500/5 hover:bg-emerald-500/10"
                              : "opacity-60 hover:opacity-80"
                          }`}
                          onClick={() =>
                            setExpandedExperiment(isExpanded ? null : exp.id)
                          }
                        >
                          <TableCell className="font-mono text-xs">
                            <div className="flex items-center gap-1">
                              {isExpanded ? (
                                <ChevronDown className="h-3 w-3 text-muted-foreground" />
                              ) : (
                                <ChevronRight className="h-3 w-3 text-muted-foreground" />
                              )}
                              {i + 1}
                            </div>
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

                        {/* Expanded detail row */}
                        {isExpanded && (
                          <TableRow key={`${exp.id}-detail`}>
                            <TableCell colSpan={8} className="bg-muted/30 p-4">
                              <div className="space-y-4">
                                {/* System Prompt */}
                                <div>
                                  <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-2">
                                    System Prompt
                                  </h4>
                                  {exp.prompt_text ? (
                                    <pre className="whitespace-pre-wrap text-xs bg-background border rounded-md p-3 max-h-48 overflow-y-auto font-mono">
                                      {exp.prompt_text}
                                    </pre>
                                  ) : (
                                    <p className="text-xs text-muted-foreground italic">
                                      Prompt text not recorded for this experiment
                                    </p>
                                  )}
                                </div>

                                {/* Config */}
                                {exp.config_json && (
                                  <div>
                                    <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-2">
                                      Configuration
                                    </h4>
                                    <div className="flex flex-wrap gap-2">
                                      {Object.entries(
                                        JSON.parse(exp.config_json) as Record<string, unknown>
                                      ).map(([key, val]) => (
                                        <Badge key={key} variant="secondary" className="text-xs font-mono">
                                          {key}: {String(val)}
                                        </Badge>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* Per-question breakdown for this experiment */}
                                {exp.per_question && (
                                  <div>
                                    <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-2">
                                      Per-Question Breakdown
                                    </h4>
                                    <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                                      {Object.entries(exp.per_question)
                                        .sort(([a], [b]) => a.localeCompare(b))
                                        .map(([qn, m]) => (
                                          <div
                                            key={qn}
                                            className="rounded-md border bg-background p-2 text-center"
                                          >
                                            <div className="text-[10px] text-muted-foreground">
                                              {qn.replace("Question ", "Q")}
                                            </div>
                                            <div className="text-sm font-bold">
                                              {m.exact_match.toFixed(0)}%
                                            </div>
                                            <div className="text-[10px] text-muted-foreground">
                                              W/in 1: {m.within_1 != null ? `${m.within_1.toFixed(0)}%` : "N/A"}
                                            </div>
                                          </div>
                                        ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>
                        )}
                      </>
                    );
                  })}

                  {/* Running experiment placeholder row */}
                  {isRunning && currentProgress && (
                    <TableRow className="bg-violet-500/5">
                      <TableCell className="font-mono text-xs">
                        {experiments.length + 1}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-500" />
                          <div>
                            <div className="text-sm font-medium text-muted-foreground">
                              Running...
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {currentProgress.rows_completed}/{currentProgress.rows_total} rows evaluated
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell colSpan={6}>
                        <Progress
                          value={
                            (currentProgress.rows_completed / currentProgress.rows_total) * 100
                          }
                          className="h-1.5"
                        />
                      </TableCell>
                    </TableRow>
                  )}
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

            {/* Per-question breakdown — grouped bar chart */}
            {perQuestionData.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Per-Question Accuracy (Best Strategy)
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={220}>
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
                              <div>Within 1: {d.within_1.toFixed(1)}%</div>
                              <div>MAE: {d.mae.toFixed(2)}</div>
                              <div>n={d.n}</div>
                            </div>
                          );
                        }}
                      />
                      <Legend
                        wrapperStyle={{ fontSize: "11px" }}
                      />
                      <Bar
                        dataKey="exact_match"
                        name="Exact Match"
                        fill="hsl(var(--chart-1))"
                        radius={[4, 4, 0, 0]}
                      />
                      <Bar
                        dataKey="within_1"
                        name="Within 1 Mark"
                        fill="hsl(var(--chart-2))"
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Section 4: Session Report */}
        {isCompleted && activeSession?.report_md && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-violet-500" />
                Session Report
              </CardTitle>
              <CardDescription>
                Automated analysis of all strategies tested in this session
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReportRenderer markdown={activeSession.report_md} />
              </div>
            </CardContent>
          </Card>
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


// Simple Markdown renderer for the report (no external dependency)
function ReportRenderer({ markdown }: { markdown: string }) {
  const lines = markdown.split("\n");
  const elements: React.ReactNode[] = [];
  let tableRows: string[][] = [];
  let inTable = false;
  let tableIndex = 0;

  const flushTable = () => {
    if (tableRows.length === 0) return;
    const headers = tableRows[0];
    const body = tableRows.slice(2); // skip separator row
    elements.push(
      <div key={`table-${tableIndex}`} className="overflow-x-auto my-3">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th
                  key={i}
                  className="border-b border-border px-2 py-1.5 text-left font-semibold text-muted-foreground"
                >
                  {h.trim()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, ri) => (
              <tr key={ri} className="border-b border-border/50">
                {row.map((cell, ci) => (
                  <td key={ci} className="px-2 py-1.5">
                    {renderInline(cell.trim())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    tableRows = [];
    tableIndex++;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Table row detection
    if (line.startsWith("|")) {
      inTable = true;
      const cells = line
        .split("|")
        .slice(1, -1); // remove empty first/last from split
      tableRows.push(cells);
      continue;
    } else if (inTable) {
      inTable = false;
      flushTable();
    }

    // Headers
    if (line.startsWith("# ")) {
      elements.push(
        <h2 key={i} className="text-lg font-bold mt-4 mb-2">
          {line.slice(2)}
        </h2>
      );
    } else if (line.startsWith("## ")) {
      elements.push(
        <h3 key={i} className="text-base font-semibold mt-4 mb-2 text-foreground">
          {line.slice(3)}
        </h3>
      );
    } else if (line.startsWith("- ")) {
      elements.push(
        <div key={i} className="flex gap-2 text-sm pl-2 py-0.5">
          <span className="text-muted-foreground">•</span>
          <span>{renderInline(line.slice(2))}</span>
        </div>
      );
    } else if (line.match(/^\d+\. /)) {
      const match = line.match(/^(\d+)\. (.*)$/);
      if (match) {
        elements.push(
          <div key={i} className="flex gap-2 text-sm pl-2 py-0.5">
            <span className="text-muted-foreground font-mono">{match[1]}.</span>
            <span>{renderInline(match[2])}</span>
          </div>
        );
      }
    } else if (line.trim() === "") {
      // skip
    } else {
      elements.push(
        <p key={i} className="text-sm py-0.5">
          {renderInline(line)}
        </p>
      );
    }
  }

  // Flush any remaining table
  if (inTable) flushTable();

  return <>{elements}</>;
}

// Inline formatting (bold, code, etc.)
function renderInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let keyIdx = 0;

  while (remaining.length > 0) {
    // Bold: **text**
    const boldMatch = remaining.match(/\*\*(.+?)\*\*/);
    // Code: `text`
    const codeMatch = remaining.match(/`(.+?)`/);

    // Find earliest match
    const boldIdx = boldMatch?.index ?? Infinity;
    const codeIdx = codeMatch?.index ?? Infinity;

    if (boldIdx === Infinity && codeIdx === Infinity) {
      parts.push(remaining);
      break;
    }

    if (boldIdx <= codeIdx && boldMatch) {
      parts.push(remaining.slice(0, boldIdx));
      parts.push(
        <strong key={keyIdx++} className="font-semibold">
          {boldMatch[1]}
        </strong>
      );
      remaining = remaining.slice(boldIdx + boldMatch[0].length);
    } else if (codeMatch) {
      parts.push(remaining.slice(0, codeIdx));
      parts.push(
        <code key={keyIdx++} className="rounded bg-muted px-1 py-0.5 text-xs font-mono">
          {codeMatch[1]}
        </code>
      );
      remaining = remaining.slice(codeIdx + codeMatch[0].length);
    }
  }

  return parts.length === 1 ? parts[0] : <>{parts}</>;
}

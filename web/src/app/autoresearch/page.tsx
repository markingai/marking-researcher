"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
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
  Medal,
  TrendingUp,
  Sparkles,
  Clock,
} from "lucide-react";
import { toast } from "sonner";
import {
  startAutoresearchSession,
  getAutoresearchSessions,
  getAutoresearchSession,
  stopAutoresearchSession,
  subscribeToAutoresearchEvents,
  getAutoresearchLeaderboard,
  getAutoresearchTimeline,
  type AutoresearchSession,
  type AutoresearchExperiment,
  type LeaderboardEntry,
  type TimelineEntry,
} from "@/lib/api";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
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
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [activeTab, setActiveTab] = useState("session");
  const [expandedLeaderboardRow, setExpandedLeaderboardRow] = useState<string | null>(null);

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

  // Load sessions + leaderboard on mount
  useEffect(() => {
    loadSessions();
    loadLeaderboard();
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

  const loadLeaderboard = async () => {
    try {
      const [lb, tl] = await Promise.all([
        getAutoresearchLeaderboard(),
        getAutoresearchTimeline(),
      ]);
      setLeaderboard(lb);
      setTimeline(tl);
    } catch {
      // No data yet
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
        loadLeaderboard();
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
        session_number: (sessions.length > 0 ? Math.max(...sessions.map(s => s.session_number ?? 0)) + 1 : 1),
        parent_session_id: null,
      };
      setActiveSession(newSession);
      setExperiments([]);
      setSessions((prev) => [newSession, ...prev]);
      subscribeToSession(result.session_id);
      setActiveTab("session");
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

  const handleViewSession = (sessionId: string) => {
    loadSessionDetail(sessionId);
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

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="session">
              {isRunning && (
                <span className="relative flex h-2 w-2 mr-1">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-violet-500" />
                </span>
              )}
              Current Session
            </TabsTrigger>
            <TabsTrigger value="leaderboard">
              <Medal className="h-3.5 w-3.5 mr-1" />
              Leaderboard
              {leaderboard.length > 0 && (
                <Badge variant="secondary" className="ml-1.5 h-5 px-1.5 text-[10px]">
                  {leaderboard.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="history">
              <Clock className="h-3.5 w-3.5 mr-1" />
              History
              {sessions.length > 0 && (
                <Badge variant="secondary" className="ml-1.5 h-5 px-1.5 text-[10px]">
                  {sessions.length}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>

          {/* ===== TAB: Current Session ===== */}
          <TabsContent value="session">
            <div className="space-y-6">
              {/* Session Control */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Zap className="h-4 w-4" />
                    Research Session
                    {activeSession?.session_number && (
                      <Badge variant="outline" className="ml-1 text-xs">
                        #{activeSession.session_number}
                      </Badge>
                    )}
                  </CardTitle>
                  <CardDescription className="flex items-center gap-2">
                    <span>
                      The agent will test multiple marking strategies and find the most
                      accurate one within your budget.
                    </span>
                    {activeSession?.parent_session_id && (
                      <Badge variant="secondary" className="gap-1 text-xs shrink-0">
                        <Sparkles className="h-3 w-3" />
                        Building on prior findings
                      </Badge>
                    )}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {isRunning ? (
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
                              <SelectItem value="gemini-3.1-pro-preview">Gemini 3.1 Pro</SelectItem>
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

              {/* Experiment Log */}
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

                              {isExpanded && (
                                <TableRow key={`${exp.id}-detail`}>
                                  <TableCell colSpan={8} className="bg-muted/30 p-4">
                                    <div className="space-y-4">
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

              {/* Best Strategy + Per-Question Chart */}
              {bestExperiment && (
                <div className="grid gap-6 md:grid-cols-2">
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

              {/* Start Next Session CTA */}
              {isCompleted && !isRunning && (
                <Card className="border-violet-500/30 bg-violet-500/5">
                  <CardContent className="py-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <Sparkles className="h-5 w-5 text-violet-500" />
                        <div>
                          <div className="font-medium text-sm">Ready for next session</div>
                          <div className="text-xs text-muted-foreground">
                            The next session will build on findings from Session #{activeSession?.session_number ?? "?"} —
                            testing variations of winners, untested strategies, and novel hybrids.
                          </div>
                        </div>
                      </div>
                      <Button onClick={handleStart} disabled={starting} size="sm">
                        {starting ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Play className="mr-2 h-4 w-4" />
                        )}
                        Start Next Session
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>

          {/* ===== TAB: Leaderboard ===== */}
          <TabsContent value="leaderboard">
            <div className="space-y-6">
              {leaderboard.length > 0 ? (
                <>
                  {/* All-Time Leaderboard */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Medal className="h-5 w-5 text-amber-500" />
                        All-Time Strategy Leaderboard
                      </CardTitle>
                      <CardDescription>
                        Cross-session rankings — best strategies across all research sessions
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-10">#</TableHead>
                            <TableHead>Strategy</TableHead>
                            <TableHead className="text-right">Best Exact%</TableHead>
                            <TableHead className="text-right">Avg Exact%</TableHead>
                            <TableHead className="text-right">Avg W/in 1%</TableHead>
                            <TableHead className="text-right">Avg MAE</TableHead>
                            <TableHead className="text-right">Avg Cost</TableHead>
                            <TableHead className="text-right">Tested</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {leaderboard.map((entry, i) => {
                            const isLbExpanded = expandedLeaderboardRow === entry.strategy_name;
                            return (
                              <>
                                <TableRow
                                  key={entry.strategy_name}
                                  className={`cursor-pointer transition-colors ${i === 0 ? "bg-amber-500/5 hover:bg-amber-500/10" : i < 3 ? "bg-muted/30 hover:bg-muted/50" : "hover:bg-accent"}`}
                                  onClick={() => setExpandedLeaderboardRow(isLbExpanded ? null : entry.strategy_name)}
                                >
                                  <TableCell className="font-mono text-xs">
                                    <div className="flex items-center gap-1">
                                      {isLbExpanded ? (
                                        <ChevronDown className="h-3 w-3 text-muted-foreground" />
                                      ) : (
                                        <ChevronRight className="h-3 w-3 text-muted-foreground" />
                                      )}
                                      {i === 0 ? (
                                        <Trophy className="h-4 w-4 text-amber-500" />
                                      ) : i === 1 ? (
                                        <Medal className="h-4 w-4 text-slate-400" />
                                      ) : i === 2 ? (
                                        <Medal className="h-4 w-4 text-amber-700" />
                                      ) : (
                                        <span className="pl-1">{i + 1}</span>
                                      )}
                                    </div>
                                  </TableCell>
                                  <TableCell>
                                    <div className="font-medium text-sm">{entry.strategy_name}</div>
                                    <div className="text-xs text-muted-foreground truncate max-w-[300px]">
                                      {entry.description}
                                    </div>
                                  </TableCell>
                                  <TableCell className="text-right font-mono font-bold">
                                    {entry.best_exact_match.toFixed(1)}%
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    {entry.avg_exact_match.toFixed(1)}%
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    {entry.avg_within_1.toFixed(1)}%
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    {entry.avg_mae.toFixed(2)}
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    ${entry.avg_cost_usd.toFixed(2)}
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    {entry.times_tested}x
                                  </TableCell>
                                </TableRow>
                                {isLbExpanded && (
                                  <TableRow key={`${entry.strategy_name}-detail`}>
                                    <TableCell colSpan={8} className="bg-muted/30 p-4">
                                      <div className="space-y-2">
                                        <h4 className="text-xs font-semibold uppercase text-muted-foreground">
                                          Full Description
                                        </h4>
                                        <p className="text-sm whitespace-pre-wrap">
                                          {entry.description}
                                        </p>
                                        <div className="flex gap-4 text-xs text-muted-foreground pt-1">
                                          {entry.first_tested && (
                                            <span>First tested: {new Date(entry.first_tested).toLocaleDateString()}</span>
                                          )}
                                          {entry.last_tested && (
                                            <span>Last tested: {new Date(entry.last_tested).toLocaleDateString()}</span>
                                          )}
                                          <span>Avg bias: {entry.avg_bias >= 0 ? "+" : ""}{entry.avg_bias.toFixed(2)}</span>
                                        </div>
                                      </div>
                                    </TableCell>
                                  </TableRow>
                                )}
                              </>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>

                  {/* Improvement Timeline */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <TrendingUp className="h-5 w-5 text-emerald-500" />
                        Improvement Over Time
                      </CardTitle>
                      <CardDescription>
                        Best exact match achieved per session — tracking convergence toward optimal strategy
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      {timeline.length > 0 ? (
                        <ResponsiveContainer width="100%" height={280}>
                          <LineChart data={timeline.map(t => ({
                            session: t.session_number ? `#${t.session_number}` : `#${timeline.indexOf(t) + 1}`,
                            date: new Date(t.created_at).toLocaleDateString(),
                            best_exact: t.best_exact_match,
                            experiments: t.experiments_run,
                            spent: t.spent_usd,
                          }))}>
                            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                            <XAxis dataKey="session" tick={{ fontSize: 11 }} />
                            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                            <Tooltip
                              content={({ active, payload }) => {
                                if (!active || !payload?.length) return null;
                                const d = payload[0].payload as { session: string; date: string; best_exact: number; experiments: number; spent: number };
                                return (
                                  <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
                                    <div className="font-medium">Session {d.session}</div>
                                    <div className="text-muted-foreground">{d.date}</div>
                                    <div>Best: {d.best_exact.toFixed(1)}%</div>
                                    <div>{d.experiments} experiments</div>
                                    <div>Spent: ${d.spent.toFixed(2)}</div>
                                  </div>
                                );
                              }}
                            />
                            <Line
                              type="monotone"
                              dataKey="best_exact"
                              name="Best Exact %"
                              stroke="hsl(142, 71%, 45%)"
                              strokeWidth={2.5}
                              dot={{ fill: "hsl(142, 71%, 45%)", r: 5, strokeWidth: 0 }}
                              connectNulls
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      ) : (
                        <p className="text-sm text-muted-foreground text-center py-8">
                          Complete sessions to see trends
                        </p>
                      )}
                    </CardContent>
                  </Card>
                </>
              ) : (
                <Card>
                  <CardContent className="py-12 text-center">
                    <Medal className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
                    <p className="text-sm text-muted-foreground">
                      No strategies tested yet. Run your first research session to populate the leaderboard.
                    </p>
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>

          {/* ===== TAB: History ===== */}
          <TabsContent value="history">
            <div className="space-y-6">
              {sessions.length > 0 ? (
                <>
                  {/* Session List */}
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">All Sessions</CardTitle>
                      <CardDescription>
                        Click a session to view its experiments and report
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {sessions.map((s) => (
                          <button
                            key={s.id}
                            onClick={() => handleViewSession(s.id)}
                            className={`flex w-full items-center justify-between rounded-md border p-3 text-left text-sm transition-colors hover:bg-accent ${
                              activeSession?.id === s.id ? "border-primary bg-accent" : ""
                            }`}
                          >
                            <div>
                              <div className="font-medium">
                                {s.session_number ? `Session #${s.session_number} — ` : ""}
                                {new Date(s.created_at).toLocaleDateString()} —{" "}
                                {s.experiments_run} experiments
                              </div>
                              <div className="text-xs text-muted-foreground">
                                Best: {s.best_exact_match.toFixed(1)}% | Spent: $
                                {s.spent_usd.toFixed(2)} / ${s.budget_usd.toFixed(2)}
                                {s.model ? ` | ${s.model}` : ""}
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

                  {/* Selected session summary */}
                  {activeSession && experiments.length > 0 && (
                    <Card>
                      <CardHeader>
                        <CardTitle className="flex items-center justify-between">
                          <span className="flex items-center gap-2">
                            Experiments
                            {activeSession.session_number && (
                              <Badge variant="outline" className="text-xs">
                                Session #{activeSession.session_number}
                              </Badge>
                            )}
                          </span>
                          <div className="flex items-center gap-3 text-sm text-muted-foreground">
                            <span>Best: {activeSession.best_exact_match.toFixed(1)}%</span>
                            <span>${activeSession.spent_usd.toFixed(2)}</span>
                            <Badge variant="secondary">
                              {experiments.length} experiment{experiments.length !== 1 ? "s" : ""}
                            </Badge>
                          </div>
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
                              const isBest = exp.kept && exp.exact_match === activeSession.best_exact_match;
                              return (
                                <TableRow
                                  key={exp.id}
                                  className={exp.kept ? "bg-emerald-500/5" : "opacity-60"}
                                >
                                  <TableCell className="font-mono text-xs">{i + 1}</TableCell>
                                  <TableCell>
                                    <div className="flex items-center gap-2">
                                      {isBest && <Trophy className="h-3.5 w-3.5 text-amber-500" />}
                                      <div>
                                        <div className="font-medium text-sm">{exp.description}</div>
                                        <div className="text-xs text-muted-foreground">{exp.strategy_name}</div>
                                      </div>
                                    </div>
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    {exp.exact_match != null ? `${exp.exact_match.toFixed(1)}%` : "-"}
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    {exp.within_1 != null ? `${exp.within_1.toFixed(1)}%` : "-"}
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    {exp.mae != null ? exp.mae.toFixed(2) : "-"}
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    {exp.bias != null ? `${exp.bias >= 0 ? "+" : ""}${exp.bias.toFixed(2)}` : "-"}
                                  </TableCell>
                                  <TableCell className="text-right font-mono">
                                    ${exp.cost_usd.toFixed(2)}
                                  </TableCell>
                                  <TableCell className="text-center">
                                    {exp.kept ? (
                                      <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                                        <Check className="mr-1 h-3 w-3" />Kept
                                      </Badge>
                                    ) : (
                                      <Badge variant="outline" className="text-muted-foreground">
                                        <X className="mr-1 h-3 w-3" />Discarded
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

                  {/* Session Report for selected session */}
                  {activeSession?.report_md && (
                    <Card>
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                          <FileText className="h-5 w-5 text-violet-500" />
                          Session Report
                          {activeSession.session_number && (
                            <Badge variant="outline" className="ml-1 text-xs">
                              #{activeSession.session_number}
                            </Badge>
                          )}
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
                </>
              ) : (
                <Card>
                  <CardContent className="py-12 text-center">
                    <Clock className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
                    <p className="text-sm text-muted-foreground">
                      No sessions yet. Start your first research session from the Current Session tab.
                    </p>
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>
        </Tabs>
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

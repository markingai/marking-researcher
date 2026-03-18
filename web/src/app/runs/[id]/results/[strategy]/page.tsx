"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { ArrowLeft } from "lucide-react";
import {
  getResultsDetail,
  type ResultsDetail,
  type EvalResultDetail,
} from "@/lib/api";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  Legend,
} from "recharts";

export default function StrategyDrillDownPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;
  const strategy = decodeURIComponent(params.strategy as string);

  const [data, setData] = useState<ResultsDetail | null>(null);
  const [page, setPage] = useState(1);
  const [showErrorsOnly, setShowErrorsOnly] = useState(false);
  const [selectedResult, setSelectedResult] = useState<EvalResultDetail | null>(
    null,
  );

  useEffect(() => {
    getResultsDetail(runId, { strategy, page, per_page: 50 })
      .then(setData)
      .catch(() => {});
  }, [runId, strategy, page]);

  if (!data) return <AppShell><p>Loading...</p></AppShell>;

  const filteredResults = showErrorsOnly
    ? data.results.filter((r) => !r.exact_match)
    : data.results;

  // Build score distribution data
  const scoreDistribution = buildScoreDistribution(data.results);
  // Build error distribution data
  const errorDistribution = buildErrorDistribution(data.results);

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-semibold">{strategy}</h1>
            <p className="text-sm text-muted-foreground">
              {data.total} results
            </p>
          </div>
        </div>

        {/* Per-question metrics */}
        {data.per_question_metrics.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Per-Question Metrics</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Question</TableHead>
                    <TableHead className="text-right">N</TableHead>
                    <TableHead className="text-right">Exact%</TableHead>
                    <TableHead className="text-right">Within 1%</TableHead>
                    <TableHead className="text-right">MAE</TableHead>
                    <TableHead className="text-right">Bias</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.per_question_metrics.map((q) => (
                    <TableRow key={q.question_number}>
                      <TableCell className="font-medium">Q{q.question_number}</TableCell>
                      <TableCell className="text-right">{q.metrics.n}</TableCell>
                      <TableCell className="text-right">{q.metrics.exact_match_pct}%</TableCell>
                      <TableCell className="text-right">{q.metrics.within_1_pct}%</TableCell>
                      <TableCell className="text-right">{q.metrics.mae}</TableCell>
                      <TableCell className="text-right">
                        {q.metrics.mean_signed_error > 0 ? "+" : ""}
                        {q.metrics.mean_signed_error}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        {/* Score Distribution */}
        {scoreDistribution.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Score Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={scoreDistribution} barGap={0}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                    <XAxis dataKey="mark" label={{ value: "Mark", position: "insideBottom", offset: -5 }} />
                    <YAxis label={{ value: "Count", angle: -90, position: "insideLeft" }} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="human" name="Human" fill="#6366f1" opacity={0.7} />
                    <Bar dataKey="ai" name="AI" fill="#f97316" opacity={0.7} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Error Distribution + Confusion Matrix side by side */}
        <div className="grid gap-6 md:grid-cols-2">
          {/* Error Distribution */}
          {errorDistribution.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Error Distribution</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={errorDistribution}>
                      <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                      <XAxis dataKey="error" label={{ value: "Signed Error (AI - Human)", position: "insideBottom", offset: -5 }} />
                      <YAxis label={{ value: "Count", angle: -90, position: "insideLeft" }} />
                      <Tooltip />
                      <Bar dataKey="count" name="Count">
                        {errorDistribution.map((entry, index) => (
                          <Cell
                            key={index}
                            fill={
                              entry.error === 0
                                ? "#22c55e"
                                : entry.error > 0
                                  ? "#f97316"
                                  : "#3b82f6"
                            }
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-2 flex justify-center gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-blue-500" /> Under-marking
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-green-500" /> Exact
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-full bg-orange-500" /> Over-marking
                  </span>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Confusion matrix */}
          {data.confusion_matrix.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Confusion Matrix</CardTitle>
              </CardHeader>
              <CardContent>
                <ConfusionMatrix entries={data.confusion_matrix} />
              </CardContent>
            </Card>
          )}
        </div>

        {/* Per-answer table */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Individual Results</CardTitle>
              <Button
                variant={showErrorsOnly ? "default" : "outline"}
                size="sm"
                onClick={() => setShowErrorsOnly(!showErrorsOnly)}
              >
                {showErrorsOnly ? "Show All" : "Discrepancies Only"}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Row ID</TableHead>
                    <TableHead>Question</TableHead>
                    <TableHead className="text-right">Human</TableHead>
                    <TableHead className="text-right">AI</TableHead>
                    <TableHead className="text-right">Error</TableHead>
                    <TableHead>Justification</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredResults.map((r) => (
                    <TableRow
                      key={`${r.row_id}-${r.question_number}`}
                      className={`cursor-pointer hover:bg-accent ${
                        selectedResult?.row_id === r.row_id &&
                        selectedResult?.question_number === r.question_number
                          ? "bg-accent"
                          : ""
                      }`}
                      onClick={() => setSelectedResult(r)}
                    >
                      <TableCell className="font-mono text-xs">{r.row_id}</TableCell>
                      <TableCell>Q{r.question_number}</TableCell>
                      <TableCell className="text-right">{r.human_mark}</TableCell>
                      <TableCell className="text-right">{r.ai_mark}</TableCell>
                      <TableCell className="text-right">
                        <span
                          className={
                            Math.abs(r.signed_error) === 0
                              ? "text-green-600"
                              : Math.abs(r.signed_error) <= 1
                                ? "text-yellow-600"
                                : "text-red-600 font-medium"
                          }
                        >
                          {r.signed_error > 0 ? "+" : ""}
                          {r.signed_error}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className="line-clamp-1 max-w-xs text-xs text-muted-foreground">
                          {r.justification?.slice(0, 80) || "\u2014"}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {data.total > 50 && (
              <div className="mt-4 flex justify-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </Button>
                <span className="flex items-center text-sm text-muted-foreground">
                  Page {page} of {Math.ceil(data.total / 50)}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page * 50 >= data.total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Result Detail Drawer */}
      <Sheet
        open={selectedResult !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedResult(null);
        }}
      >
        <SheetContent
          side="right"
          className="w-full sm:max-w-lg overflow-y-auto"
        >
          {selectedResult && (
            <>
              <SheetHeader className="border-b pb-4">
                <SheetTitle>
                  Q{selectedResult.question_number} — Row {selectedResult.row_id}
                </SheetTitle>
                <SheetDescription>
                  {selectedResult.total_marks} marks available
                </SheetDescription>
              </SheetHeader>

              <div className="space-y-6 p-4">
                {/* Mark comparison */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="rounded-lg border p-3 text-center">
                    <div className="text-xs text-muted-foreground">Human</div>
                    <div className="text-2xl font-bold">{selectedResult.human_mark}</div>
                  </div>
                  <div className="rounded-lg border p-3 text-center">
                    <div className="text-xs text-muted-foreground">AI</div>
                    <div className="text-2xl font-bold">{selectedResult.ai_mark}</div>
                  </div>
                  <div className="rounded-lg border p-3 text-center">
                    <div className="text-xs text-muted-foreground">Error</div>
                    <div
                      className={`text-2xl font-bold ${
                        Math.abs(selectedResult.signed_error) === 0
                          ? "text-green-600"
                          : Math.abs(selectedResult.signed_error) <= 1
                            ? "text-yellow-600"
                            : "text-red-600"
                      }`}
                    >
                      {selectedResult.signed_error > 0 ? "+" : ""}
                      {selectedResult.signed_error}
                    </div>
                  </div>
                </div>

                {/* Status badge */}
                <div className="flex items-center gap-2">
                  <Badge
                    variant={
                      selectedResult.exact_match ? "default" : "destructive"
                    }
                  >
                    {selectedResult.exact_match ? "Exact Match" : "Discrepancy"}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    Cost: ${selectedResult.cost_usd.toFixed(4)}
                  </span>
                </div>

                {/* Justification */}
                {selectedResult.justification && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold">Justification</h3>
                    <div className="rounded-lg border bg-muted/30 p-4 text-sm leading-relaxed whitespace-pre-wrap">
                      {selectedResult.justification}
                    </div>
                  </div>
                )}

                {/* Criteria breakdown */}
                {selectedResult.criteria_breakdown && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold">Criteria Breakdown</h3>
                    <CriteriaBreakdown raw={selectedResult.criteria_breakdown} />
                  </div>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </AppShell>
  );
}

/**
 * Render criteria breakdown as structured cards if JSON, or formatted text if plain string.
 */
function CriteriaBreakdown({ raw }: { raw: string }) {
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return (
        <div className="space-y-2">
          {parsed.map((c: { criterion?: string; marks_awarded?: number; max_marks?: number; reason?: string }, i: number) => (
            <div key={i} className="rounded-lg border p-3 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{c.criterion || `Criterion ${i + 1}`}</span>
                <Badge variant="outline" className="font-mono">
                  {c.marks_awarded ?? "?"}/{c.max_marks ?? "?"}
                </Badge>
              </div>
              {c.reason && (
                <p className="text-xs text-muted-foreground leading-relaxed">{c.reason}</p>
              )}
            </div>
          ))}
        </div>
      );
    }
    // Object with criteria array
    if (parsed.criteria && Array.isArray(parsed.criteria)) {
      return (
        <div className="space-y-2">
          {parsed.criteria.map((c: { criterion?: string; marks_awarded?: number; max_marks?: number; reason?: string }, i: number) => (
            <div key={i} className="rounded-lg border p-3 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{c.criterion || `Criterion ${i + 1}`}</span>
                <Badge variant="outline" className="font-mono">
                  {c.marks_awarded ?? "?"}/{c.max_marks ?? "?"}
                </Badge>
              </div>
              {c.reason && (
                <p className="text-xs text-muted-foreground leading-relaxed">{c.reason}</p>
              )}
            </div>
          ))}
        </div>
      );
    }
  } catch {
    // Not JSON — fall through to plain text
  }

  // Semicolon-separated or plain text fallback
  return (
    <div className="rounded-lg border bg-muted/30 p-4 text-sm leading-relaxed whitespace-pre-wrap">
      {raw}
    </div>
  );
}

function ConfusionMatrix({
  entries,
}: {
  entries: { human_mark: number; ai_mark: number; count: number }[];
}) {
  const humanMarks = [...new Set(entries.map((e) => e.human_mark))].sort((a, b) => a - b);
  const aiMarks = [...new Set(entries.map((e) => e.ai_mark))].sort((a, b) => a - b);
  const allMarks = [...new Set([...humanMarks, ...aiMarks])].sort((a, b) => a - b);

  const lookup: Record<string, number> = {};
  entries.forEach((e) => {
    lookup[`${e.human_mark}-${e.ai_mark}`] = e.count;
  });

  const maxCount = Math.max(...entries.map((e) => e.count), 1);

  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1 text-muted-foreground">H \ AI</th>
            {allMarks.map((m) => (
              <th key={m} className="px-2 py-1 text-center font-medium">
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {allMarks.map((h) => (
            <tr key={h}>
              <td className="px-2 py-1 font-medium">{h}</td>
              {allMarks.map((a) => {
                const count = lookup[`${h}-${a}`] || 0;
                const intensity = count / maxCount;
                const isDiagonal = h === a;
                return (
                  <td
                    key={a}
                    className="px-2 py-1 text-center"
                    style={{
                      backgroundColor: count > 0
                        ? isDiagonal
                          ? `rgba(34, 197, 94, ${0.1 + intensity * 0.5})`
                          : `rgba(239, 68, 68, ${0.1 + intensity * 0.4})`
                        : "transparent",
                    }}
                  >
                    {count || ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Build score distribution histogram data from results.
 */
function buildScoreDistribution(results: EvalResultDetail[]): { mark: number; human: number; ai: number }[] {
  const humanCounts: Record<number, number> = {};
  const aiCounts: Record<number, number> = {};

  for (const r of results) {
    humanCounts[r.human_mark] = (humanCounts[r.human_mark] || 0) + 1;
    if (r.ai_mark >= 0) {
      aiCounts[r.ai_mark] = (aiCounts[r.ai_mark] || 0) + 1;
    }
  }

  const allMarks = new Set([
    ...Object.keys(humanCounts).map(Number),
    ...Object.keys(aiCounts).map(Number),
  ]);

  return [...allMarks]
    .sort((a, b) => a - b)
    .map((mark) => ({
      mark,
      human: humanCounts[mark] || 0,
      ai: aiCounts[mark] || 0,
    }));
}

/**
 * Build error distribution histogram data from results.
 */
function buildErrorDistribution(results: EvalResultDetail[]): { error: number; count: number }[] {
  const counts: Record<number, number> = {};
  for (const r of results) {
    if (r.ai_mark >= 0) {
      const err = r.signed_error;
      counts[err] = (counts[err] || 0) + 1;
    }
  }

  return Object.entries(counts)
    .map(([error, count]) => ({ error: Number(error), count }))
    .sort((a, b) => a.error - b.error);
}

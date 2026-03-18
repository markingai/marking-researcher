"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
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
import { ArrowLeft } from "lucide-react";
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
import { getResultsSummary, getRun, type ResultsSummary, type RunDetail } from "@/lib/api";

export default function ResultsOverviewPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;

  const [run, setRun] = useState<RunDetail | null>(null);
  const [summary, setSummary] = useState<ResultsSummary | null>(null);

  useEffect(() => {
    getRun(runId).then(setRun).catch(() => {});
    getResultsSummary(runId).then(setSummary).catch(() => {});
  }, [runId]);

  if (!summary || !run)
    return (
      <AppShell>
        <p>Loading results...</p>
      </AppShell>
    );

  const chartData = summary.strategies.map((s) => ({
    name: s.name.replace(/^(maths_|english_)/, ""),
    "Exact Match %": s.metrics.exact_match_pct,
    "Within 1 %": s.metrics.within_1_pct,
    MAE: s.metrics.mae,
  }));

  // Bias analysis data
  const biasData = summary.strategies.map((s) => ({
    name: s.name.replace(/^(maths_|english_)/, ""),
    bias: s.metrics.mean_signed_error,
    over: s.metrics.over_mark_pct,
    under: -s.metrics.under_mark_pct,
  }));

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-semibold">Results</h1>
            <p className="text-sm text-muted-foreground">
              {run.name || run.id.slice(0, 8)} &middot; {summary.total_evaluated} rows
              &middot; ${summary.total_cost_usd.toFixed(4)}
            </p>
          </div>
        </div>

        {/* Summary stat cards */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Card>
            <CardContent className="pt-6 text-center">
              <div className="text-2xl font-bold">{summary.strategies.length}</div>
              <div className="text-xs text-muted-foreground">Strategies</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <div className="text-2xl font-bold">{summary.total_evaluated}</div>
              <div className="text-xs text-muted-foreground">Evaluations</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <div className="text-2xl font-bold text-green-600">
                {summary.best_strategy
                  ? summary.strategies.find((s) => s.name === summary.best_strategy)?.metrics.exact_match_pct + "%"
                  : "N/A"}
              </div>
              <div className="text-xs text-muted-foreground">Best Exact%</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <div className="text-2xl font-bold">${summary.total_cost_usd.toFixed(2)}</div>
              <div className="text-xs text-muted-foreground">Total Cost</div>
            </CardContent>
          </Card>
        </div>

        {/* Accuracy chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Accuracy Comparison</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} angle={-20} textAnchor="end" height={60} />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="Exact Match %" fill="hsl(221, 83%, 53%)" radius={[4, 4, 0, 0]}>
                    {chartData.map((_, i) => (
                      <Cell
                        key={i}
                        fill={
                          summary.strategies[i].name === summary.best_strategy
                            ? "hsl(142, 71%, 45%)"
                            : "hsl(221, 83%, 53%)"
                        }
                      />
                    ))}
                  </Bar>
                  <Bar dataKey="Within 1 %" fill="hsl(221, 83%, 73%)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Bias Analysis */}
        {biasData.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Bias Analysis</CardTitle>
              <p className="text-xs text-muted-foreground">
                Positive bias = over-marking, Negative = under-marking
              </p>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={biasData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                    <XAxis type="number" domain={["auto", "auto"]} />
                    <YAxis
                      dataKey="name"
                      type="category"
                      tick={{ fontSize: 11 }}
                      width={140}
                    />
                    <Tooltip
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      formatter={(value: any) =>
                        typeof value === "number"
                          ? (value > 0 ? "+" : "") + value.toFixed(3)
                          : String(value ?? "")
                      }
                    />
                    <Legend />
                    <Bar dataKey="over" name="Over-marking %" fill="#f97316" stackId="stack" />
                    <Bar dataKey="under" name="Under-marking %" fill="#3b82f6" stackId="stack" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {/* Bias summary badges */}
              <div className="mt-4 flex flex-wrap gap-2">
                {summary.strategies.map((s) => {
                  const bias = s.metrics.mean_signed_error;
                  const absBias = Math.abs(bias);
                  return (
                    <div
                      key={s.name}
                      className="flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs"
                    >
                      <span className="font-medium">{s.name.replace(/^(maths_|english_)/, "")}</span>
                      <span
                        className={
                          absBias < 0.3
                            ? "text-green-600"
                            : bias > 0
                              ? "text-orange-500"
                              : "text-blue-500"
                        }
                      >
                        {bias > 0 ? "+" : ""}{bias}
                      </span>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Strategy comparison table */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Strategy Comparison</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Strategy</TableHead>
                    <TableHead className="text-right">N</TableHead>
                    <TableHead className="text-right">Exact%</TableHead>
                    <TableHead className="text-right">Within 1%</TableHead>
                    <TableHead className="text-right">MAE</TableHead>
                    <TableHead className="text-right">Bias</TableHead>
                    <TableHead className="text-right">Over%</TableHead>
                    <TableHead className="text-right">Under%</TableHead>
                    <TableHead className="text-right">Errors</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summary.strategies.map((s) => (
                    <TableRow key={s.name}>
                      <TableCell>
                        <Link
                          href={`/runs/${runId}/results/${encodeURIComponent(s.name)}`}
                          className="font-medium hover:underline"
                        >
                          {s.name}
                        </Link>
                        {s.name === summary.best_strategy && (
                          <Badge variant="default" className="ml-2 text-xs">
                            Best
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">{s.metrics.n}</TableCell>
                      <TableCell className="text-right font-medium">
                        {s.metrics.exact_match_pct}%
                      </TableCell>
                      <TableCell className="text-right">
                        {s.metrics.within_1_pct}%
                      </TableCell>
                      <TableCell className="text-right">{s.metrics.mae}</TableCell>
                      <TableCell className="text-right">
                        <span
                          className={
                            Math.abs(s.metrics.mean_signed_error) < 0.3
                              ? "text-green-600"
                              : s.metrics.mean_signed_error > 0
                                ? "text-orange-500"
                                : "text-blue-500"
                          }
                        >
                          {s.metrics.mean_signed_error > 0 ? "+" : ""}
                          {s.metrics.mean_signed_error}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        {s.metrics.over_mark_pct}%
                      </TableCell>
                      <TableCell className="text-right">
                        {s.metrics.under_mark_pct}%
                      </TableCell>
                      <TableCell className="text-right">{s.metrics.errors}</TableCell>
                      <TableCell className="text-right">
                        ${s.cost_usd.toFixed(4)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

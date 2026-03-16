"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Play, History } from "lucide-react";
import { getRuns, getSettings, type RunSummary, type SettingsResponse } from "@/lib/api";

function statusColor(status: string) {
  switch (status) {
    case "completed":
      return "default";
    case "running":
      return "secondary";
    case "failed":
      return "destructive";
    case "cancelled":
      return "outline";
    default:
      return "secondary";
  }
}

export default function DashboardPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);

  useEffect(() => {
    getRuns(undefined, 5).then((d) => setRuns(d.runs)).catch(() => {});
    getSettings().then(setSettings).catch(() => {});
  }, []);

  const completedRuns = runs.filter((r) => r.status === "completed");
  const totalCost = completedRuns.reduce((s, r) => s + r.total_cost_usd, 0);

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <div className="flex gap-2">
            <Link href="/runs/new" className={buttonVariants()}>
              <Play className="mr-2 h-4 w-4" /> New Run
            </Link>
            <Link href="/runs" className={buttonVariants({ variant: "outline" })}>
              <History className="mr-2 h-4 w-4" /> History
            </Link>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Runs
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{runs.length}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Spend
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">${totalCost.toFixed(2)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                API Keys
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-2">
                {settings &&
                  Object.entries(settings.api_keys).map(([provider, ok]) => (
                    <Badge
                      key={provider}
                      variant={ok ? "default" : "outline"}
                    >
                      {provider}
                    </Badge>
                  ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Recent Runs */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent Runs</CardTitle>
          </CardHeader>
          <CardContent>
            {runs.length === 0 ? (
              <p className="py-8 text-center text-muted-foreground">
                No runs yet.{" "}
                <Link href="/runs/new" className="underline">
                  Start your first evaluation
                </Link>
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Subject</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Rows</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                    <TableHead className="text-right">Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell>
                        <Link
                          href={`/runs/${run.id}`}
                          className="font-medium hover:underline"
                        >
                          {run.name || run.id.slice(0, 8)}
                        </Link>
                      </TableCell>
                      <TableCell className="capitalize">{run.subject}</TableCell>
                      <TableCell>
                        <Badge variant={statusColor(run.status)}>
                          {run.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {run.completed_rows}/{run.total_rows}
                      </TableCell>
                      <TableCell className="text-right">
                        ${run.total_cost_usd.toFixed(4)}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {new Date(run.created_at).toLocaleDateString()}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

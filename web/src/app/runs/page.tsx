"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { Button, buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus } from "lucide-react";
import { getRuns, type RunSummary } from "@/lib/api";

function statusVariant(status: string) {
  switch (status) {
    case "completed": return "default" as const;
    case "running": return "secondary" as const;
    case "failed": return "destructive" as const;
    case "cancelled": return "outline" as const;
    default: return "secondary" as const;
  }
}

export default function RunHistoryPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("all");
  const [page, setPage] = useState(0);
  const perPage = 20;

  useEffect(() => {
    const status = statusFilter === "all" ? undefined : statusFilter;
    getRuns(status, perPage, page * perPage)
      .then((d) => {
        setRuns(d.runs);
        setTotal(d.total);
      })
      .catch(() => {});
  }, [statusFilter, page]);

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Run History</h1>
          <Link href="/runs/new" className={buttonVariants()}>
            <Plus className="mr-2 h-4 w-4" /> New Run
          </Link>
        </div>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">{total} runs</CardTitle>
              <Select value={statusFilter} onValueChange={(v) => v && setStatusFilter(v)}>
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Filter by status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="running">Running</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                  <SelectItem value="cancelled">Cancelled</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Subject</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Strategies</TableHead>
                  <TableHead className="text-right">Rows</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="text-right">Date</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                      No runs found
                    </TableCell>
                  </TableRow>
                ) : (
                  runs.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Link
                            href={`/runs/${run.id}`}
                            className="font-medium hover:underline"
                          >
                            {run.name || run.id.slice(0, 8)}
                          </Link>
                          {run.name?.startsWith("Promoted:") && (
                            <Badge variant="outline" className="text-xs border-violet-500/30 bg-violet-500/10 text-violet-600">
                              Autoresearch
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="capitalize">{run.subject}</TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
                      </TableCell>
                      <TableCell className="text-right">{run.strategies_count}</TableCell>
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
                  ))
                )}
              </TableBody>
            </Table>
            {total > perPage && (
              <div className="mt-4 flex justify-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={(page + 1) * perPage >= total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

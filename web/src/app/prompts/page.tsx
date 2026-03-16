"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getStrategies, type StrategyInfo } from "@/lib/api";

export default function PromptsListPage() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);

  useEffect(() => {
    getStrategies().then((d) => setStrategies(d.strategies)).catch(() => {});
  }, []);

  // Group by subject
  const grouped: Record<string, StrategyInfo[]> = {};
  strategies.forEach((s) => {
    if (!grouped[s.subject]) grouped[s.subject] = [];
    grouped[s.subject].push(s);
  });

  return (
    <AppShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold">Prompts</h1>
        <p className="text-sm text-muted-foreground">
          View and edit the prompt text for each strategy.
        </p>

        {Object.entries(grouped).map(([subject, strats]) => (
          <Card key={subject}>
            <CardHeader>
              <CardTitle className="capitalize text-base">{subject}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {strats.map((s) => (
                  <Link
                    key={s.name}
                    href={`/prompts/${encodeURIComponent(s.name)}`}
                    className="flex items-center justify-between rounded-md border p-3 hover:bg-accent transition-colors"
                  >
                    <div>
                      <div className="text-sm font-medium">{s.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {s.description}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-xs">
                        {s.model}
                      </Badge>
                      {s.phase && (
                        <Badge variant="secondary" className="text-xs">
                          Phase {s.phase}
                        </Badge>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </AppShell>
  );
}

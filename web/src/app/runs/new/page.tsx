"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronDown, ChevronRight, ArrowLeft, ArrowRight, Rocket } from "lucide-react";
import { toast } from "sonner";
import {
  getStrategies,
  getDatasets,
  getSettings,
  getSubjects,
  createRun,
  type StrategyInfo,
  type DatasetInfo,
  type ModelInfo,
  type SubjectInfo,
} from "@/lib/api";

type Step = 1 | 2 | 3 | 4 | 5;

export default function NewRunPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [loading, setLoading] = useState(false);

  // Data
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [pdfAvailable, setPdfAvailable] = useState(false);
  const [subjectList, setSubjectList] = useState<SubjectInfo[]>([]);

  // Config
  const [subject, setSubject] = useState("maths");
  const [inputMode, setInputMode] = useState("csv");
  const [selectedQuestions, setSelectedQuestions] = useState<string[]>([]);
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [sampleSize, setSampleSize] = useState(50);
  const [seed, setSeed] = useState(42);
  const [modelOverride, setModelOverride] = useState<string>("default");
  const [runName, setRunName] = useState("");

  useEffect(() => {
    getStrategies().then((d) => setStrategies(d.strategies)).catch(() => {});
    getSettings()
      .then((d) => setModels(d.models))
      .catch(() => {});
    getSubjects()
      .then((d) => setSubjectList(d.subjects))
      .catch(() => {});
  }, []);

  // Re-fetch datasets when inputMode changes (PDF mode includes Q32)
  useEffect(() => {
    getDatasets(inputMode)
      .then((d) => {
        setDatasets(d.datasets);
        setPdfAvailable(d.pdf_available);
      })
      .catch(() => {});
    // Clear selected questions when switching modes
    setSelectedQuestions([]);
  }, [inputMode]);

  const filteredStrategies = strategies.filter(
    (s) => s.subject === subject || s.subject === "all",
  );

  const currentDataset = datasets.find((d) => d.subject === subject);
  const questions = currentDataset?.questions || [];

  // Group strategies by phase
  const phases: Record<number, StrategyInfo[]> = {};
  filteredStrategies.forEach((s) => {
    const p = s.phase ?? 0;
    if (!phases[p]) phases[p] = [];
    phases[p].push(s);
  });

  const phaseLabels: Record<number, string> = {
    1: "Phase 1: Baseline Strategies",
    2: "Phase 2: Half-Mark Strategies",
    3: "Phase 3: Deep English",
    4: "Phase 4: Scorecard-Inspired",
    5: "Phase 5: Cross-Model Variants",
    6: "Phase 6: Debate & Multi-Agent",
    0: "Other",
  };

  function toggleQuestion(q: string) {
    setSelectedQuestions((prev) =>
      prev.includes(q) ? prev.filter((x) => x !== q) : [...prev, q],
    );
  }

  function toggleStrategy(name: string) {
    setSelectedStrategies((prev) =>
      prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name],
    );
  }

  async function handleLaunch() {
    setLoading(true);
    try {
      const result = await createRun({
        name: runName || undefined,
        subject,
        input_mode: inputMode,
        strategies: selectedStrategies,
        questions: selectedQuestions.length > 0 ? selectedQuestions : undefined,
        sample_size: sampleSize,
        random_seed: seed,
        model_override: modelOverride !== "default" ? modelOverride : undefined,
      });
      toast.success("Run started!");
      router.push(`/runs/${result.run_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to start run");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-2xl font-semibold">New Run</h1>
        </div>

        {/* Step indicators */}
        <div className="flex gap-2">
          {([1, 2, 3, 4, 5] as Step[]).map((s) => (
            <button
              key={s}
              onClick={() => setStep(s)}
              className={`h-2 flex-1 rounded-full transition-colors ${
                s <= step ? "bg-primary" : "bg-muted"
              }`}
            />
          ))}
        </div>

        {/* Step 1: Subject & Input Mode */}
        {step === 1 && (
          <Card>
            <CardHeader>
              <CardTitle>Subject & Input Mode</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Subject</Label>
                <Select value={subject} onValueChange={(v) => v && setSubject(v)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="maths">Maths</SelectItem>
                    <SelectItem value="english">English</SelectItem>
                    <SelectItem value="all">Both (Maths + English)</SelectItem>
                    {subjectList
                      .filter((s) => !s.is_builtin)
                      .map((s) => (
                        <SelectItem key={s.slug} value={s.slug}>
                          {s.display_name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Input Mode</Label>
                <Select value={inputMode} onValueChange={(v) => v && setInputMode(v)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="csv">CSV (text-based)</SelectItem>
                    {pdfAvailable && (
                      <SelectItem value="pdf">PDF (visual)</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex justify-end">
                <Button onClick={() => setStep(2)}>
                  Next <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 2: Questions */}
        {step === 2 && (
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Questions</CardTitle>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setSelectedQuestions(questions.map((q) => q.number))
                    }
                  >
                    Select All
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedQuestions([])}
                  >
                    Clear
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {questions.length === 0 ? (
                <p className="text-muted-foreground">No questions found for this subject.</p>
              ) : (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                  {questions.map((q) => (
                    <label
                      key={q.number}
                      className="flex cursor-pointer items-center gap-2 rounded-md border p-3 hover:bg-accent"
                    >
                      <Checkbox
                        checked={selectedQuestions.includes(q.number)}
                        onCheckedChange={() => toggleQuestion(q.number)}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium">Q{q.number}</div>
                        <div className="text-xs text-muted-foreground">
                          {q.total_marks} marks, {q.sample_count} rows
                        </div>
                      </div>
                    </label>
                  ))}
                </div>
              )}
              <p className="mt-3 text-sm text-muted-foreground">
                {selectedQuestions.length === 0
                  ? "All questions will be included"
                  : `${selectedQuestions.length} question(s) selected`}
              </p>
              <div className="mt-4 flex justify-between">
                <Button variant="outline" onClick={() => setStep(1)}>
                  <ArrowLeft className="mr-2 h-4 w-4" /> Back
                </Button>
                <Button onClick={() => setStep(3)}>
                  Next <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 3: Strategies */}
        {step === 3 && (
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Strategies</CardTitle>
                <p className="text-sm text-muted-foreground">
                  {selectedStrategies.length} selected
                </p>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {Object.entries(phases)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([phase, strats]) => (
                  <PhaseGroup
                    key={phase}
                    label={phaseLabels[Number(phase)] || `Phase ${phase}`}
                    strategies={strats}
                    selected={selectedStrategies}
                    onToggle={toggleStrategy}
                  />
                ))}
              <div className="flex justify-between">
                <Button variant="outline" onClick={() => setStep(2)}>
                  <ArrowLeft className="mr-2 h-4 w-4" /> Back
                </Button>
                <Button
                  onClick={() => setStep(4)}
                  disabled={selectedStrategies.length === 0}
                >
                  Next <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 4: Config */}
        {step === 4 && (
          <Card>
            <CardHeader>
              <CardTitle>Configuration</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Model Override</Label>
                <Select value={modelOverride} onValueChange={(v) => v && setModelOverride(v)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">Use strategy defaults</SelectItem>
                    {models
                      .filter((m) => m.available)
                      .map((m) => (
                        <SelectItem key={m.model_id} value={m.model_id}>
                          {m.name} ({m.provider})
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>
                  Sample Size: {sampleSize}
                </Label>
                <Slider
                  value={sampleSize}
                  onValueChange={(v) => setSampleSize(typeof v === "number" ? v : v[0])}
                  min={5}
                  max={200}
                  step={5}
                />
              </div>
              <div className="space-y-2">
                <Label>Random Seed</Label>
                <Input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value))}
                />
              </div>
              <div className="flex justify-between">
                <Button variant="outline" onClick={() => setStep(3)}>
                  <ArrowLeft className="mr-2 h-4 w-4" /> Back
                </Button>
                <Button onClick={() => setStep(5)}>
                  Next <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 5: Review & Launch */}
        {step === 5 && (
          <Card>
            <CardHeader>
              <CardTitle>Review & Launch</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Run Name (optional)</Label>
                <Input
                  placeholder="e.g., Q32 baseline test"
                  value={runName}
                  onChange={(e) => setRunName(e.target.value)}
                />
              </div>
              <div className="rounded-lg border p-4 space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Subject</span>
                  <span className="capitalize font-medium">{subject}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Input Mode</span>
                  <span className="uppercase font-medium">{inputMode}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Questions</span>
                  <span className="font-medium">
                    {selectedQuestions.length || "All"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Strategies</span>
                  <span className="font-medium">{selectedStrategies.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Sample Size</span>
                  <span className="font-medium">{sampleSize}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Model</span>
                  <span className="font-medium">
                    {modelOverride === "default" ? "Strategy defaults" : modelOverride}
                  </span>
                </div>
              </div>
              <div className="flex flex-wrap gap-1">
                {selectedStrategies.map((name) => (
                  <Badge key={name} variant="secondary">
                    {name}
                  </Badge>
                ))}
              </div>
              <div className="flex justify-between">
                <Button variant="outline" onClick={() => setStep(4)}>
                  <ArrowLeft className="mr-2 h-4 w-4" /> Back
                </Button>
                <Button onClick={handleLaunch} disabled={loading}>
                  <Rocket className="mr-2 h-4 w-4" />
                  {loading ? "Starting..." : "Launch Run"}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </AppShell>
  );
}

function PhaseGroup({
  label,
  strategies,
  selected,
  onToggle,
}: {
  label: string;
  strategies: StrategyInfo[];
  selected: string[];
  onToggle: (name: string) => void;
}) {
  const [open, setOpen] = useState(true);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium hover:bg-accent">
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        {label}
        <Badge variant="outline" className="ml-auto">
          {strategies.filter((s) => selected.includes(s.name)).length}/{strategies.length}
        </Badge>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-1 pl-6 pt-1">
        {strategies.map((s) => (
          <StrategyCard
            key={s.name}
            strategy={s}
            checked={selected.includes(s.name)}
            onToggle={() => onToggle(s.name)}
          />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

function StrategyCard({
  strategy,
  checked,
  onToggle,
}: {
  strategy: StrategyInfo;
  checked: boolean;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-md border p-3">
      <div className="flex items-start gap-3">
        <Checkbox checked={checked} onCheckedChange={onToggle} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{strategy.name}</span>
            <Badge variant="outline" className="text-xs">
              {strategy.model}
            </Badge>
            {strategy.is_two_pass && <Badge variant="secondary" className="text-xs">2-pass</Badge>}
            {strategy.has_debate && <Badge variant="secondary" className="text-xs">debate</Badge>}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{strategy.description}</p>
          {strategy.long_description && (
            <button
              className="mt-1 text-xs text-primary hover:underline"
              onClick={(e) => {
                e.preventDefault();
                setExpanded(!expanded);
              }}
            >
              {expanded ? "Less" : "More details"}
            </button>
          )}
          {expanded && strategy.long_description && (
            <p className="mt-2 text-xs text-muted-foreground whitespace-pre-line">
              {strategy.concept && (
                <>
                  <strong>Concept:</strong> {strategy.concept}{"\n"}
                </>
              )}
              {strategy.methodology && (
                <>
                  <strong>Method:</strong> {strategy.methodology}{"\n"}
                </>
              )}
              {strategy.recommendations && (
                <>
                  <strong>Rec:</strong> {strategy.recommendations}
                </>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

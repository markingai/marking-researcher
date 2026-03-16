"use client";

import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Upload, Trash2, BookOpen, Plus, FileSpreadsheet, AlertCircle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import {
  getSettings,
  getSubjects,
  createSubject,
  deleteSubject,
  type SettingsResponse,
  type SubjectInfo,
} from "@/lib/api";

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [subjects, setSubjects] = useState<SubjectInfo[]>([]);
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [newSubjectName, setNewSubjectName] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getSettings().then(setSettings).catch(() => {});
    loadSubjects();
  }, []);

  function loadSubjects() {
    getSubjects()
      .then((d) => setSubjects(d.subjects))
      .catch(() => {});
  }

  async function handleUpload() {
    if (!selectedFile || !newSubjectName.trim()) {
      toast.error("Please provide a subject name and CSV file");
      return;
    }
    setUploading(true);
    try {
      const result = await createSubject(selectedFile, newSubjectName.trim());
      toast.success(
        `Subject "${result.display_name}" created with ${result.total_rows} rows and ${result.question_count} questions`
      );
      setShowUpload(false);
      setNewSubjectName("");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      loadSubjects();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(slug: string, name: string) {
    if (!confirm(`Delete subject "${name}"? This cannot be undone.`)) return;
    try {
      await deleteSubject(slug);
      toast.success(`Subject "${name}" deleted`);
      loadSubjects();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    }
  }

  if (!settings)
    return (
      <AppShell>
        <p>Loading...</p>
      </AppShell>
    );

  return (
    <AppShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold">Settings</h1>

        {/* Subjects & Data */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <BookOpen className="h-4 w-4" />
                Subjects & Data
              </CardTitle>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowUpload(!showUpload)}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                Add Subject
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Subject list */}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Subject</TableHead>
                  <TableHead className="text-right">Rows</TableHead>
                  <TableHead className="text-right">Questions</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {subjects.map((s) => (
                  <TableRow key={s.slug}>
                    <TableCell className="font-medium">{s.display_name}</TableCell>
                    <TableCell className="text-right">
                      {s.total_rows ?? "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      {s.question_count ?? "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={s.is_builtin ? "default" : "secondary"} className="text-xs">
                        {s.is_builtin ? "Built-in" : "Custom"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {!s.is_builtin && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => handleDelete(s.slug, s.display_name)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {/* Upload form */}
            {showUpload && (
              <div className="rounded-lg border border-dashed p-4 space-y-4">
                <h3 className="text-sm font-medium">Add a New Subject</h3>
                <div className="space-y-2">
                  <Label htmlFor="subject-name">Subject Name</Label>
                  <Input
                    id="subject-name"
                    placeholder="e.g., Science, History, Geography"
                    value={newSubjectName}
                    onChange={(e) => setNewSubjectName(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="csv-file">CSV Data File</Label>
                  <Input
                    id="csv-file"
                    ref={fileInputRef}
                    type="file"
                    accept=".csv"
                    onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                  />
                </div>

                {/* CSV format guide */}
                <div className="rounded-md bg-muted/50 p-3 text-xs space-y-2">
                  <p className="font-medium flex items-center gap-1">
                    <FileSpreadsheet className="h-3.5 w-3.5" />
                    Required CSV Columns
                  </p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                    <div className="flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 text-green-500" />
                      <code>case_id</code>
                    </div>
                    <div className="flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 text-green-500" />
                      <code>question_number</code>
                    </div>
                    <div className="flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 text-green-500" />
                      <code>question_text</code>
                    </div>
                    <div className="flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 text-green-500" />
                      <code>total_marks</code>
                    </div>
                    <div className="flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 text-green-500" />
                      <code>marking_guide</code>
                    </div>
                    <div className="flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 text-green-500" />
                      <code>student_answer</code>
                    </div>
                    <div className="flex items-center gap-1">
                      <CheckCircle2 className="h-3 w-3 text-green-500" />
                      <code>human_mark</code>
                    </div>
                  </div>
                  <p className="text-muted-foreground pt-1">
                    Optional: <code>source_text</code>, <code>image_url</code>, <code>ai_mark</code>
                  </p>
                </div>

                <div className="flex gap-2 justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setShowUpload(false);
                      setNewSubjectName("");
                      setSelectedFile(null);
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleUpload}
                    disabled={uploading || !selectedFile || !newSubjectName.trim()}
                  >
                    <Upload className="mr-1.5 h-3.5 w-3.5" />
                    {uploading ? "Uploading..." : "Upload & Create"}
                  </Button>
                </div>
              </div>
            )}

            <div className="flex items-start gap-2 rounded-md bg-blue-50 dark:bg-blue-950/30 p-3 text-xs text-blue-700 dark:text-blue-300">
              <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <div>
                <p className="font-medium">How custom subjects work</p>
                <p className="mt-1 text-blue-600 dark:text-blue-400">
                  Upload a CSV with student answers, marking guides, and human marks.
                  Three generic strategies (baseline, criterion-decomposed, conservative)
                  are automatically created for each custom subject. You can then run
                  evaluations from the New Run page.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* API Keys */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">API Key Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex gap-4">
              {Object.entries(settings.api_keys).map(([provider, configured]) => (
                <div key={provider} className="flex items-center gap-2">
                  <div
                    className={`h-2.5 w-2.5 rounded-full ${
                      configured ? "bg-green-500" : "bg-gray-300"
                    }`}
                  />
                  <span className="text-sm capitalize">{provider}</span>
                  <Badge variant={configured ? "default" : "outline"} className="text-xs">
                    {configured ? "Configured" : "Not set"}
                  </Badge>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              API keys are set via environment variables on the server. They are never exposed to the frontend.
            </p>
          </CardContent>
        </Card>

        {/* Models */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Available Models</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead>Provider</TableHead>
                  <TableHead>Model ID</TableHead>
                  <TableHead className="text-right">Input $/M</TableHead>
                  <TableHead className="text-right">Output $/M</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {settings.models.map((m) => (
                  <TableRow key={m.model_id}>
                    <TableCell className="font-medium">{m.name}</TableCell>
                    <TableCell className="capitalize">{m.provider}</TableCell>
                    <TableCell className="font-mono text-xs">{m.model_id}</TableCell>
                    <TableCell className="text-right">${m.input_price_per_m}</TableCell>
                    <TableCell className="text-right">${m.output_price_per_m}</TableCell>
                    <TableCell>
                      <Badge variant={m.available ? "default" : "outline"}>
                        {m.available ? "Available" : "No API key"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Rate Limits */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Rate Limits</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm">
              {Object.entries(settings.rate_limits).map(([key, value]) => (
                <div key={key} className="flex justify-between py-1">
                  <span className="text-muted-foreground">
                    {key.replace(/_/g, " ")}
                  </span>
                  <span className="font-medium">{value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

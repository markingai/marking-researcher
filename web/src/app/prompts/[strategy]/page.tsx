"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { ArrowLeft, Save, RotateCcw, Pencil, Eye } from "lucide-react";
import { toast } from "sonner";
import {
  getPrompt,
  savePromptOverrides,
  deletePromptOverrides,
  type PromptResponse,
  type PromptField,
} from "@/lib/api";

export default function PromptEditorPage() {
  const params = useParams();
  const router = useRouter();
  const strategyName = decodeURIComponent(params.strategy as string);

  const [prompt, setPrompt] = useState<PromptResponse | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [editingField, setEditingField] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getPrompt(strategyName).then(setPrompt).catch(() => {
      toast.error("Failed to load prompt");
    });
  }, [strategyName]);

  const hasChanges = Object.keys(edits).length > 0;

  async function handleSave() {
    setSaving(true);
    try {
      const overrides = Object.entries(edits).map(([field_path, text]) => ({
        field_path,
        text,
      }));
      await savePromptOverrides(strategyName, overrides);
      toast.success("Prompt overrides saved");
      // Refresh
      const updated = await getPrompt(strategyName);
      setPrompt(updated);
      setEdits({});
      setEditingField(null);
    } catch {
      toast.error("Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    try {
      await deletePromptOverrides(strategyName);
      toast.success("Reset to defaults");
      const updated = await getPrompt(strategyName);
      setPrompt(updated);
      setEdits({});
      setEditingField(null);
    } catch {
      toast.error("Failed to reset");
    }
  }

  if (!prompt) return <AppShell><p>Loading...</p></AppShell>;

  const hasOverrides = prompt.fields.some((f) => f.is_overridden);

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="sm" onClick={() => router.back()}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h1 className="text-2xl font-semibold">{strategyName}</h1>
              <p className="text-sm text-muted-foreground">
                {prompt.prompt_fn_name} &middot; {prompt.module}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            {hasOverrides && (
              <Button variant="outline" size="sm" onClick={handleReset}>
                <RotateCcw className="mr-2 h-3 w-3" />
                Reset to Defaults
              </Button>
            )}
            {hasChanges && (
              <Button size="sm" onClick={handleSave} disabled={saving}>
                <Save className="mr-2 h-3 w-3" />
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            )}
          </div>
        </div>

        {prompt.fields.map((field) => (
          <PromptFieldCard
            key={field.field_path}
            field={field}
            editText={edits[field.field_path]}
            isEditing={editingField === field.field_path}
            onStartEdit={() => setEditingField(field.field_path)}
            onStopEdit={() => setEditingField(null)}
            onChangeText={(text) =>
              setEdits((prev) => ({ ...prev, [field.field_path]: text }))
            }
          />
        ))}

        {prompt.response_schema && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Response Schema</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="overflow-auto rounded bg-muted p-3 text-xs">
                {JSON.stringify(prompt.response_schema, null, 2)}
              </pre>
            </CardContent>
          </Card>
        )}
      </div>
    </AppShell>
  );
}

function PromptFieldCard({
  field,
  editText,
  isEditing,
  onStartEdit,
  onStopEdit,
  onChangeText,
}: {
  field: PromptField;
  editText: string | undefined;
  isEditing: boolean;
  onStartEdit: () => void;
  onStopEdit: () => void;
  onChangeText: (text: string) => void;
}) {
  const currentText = editText ?? field.text;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm">{field.label}</CardTitle>
            <Badge variant="outline" className="text-xs font-mono">
              {field.field_path}
            </Badge>
            {field.is_template && (
              <Badge variant="secondary" className="text-xs">
                Template
              </Badge>
            )}
            {field.is_overridden && (
              <Badge className="text-xs">Modified</Badge>
            )}
          </div>
          {!field.is_template && (
            <Button
              variant="ghost"
              size="sm"
              onClick={isEditing ? onStopEdit : onStartEdit}
            >
              {isEditing ? (
                <><Eye className="mr-1 h-3 w-3" /> View</>
              ) : (
                <><Pencil className="mr-1 h-3 w-3" /> Edit</>
              )}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isEditing && !field.is_template ? (
          <Textarea
            value={currentText}
            onChange={(e) => onChangeText(e.target.value)}
            rows={Math.min(Math.max(currentText.split("\n").length, 3), 20)}
            className="font-mono text-xs"
          />
        ) : (
          <div className="rounded bg-muted p-3">
            <pre className="whitespace-pre-wrap text-xs">{highlightTemplates(currentText)}</pre>
          </div>
        )}
        {field.is_overridden && field.original_text && editText === undefined && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Show original
            </summary>
            <pre className="mt-1 whitespace-pre-wrap rounded bg-muted/50 p-2 text-xs text-muted-foreground">
              {field.original_text}
            </pre>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function highlightTemplates(text: string): string {
  // Template variables are already in the text as {row.xxx} — just return as-is
  // In a more advanced version, we'd render with syntax highlighting
  return text;
}

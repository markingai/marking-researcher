/**
 * Typed API client with JWT authentication.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  // Don't set Content-Type for FormData (browser sets boundary automatically)
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Unauthorized");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }

  return res.json();
}

// --- Auth ---
export async function login(password: string) {
  const data = await request<{ token: string; expires_at: string }>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ password }) },
  );
  setToken(data.token);
  return data;
}

// --- Strategies ---
export async function getStrategies(subject?: string, phase?: number) {
  const params = new URLSearchParams();
  if (subject) params.set("subject", subject);
  if (phase !== undefined) params.set("phase", String(phase));
  const qs = params.toString();
  return request<{ strategies: StrategyInfo[] }>(
    `/api/strategies${qs ? `?${qs}` : ""}`,
  );
}

// --- Datasets ---
export async function getDatasets(inputMode?: string) {
  const params = new URLSearchParams();
  if (inputMode) params.set("input_mode", inputMode);
  const qs = params.toString();
  return request<DatasetsResponse>(`/api/datasets${qs ? `?${qs}` : ""}`);
}

export async function getQuestions(subject: string, inputMode?: string) {
  const params = new URLSearchParams();
  if (inputMode) params.set("input_mode", inputMode);
  const qs = params.toString();
  return request<{ questions: QuestionInfo[] }>(
    `/api/datasets/${subject}/questions${qs ? `?${qs}` : ""}`,
  );
}

// --- Runs ---
export async function createRun(req: CreateRunRequest) {
  return request<{ run_id: string; status: string }>(
    "/api/runs",
    { method: "POST", body: JSON.stringify(req) },
  );
}

export async function getRuns(status?: string, limit = 20, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) params.set("status", status);
  return request<{ runs: RunSummary[]; total: number }>(
    `/api/runs?${params}`,
  );
}

export async function getRun(id: string) {
  return request<RunDetail>(`/api/runs/${id}`);
}

export async function cancelRun(id: string) {
  return request<{ status: string }>(
    `/api/runs/${id}/cancel`,
    { method: "POST" },
  );
}

export function subscribeToRunEvents(
  runId: string,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): () => void {
  const token = getToken();
  const url = `${API_URL}/api/runs/${runId}/events?token=${token}`;
  const es = new EventSource(url);

  es.onmessage = (e) => {
    try {
      const parsed = JSON.parse(e.data);
      onEvent(parsed.event, parsed.data);
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = () => {
    // EventSource will auto-reconnect
  };

  return () => es.close();
}

// --- Results ---
export async function getResultsSummary(runId: string) {
  return request<ResultsSummary>(`/api/results/${runId}`);
}

export async function getResultsDetail(
  runId: string,
  params?: { strategy?: string; question?: string; page?: number; per_page?: number },
) {
  const qs = new URLSearchParams();
  if (params?.strategy) qs.set("strategy", params.strategy);
  if (params?.question) qs.set("question", params.question);
  if (params?.page) qs.set("page", String(params.page));
  if (params?.per_page) qs.set("per_page", String(params.per_page));
  const q = qs.toString();
  return request<ResultsDetail>(
    `/api/results/${runId}/detail${q ? `?${q}` : ""}`,
  );
}

// --- Prompts ---
export async function getPrompt(strategyName: string) {
  return request<PromptResponse>(`/api/prompts/${strategyName}`);
}

export async function savePromptOverrides(
  strategyName: string,
  overrides: { field_path: string; text: string }[],
) {
  return request<{ status: string }>(
    `/api/prompts/${strategyName}`,
    { method: "PUT", body: JSON.stringify({ overrides }) },
  );
}

export async function deletePromptOverrides(strategyName: string) {
  return request<{ status: string }>(
    `/api/prompts/${strategyName}/overrides`,
    { method: "DELETE" },
  );
}

// --- Settings ---
export async function getSettings() {
  return request<SettingsResponse>("/api/settings");
}

// --- Uploads ---
export async function uploadFile(file: File, subject?: string) {
  const formData = new FormData();
  formData.append("file", file);
  if (subject) formData.append("subject", subject);
  return request<{ id: string; filename: string; file_type: string; size: number }>(
    "/api/uploads",
    { method: "POST", body: formData },
  );
}

// --- Subjects ---
export async function getSubjects() {
  return request<{ subjects: SubjectInfo[] }>("/api/subjects");
}

export async function createSubject(file: File, displayName: string) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("display_name", displayName);
  return request<{
    slug: string;
    display_name: string;
    total_rows: number;
    question_count: number;
    columns: string[];
  }>("/api/subjects", { method: "POST", body: formData });
}

export async function deleteSubject(slug: string) {
  return request<{ status: string; slug: string }>(
    `/api/subjects/${slug}`,
    { method: "DELETE" },
  );
}

// --- Types ---
export interface StrategyInfo {
  name: string;
  description: string;
  long_description: string | null;
  concept: string | null;
  methodology: string | null;
  recommendations: string | null;
  subject: string;
  model: string;
  provider: string;
  phase: number | null;
  tags: string[];
  is_two_pass: boolean;
  has_debate: boolean;
  ensemble_runs: number;
}

export interface QuestionInfo {
  number: string;
  total_marks: number;
  sample_count: number;
  question_text_preview: string;
}

export interface DatasetInfo {
  subject: string;
  source: string;
  total_rows: number;
  questions: QuestionInfo[];
}

export interface DatasetsResponse {
  datasets: DatasetInfo[];
  pdf_available: boolean;
  pdf_submissions: number;
}

export interface CreateRunRequest {
  name?: string;
  subject: string;
  input_mode: string;
  strategies: string[];
  questions?: string[];
  sample_size: number;
  random_seed: number;
  model_override?: string;
}

export interface RunSummary {
  id: string;
  name: string | null;
  status: string;
  subject: string;
  input_mode: string;
  model_override: string | null;
  strategies_count: number;
  total_rows: number;
  completed_rows: number;
  total_cost_usd: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

export interface RunStrategyStatus {
  strategy_name: string;
  status: string;
  rows_total: number;
  rows_completed: number;
  errors: number;
  cost_usd: number;
}

export interface RunDetail extends RunSummary {
  strategies: RunStrategyStatus[];
  questions: string[];
}

export interface MetricSet {
  n: number;
  exact_match_pct: number;
  exact_match_rounded_pct: number;
  within_half_pct: number;
  within_1_pct: number;
  mae: number;
  mean_signed_error: number;
  over_mark_pct: number;
  under_mark_pct: number;
  errors: number;
}

export interface ResultsSummary {
  strategies: {
    name: string;
    metrics: MetricSet;
    cost_usd: number;
  }[];
  total_evaluated: number;
  total_errors: number;
  total_cost_usd: number;
  best_strategy: string | null;
}

export interface EvalResultDetail {
  row_id: string;
  question_number: string;
  total_marks: number;
  human_mark: number;
  ai_mark: number;
  signed_error: number;
  exact_match: boolean;
  justification: string | null;
  criteria_breakdown: string | null;
  cost_usd: number;
}

export interface ConfusionEntry {
  human_mark: number;
  ai_mark: number;
  count: number;
}

export interface QuestionMetric {
  question_number: string;
  metrics: MetricSet;
}

export interface ResultsDetail {
  results: EvalResultDetail[];
  total: number;
  confusion_matrix: ConfusionEntry[];
  per_question_metrics: QuestionMetric[];
}

export interface PromptField {
  field_path: string;
  label: string;
  text: string;
  is_template: boolean;
  is_overridden: boolean;
  original_text: string | null;
}

export interface PromptResponse {
  strategy_name: string;
  prompt_fn_name: string;
  module: string;
  fields: PromptField[];
  response_schema: Record<string, unknown> | null;
}

export interface ModelInfo {
  name: string;
  model_id: string;
  provider: string;
  input_price_per_m: number;
  output_price_per_m: number;
  available: boolean;
}

export interface SettingsResponse {
  api_keys: Record<string, boolean>;
  models: ModelInfo[];
  rate_limits: Record<string, number>;
}

export interface SubjectInfo {
  slug: string;
  display_name: string;
  is_builtin: boolean;
  total_rows: number | null;
  question_count: number | null;
  created_at: string | null;
}

// --- Autoresearch ---
export interface AutoresearchSession {
  id: string;
  status: string;
  budget_usd: number;
  spent_usd: number;
  model: string;
  sample_size: number;
  experiments_run: number;
  best_exact_match: number;
  best_experiment_id: string | null;
  created_at: string;
  completed_at: string | null;
  report_md: string | null;
  session_number: number | null;
  parent_session_id: string | null;
}

export interface AutoresearchExperiment {
  id: string;
  session_id: string;
  description: string;
  strategy_name: string;
  exact_match: number | null;
  within_10_pct: number | null;
  within_1: number | null;
  mae: number | null;
  bias: number | null;
  cost_usd: number;
  n: number;
  model: string | null;
  kept: boolean;
  per_question: Record<string, { n: number; exact_match: number; within_10_pct?: number; within_1?: number; mae: number; bias?: number }> | null;
  prompt_text: string | null;
  config_json: string | null;
  created_at: string;
}

export interface AutoresearchSessionDetail {
  session: AutoresearchSession;
  experiments: AutoresearchExperiment[];
}

export async function startAutoresearchSession(config: {
  budget_usd?: number;
  sample_size?: number;
  model?: string;
}) {
  return request<{ session_id: string; status: string }>(
    "/api/autoresearch/sessions",
    { method: "POST", body: JSON.stringify(config) },
  );
}

export async function getAutoresearchSessions() {
  return request<AutoresearchSession[]>("/api/autoresearch/sessions");
}

export async function getAutoresearchSession(id: string) {
  return request<AutoresearchSessionDetail>(
    `/api/autoresearch/sessions/${id}`,
  );
}

export async function stopAutoresearchSession(id: string) {
  return request<{ status: string }>(
    `/api/autoresearch/sessions/${id}/stop`,
    { method: "POST" },
  );
}

export function subscribeToAutoresearchEvents(
  sessionId: string,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): () => void {
  const token = getToken();
  const url = `${API_URL}/api/autoresearch/sessions/${sessionId}/events?token=${token}`;
  const es = new EventSource(url);

  es.onmessage = (e) => {
    try {
      const parsed = JSON.parse(e.data);
      onEvent(parsed.event, parsed.data);
      // Close on terminal events to prevent auto-reconnect loop
      if (parsed.event === "session_complete" || parsed.event === "error") {
        es.close();
      }
    } catch {
      // ignore
    }
  };

  es.onerror = () => {
    es.close();
  };

  return () => es.close();
}

// --- Leaderboard ---
export interface LeaderboardEntry {
  strategy_name: string;
  description: string;
  times_tested: number;
  avg_exact_match: number;
  avg_within_10_pct: number | null;
  avg_within_1: number;
  avg_mae: number;
  avg_bias: number;
  avg_cost_usd: number;
  best_exact_match: number;
  best_within_10_pct: number | null;
  first_tested: string | null;
  last_tested: string | null;
}

export interface TimelineEntry {
  session_id: string;
  created_at: string;
  best_exact_match: number;
  experiments_run: number;
  spent_usd: number;
  session_number: number | null;
}

export async function getAutoresearchLeaderboard() {
  return request<LeaderboardEntry[]>("/api/autoresearch/leaderboard");
}

export async function getAutoresearchTimeline() {
  return request<TimelineEntry[]>("/api/autoresearch/leaderboard/timeline");
}

export async function promoteExperiment(experimentId: string) {
  return request<{ run_id: string; status: string }>(
    `/api/autoresearch/experiments/${experimentId}/promote`,
    { method: "POST" },
  );
}

export { ApiError };

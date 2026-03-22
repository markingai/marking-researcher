"""Pydantic request/response models."""

from __future__ import annotations

from pydantic import BaseModel


# --- Auth ---

class LoginRequest(BaseModel):
    password: str

class LoginResponse(BaseModel):
    token: str
    expires_at: str


# --- Strategies ---

class StrategyInfo(BaseModel):
    name: str
    description: str
    long_description: str | None = None
    concept: str | None = None
    methodology: str | None = None
    recommendations: str | None = None
    subject: str
    model: str
    provider: str
    phase: int | None = None
    tags: list[str] = []
    is_two_pass: bool = False
    has_debate: bool = False
    ensemble_runs: int = 1

class StrategiesResponse(BaseModel):
    strategies: list[StrategyInfo]


# --- Datasets ---

class QuestionInfo(BaseModel):
    number: str
    total_marks: int
    sample_count: int
    question_text_preview: str

class DatasetInfo(BaseModel):
    subject: str
    source: str
    total_rows: int
    questions: list[QuestionInfo]

class DatasetsResponse(BaseModel):
    datasets: list[DatasetInfo]
    pdf_available: bool = False
    pdf_submissions: int = 0


# --- Runs ---

class CreateRunRequest(BaseModel):
    name: str | None = None
    subject: str  # maths, english, all
    input_mode: str = "csv"
    strategies: list[str]
    questions: list[str] | None = None  # None = all questions
    sample_size: int = 50
    random_seed: int = 42
    model_override: str | None = None

class RunSummary(BaseModel):
    id: str
    name: str | None
    status: str
    subject: str
    input_mode: str
    model_override: str | None = None
    strategies_count: int
    total_rows: int
    completed_rows: int
    total_cost_usd: float
    created_at: str
    started_at: str | None
    completed_at: str | None
    error_message: str | None = None

class RunStrategyStatus(BaseModel):
    strategy_name: str
    status: str
    rows_total: int
    rows_completed: int
    errors: int
    cost_usd: float

class RunDetail(RunSummary):
    strategies: list[RunStrategyStatus]
    questions: list[str]

class RunsListResponse(BaseModel):
    runs: list[RunSummary]
    total: int


# --- Results ---

class MetricSetResponse(BaseModel):
    n: int
    exact_match_pct: float
    exact_match_rounded_pct: float
    within_half_pct: float
    within_1_pct: float
    mae: float
    mean_signed_error: float
    over_mark_pct: float
    under_mark_pct: float
    errors: int

class StrategyResult(BaseModel):
    name: str
    description: str
    model: str
    phase: int | None
    metrics: MetricSetResponse
    cost_usd: float

class ResultsSummaryResponse(BaseModel):
    run_id: str
    subject: str
    total_evaluated: int
    total_errors: int
    total_cost_usd: float
    strategies: list[StrategyResult]
    best_strategy: str | None

class EvalResultDetail(BaseModel):
    row_id: str
    question_number: str
    total_marks: int
    human_mark: float
    ai_mark: float
    signed_error: float
    exact_match: bool
    justification: str | None
    criteria_breakdown: str | None
    cost_usd: float

class ConfusionEntry(BaseModel):
    human_mark: float
    ai_mark: float
    count: int

class QuestionMetric(BaseModel):
    question_number: str
    metrics: MetricSetResponse

class ResultsDetailResponse(BaseModel):
    results: list[EvalResultDetail]
    total: int
    confusion_matrix: list[ConfusionEntry]
    per_question_metrics: list[QuestionMetric]


# --- Prompts ---

class PromptField(BaseModel):
    field_path: str
    label: str
    text: str
    is_template: bool = False
    is_overridden: bool = False
    original_text: str | None = None

class PromptResponse(BaseModel):
    strategy_name: str
    prompt_fn_name: str
    module: str
    fields: list[PromptField]
    response_schema: dict | None = None

class PromptOverrideRequest(BaseModel):
    overrides: list[dict]  # [{field_path, text}]


# --- Settings ---

class ModelInfo(BaseModel):
    name: str
    model_id: str
    provider: str
    input_price_per_m: float
    output_price_per_m: float
    available: bool  # API key configured

class SettingsResponse(BaseModel):
    api_keys: dict[str, bool]  # provider → configured
    models: list[ModelInfo]
    rate_limits: dict[str, int]


# --- Autoresearch ---

class StartAutoresearchRequest(BaseModel):
    budget_usd: float = 20.0
    sample_size: int = 30
    model: str = "gemini-2.5-pro"

class AutoresearchSessionResponse(BaseModel):
    id: str
    status: str
    budget_usd: float
    spent_usd: float
    model: str
    sample_size: int
    experiments_run: int
    best_exact_match: float
    best_experiment_id: str | None
    created_at: str
    completed_at: str | None
    report_md: str | None = None
    session_number: int | None = None
    parent_session_id: str | None = None

class AutoresearchExperimentResponse(BaseModel):
    id: str
    session_id: str
    description: str
    strategy_name: str
    exact_match: float | None
    within_1: float | None
    mae: float | None
    bias: float | None
    cost_usd: float
    n: int
    model: str | None
    kept: bool
    per_question: dict | None = None
    prompt_text: str | None = None
    config_json: str | None = None
    created_at: str

class AutoresearchSessionDetailResponse(BaseModel):
    session: AutoresearchSessionResponse
    experiments: list[AutoresearchExperimentResponse]


class LeaderboardEntry(BaseModel):
    strategy_name: str
    description: str
    times_tested: int
    avg_exact_match: float
    avg_within_1: float
    avg_mae: float
    avg_bias: float
    avg_cost_usd: float
    best_exact_match: float
    first_tested: str | None = None
    last_tested: str | None = None


class TimelineEntry(BaseModel):
    session_id: str
    created_at: str
    best_exact_match: float
    experiments_run: int
    spent_usd: float

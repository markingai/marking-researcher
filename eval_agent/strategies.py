"""Strategy definitions and registry.

Each strategy defines how to prompt the model and parse the response.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any

from . import config
from .data_loader import MarkingRow
from .prompts import maths_prompts, english_prompts, generic_prompts


@dataclass
class DebateConfig:
    """Configuration for multi-marker debate strategies."""
    mode: str  # "dual_adjudicate", "multi_round", "panel"

    # For dual_adjudicate and multi_round
    marker_b_prompt_fn: Callable | None = None
    marker_b_parse_fn: Callable | None = None
    adjudicator_fn: Callable | None = None  # returns (system, user_parts, schema)
    adjudicator_parse_fn: Callable | None = None
    agreement_threshold: float = 0  # skip adjudication if marks within this
    max_debate_rounds: int = 2
    deadlock_strategy: str = "conservative"  # "conservative" or "average"
    rebuttal_fn: Callable | None = None  # for multi_round mode

    # For panel mode
    panel_prompt_fns: list[Callable] | None = None
    panel_parse_fns: list[Callable] | None = None


@dataclass
class Strategy:
    name: str
    description: str
    subject: str  # "maths", "english", or "all"
    model: str
    temperature: float
    thinking: bool
    thinking_budget: int | None  # None = unlimited (-1)
    prompt_fn: Callable  # returns (system, user_parts, schema)
    parse_fn: Callable[[dict], dict]  # extracts {mark, justification} from response
    provider: str = "gemini"  # "gemini", "anthropic", "openai"
    thinking_level: str | None = None  # For Gemini 3.x: "low", "medium", "high"
    is_two_pass: bool = False
    second_pass_fn: Callable | None = None
    ensemble_runs: int = 1  # >1 means run N times and average
    debate_config: DebateConfig | None = None


# --- Response parsers ---

def parse_simple(resp: dict) -> dict:
    """Parse a {mark, justification} response."""
    if "error" in resp and "mark" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}
    return {
        "mark": int(resp.get("mark", -1)),
        "justification": resp.get("justification", ""),
    }


def parse_criterion(resp: dict) -> dict:
    """Parse a criterion-decomposed response."""
    if "error" in resp and "total_mark" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}

    criteria = resp.get("criteria", [])
    total = int(resp.get("total_mark", -1))
    breakdown = "; ".join(
        f"{c.get('criterion', '?')}: {c.get('marks_awarded', '?')}/{c.get('max_marks', '?')} - {c.get('reason', '')}"
        for c in criteria
    )
    return {
        "mark": total,
        "justification": breakdown,
        "criteria": criteria,
    }


def parse_english_criterion(resp: dict) -> dict:
    """Parse English criterion-decomposed response."""
    if "error" in resp and "final_mark" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}

    ca = resp.get("content_and_analysis", 0)
    ce = resp.get("command_of_evidence", 0)
    cos = resp.get("coherence_organization_style", 0)
    cc = resp.get("control_of_conventions", 0)
    final = int(resp.get("final_mark", round((ca + ce + cos + cc) / 4)))

    breakdown = (
        f"Content & Analysis: {ca}/6, "
        f"Command of Evidence: {ce}/6, "
        f"Coherence/Org/Style: {cos}/6, "
        f"Conventions: {cc}/6"
    )
    return {
        "mark": final,
        "justification": f"{breakdown}. {resp.get('justification', '')}",
        "criteria_scores": {"ca": ca, "ce": ce, "cos": cos, "cc": cc},
    }


def parse_english_halfmark_criterion(resp: dict) -> dict:
    """Parse English criterion-decomposed response with half-marks."""
    if "error" in resp and "final_mark" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}

    ca = float(resp.get("content_and_analysis", 0))
    ce = float(resp.get("command_of_evidence", 0))
    cos = float(resp.get("coherence_organization_style", 0))
    cc = float(resp.get("control_of_conventions", 0))
    raw_avg = (ca + ce + cos + cc) / 4
    final = float(resp.get("final_mark", round(raw_avg * 2) / 2))
    # Snap to nearest 0.5
    final = round(final * 2) / 2

    breakdown = (
        f"Content & Analysis: {ca}/6, "
        f"Command of Evidence: {ce}/6, "
        f"Coherence/Org/Style: {cos}/6, "
        f"Conventions: {cc}/6"
    )
    return {
        "mark": final,
        "justification": f"{breakdown}. {resp.get('justification', '')}",
        "criteria_scores": {"ca": ca, "ce": ce, "cos": cos, "cc": cc},
    }


def parse_halfmark(resp: dict) -> dict:
    """Parse a {mark, justification} response allowing half-marks."""
    if "error" in resp and "mark" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}
    raw_mark = float(resp.get("mark", -1))
    # Snap to nearest 0.5
    mark = round(raw_mark * 2) / 2
    return {
        "mark": mark,
        "justification": resp.get("justification", ""),
    }


def parse_scorecard(resp: dict) -> dict:
    """Parse scorecard signal response and compute mark deterministically."""
    if "error" in resp and "claim_present" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}

    from .scorecard_scorer import signals_to_mark

    signals = {
        "claim_present": resp.get("claim_present", False),
        "claim_quality": int(resp.get("claim_quality", 0)),
        "source_analysis": int(resp.get("source_analysis", 0)),
        "counterclaim_quality": int(resp.get("counterclaim_quality", 0)),
        "evidence_present": resp.get("evidence_present", False),
        "evidence_quality": int(resp.get("evidence_quality", 0)),
        "citation_quality": int(resp.get("citation_quality", 0)),
        "task_focus": int(resp.get("task_focus", 0)),
        "organization": int(resp.get("organization", 0)),
        "language_sophistication": int(resp.get("language_sophistication", 0)),
        "conventions_control": int(resp.get("conventions_control", 0)),
        "conventions_severity": int(resp.get("conventions_severity", 0)),
        "source_count": int(resp.get("source_count", 0)),
        "is_off_topic": resp.get("is_off_topic", False),
        "is_blank_or_copied": resp.get("is_blank_or_copied", False),
    }

    mark, breakdown = signals_to_mark(signals)
    notes = resp.get("signal_notes", "")

    return {
        "mark": mark,
        "justification": f"{breakdown}. Notes: {notes}",
        "signals": signals,
    }


def parse_comparative(resp: dict) -> dict:
    """Parse comparative anchor response and compute mark deterministically."""
    if "error" in resp and "vs_3_content" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}

    COMP_MAP = {"WORSE": -1, "EQUAL": 0, "BETTER": 1}

    # Gate checks
    if resp.get("is_blank_or_copied", False):
        return {"mark": 0, "justification": "Gate: blank/copied -> 0"}
    if resp.get("is_off_topic", False):
        return {"mark": 1, "justification": "Gate: off-topic -> 1"}

    criteria = ["content", "evidence", "coherence", "conventions"]
    criterion_scores = []

    for c in criteria:
        vs_3_raw = str(resp.get(f"vs_3_{c}", "EQUAL")).upper().strip()
        vs_4_raw = str(resp.get(f"vs_4_{c}", "EQUAL")).upper().strip()
        vs_3 = COMP_MAP.get(vs_3_raw, 0)
        vs_4 = COMP_MAP.get(vs_4_raw, 0)

        if vs_3 == -1:  # WORSE than anchor 3
            score = 2.0 if vs_4 >= 0 else 1.5
        elif vs_3 == 0:  # EQUAL to anchor 3
            if vs_4 == -1:
                score = 3.0
            elif vs_4 == 0:
                score = 3.5
            else:
                score = 3.5  # Equal to 3 but better than 4 is inconsistent
        else:  # BETTER than anchor 3
            if vs_4 == -1:
                score = 3.5  # Between 3 and 4
            elif vs_4 == 0:
                score = 4.0  # Matches 4
            else:
                score = 5.0  # Above both

        criterion_scores.append(score)

    raw_avg = sum(criterion_scores) / len(criterion_scores)

    # Source cap
    if resp.get("fewer_than_3_sources", False) and raw_avg > 3:
        raw_avg = 3.0

    final = round(raw_avg)
    final = max(0, min(6, final))

    breakdown = ", ".join(
        f"{c}={s:.1f}" for c, s in zip(criteria, criterion_scores)
    )
    notes = resp.get("comparison_notes", "")
    return {
        "mark": final,
        "justification": f"Criterion: {breakdown}, avg={raw_avg:.2f} -> {final}. {notes}",
    }


def parse_verify(resp: dict) -> dict:
    """Parse a verify-pass response."""
    if "error" in resp and "verified_mark" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}
    return {
        "mark": int(resp.get("verified_mark", resp.get("original_mark", -1))),
        "justification": resp.get("reason", ""),
        "changed": resp.get("changed", False),
    }


# --- Strategy registry ---

def build_strategies() -> list[Strategy]:
    """Build the full list of strategies to test."""
    model = config.MODEL_DEFAULT

    return [
        # === MATHS STRATEGIES ===
        Strategy(
            name="maths_baseline",
            description="Replicates current n8n marking prompt",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.baseline,
            parse_fn=parse_simple,
        ),
        Strategy(
            name="maths_criterion_decomposed",
            description="Marks each criterion independently then sums",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
        ),
        Strategy(
            name="maths_few_shot",
            description="Includes correctly-marked examples for calibration",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.few_shot_calibrated,
            parse_fn=parse_simple,
        ),
        Strategy(
            name="maths_mark_verify",
            description="Two-pass: mark then adversarial review",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.mark_then_verify_pass1,
            parse_fn=parse_simple,
            is_two_pass=True,
            second_pass_fn=maths_prompts.mark_then_verify_pass2,
        ),
        Strategy(
            name="maths_rubric_anchor",
            description="Level-based matching instead of direct marking",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.rubric_anchor,
            parse_fn=parse_simple,
        ),
        Strategy(
            name="maths_conservative",
            description="Baseline with strong conservative bias language",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.conservative_bias,
            parse_fn=parse_simple,
        ),

        # === ENGLISH STRATEGIES ===
        Strategy(
            name="english_baseline",
            description="Holistic essay scoring",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_baseline,
            parse_fn=parse_simple,
        ),
        Strategy(
            name="english_criterion_decomposed",
            description="Score 4 criteria independently then average",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_criterion_decomposed,
            parse_fn=parse_english_criterion,
        ),
        Strategy(
            name="english_anchor_examples",
            description="Includes calibration essays at different score levels",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_anchor_examples,
            parse_fn=parse_simple,
        ),
        Strategy(
            name="english_strict_range",
            description="Baseline with score distribution calibration",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_strict_range,
            parse_fn=parse_simple,
        ),

        # === PHASE 2 STRATEGIES ===

        # Hybrid: criterion decomposed + conservative for maths
        Strategy(
            name="maths_criterion_conservative",
            description="Criterion decomposed with conservative bias language",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_conservative,
            parse_fn=parse_criterion,
        ),

        # English with half-mark output: criterion decomposed
        Strategy(
            name="english_halfmark_criterion",
            description="Criterion decomposed with 0.5 increment scoring",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_halfmark_criterion,
            parse_fn=parse_english_halfmark_criterion,
        ),

        # English with half-marks + exemplar anchors
        Strategy(
            name="english_halfmark_exemplar",
            description="Half-marks with calibration exemplars at each level",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_halfmark_exemplar,
            parse_fn=parse_halfmark,
        ),

        # === PHASE 3 STRATEGIES (English-focused) ===

        # S1: Forced criterion independence (fixes root cause: criterion collapse)
        Strategy(
            name="english_forced_independence",
            description="Forces independent scoring per criterion with anti-collapse guards",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
        ),

        # S2: Level descriptors (match to rubric level descriptions)
        Strategy(
            name="english_level_descriptors",
            description="Match essay to specific rubric level descriptors per criterion",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_level_descriptors,
            parse_fn=parse_english_criterion,
        ),

        # S3: Full exemplars (full essays at each score level)
        Strategy(
            name="english_full_exemplars",
            description="Full calibration essays at score 2, 3, 4, 5 + criterion decomposition",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_full_exemplars,
            parse_fn=parse_english_criterion,
        ),

        # S4: Flash ensemble (3x Flash runs averaged)
        Strategy(
            name="english_flash_ensemble",
            description="3x Gemini Flash runs averaged (cheap ensemble)",
            subject="english",
            model=config.MODEL_FLASH,
            temperature=0.3,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
            ensemble_runs=3,
        ),

        # S5: Higher thinking budget (8192 instead of 4096)
        Strategy(
            name="english_higher_thinking",
            description="Criterion decomposed with 8192 thinking budget",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=8192,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
        ),

        # === PHASE 4 STRATEGIES (Scorecard-inspired) ===

        # S10: Scorecard (binary signal extraction + deterministic scoring)
        Strategy(
            name="english_scorecard",
            description="Binary/ordinal signal extraction -> deterministic scoring (no LLM scores)",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_scorecard,
            parse_fn=parse_scorecard,
        ),

        # S11: Cascade (coarse band + fine exact)
        Strategy(
            name="english_cascade",
            description="Two-pass: band classification (LOW/MID/HIGH) then within-band exact score",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_cascade_pass1,
            parse_fn=parse_simple,  # Pass 1 parsed specially in runner
            is_two_pass=True,
        ),

        # S12: Comparative anchor (relative comparison to exemplars)
        Strategy(
            name="english_comparative_anchor",
            description="Compare essay to score-3 and score-4 exemplars (relative judgment)",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_comparative_anchor,
            parse_fn=parse_comparative,
        ),

        # === PHASE 6: DEBATE STRATEGIES ===

        # Simple Moderation: criterion_decomposed + independent moderator review
        Strategy(
            name="maths_moderated",
            description="Two-pass: criterion marking then independent moderator review",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
            is_two_pass=True,
            second_pass_fn=maths_prompts.moderation_pass2,
        ),

        # Simple Moderation for English: comparative anchor + moderator review
        Strategy(
            name="english_moderated",
            description="Two-pass: comparative anchor then independent moderator review",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_comparative_anchor,
            parse_fn=parse_comparative,
            is_two_pass=True,
            second_pass_fn=english_prompts.english_moderation_pass2,
        ),

        # Expert Panel: 3 independent markers with majority/median resolution
        Strategy(
            name="maths_panel",
            description="3 independent markers vote (criterion, conservative, rubric_anchor)",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
            debate_config=DebateConfig(
                mode="panel",
                panel_prompt_fns=[
                    maths_prompts.criterion_decomposed,
                    maths_prompts.criterion_conservative,
                    maths_prompts.rubric_anchor,
                ],
                panel_parse_fns=[
                    parse_criterion,
                    parse_criterion,
                    parse_simple,
                ],
            ),
        ),
        Strategy(
            name="english_panel",
            description="3 independent markers vote (forced_independence, level_descriptors, comparative_anchor)",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
            debate_config=DebateConfig(
                mode="panel",
                panel_prompt_fns=[
                    english_prompts.english_forced_independence,
                    english_prompts.english_level_descriptors,
                    english_prompts.english_comparative_anchor,
                ],
                panel_parse_fns=[
                    parse_english_criterion,
                    parse_english_criterion,
                    parse_comparative,
                ],
            ),
        ),

        # Dual Adjudication: 2 markers + adjudicator on disagreement
        Strategy(
            name="maths_dual_adjudicate",
            description="Two markers (criterion + conservative) + chief examiner adjudicator",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
            debate_config=DebateConfig(
                mode="dual_adjudicate",
                marker_b_prompt_fn=maths_prompts.criterion_conservative,
                marker_b_parse_fn=parse_criterion,
                adjudicator_fn=maths_prompts.adjudicator,
                adjudicator_parse_fn=parse_simple,
                agreement_threshold=0,
            ),
        ),
        Strategy(
            name="english_dual_adjudicate",
            description="Two markers (forced_independence + comparative_anchor) + adjudicator",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
            debate_config=DebateConfig(
                mode="dual_adjudicate",
                marker_b_prompt_fn=english_prompts.english_comparative_anchor,
                marker_b_parse_fn=parse_comparative,
                adjudicator_fn=english_prompts.english_adjudicator,
                adjudicator_parse_fn=parse_simple,
                agreement_threshold=0,
            ),
        ),

        # Multi-Round Debate: iterative rebuttals with CONCEDE/HOLD/COMPROMISE
        Strategy(
            name="maths_debate",
            description="Two markers debate with rebuttals (max 2 rounds, conservative deadlock)",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
            debate_config=DebateConfig(
                mode="multi_round",
                marker_b_prompt_fn=maths_prompts.criterion_conservative,
                marker_b_parse_fn=parse_criterion,
                rebuttal_fn=maths_prompts.debate_rebuttal,
                max_debate_rounds=2,
                deadlock_strategy="conservative",
            ),
        ),
        Strategy(
            name="english_debate",
            description="Two markers debate with rebuttals (max 2 rounds, conservative deadlock)",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
            debate_config=DebateConfig(
                mode="multi_round",
                marker_b_prompt_fn=english_prompts.english_comparative_anchor,
                marker_b_parse_fn=parse_comparative,
                rebuttal_fn=english_prompts.english_debate_rebuttal,
                max_debate_rounds=2,
                deadlock_strategy="conservative",
            ),
        ),

        # === PHASE 5: CROSS-MODEL COMPARISON ===

        # Maths criterion_decomposed on new models
        Strategy(
            name="maths_criterion_decomposed_gemini3",
            description="Criterion decomposed on Gemini 3 Pro (high thinking)",
            subject="maths",
            model=config.MODEL_GEMINI_3,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
            provider="gemini",
            thinking_level="high",
        ),
        Strategy(
            name="maths_criterion_decomposed_gemini31",
            description="Criterion decomposed on Gemini 3.1 Pro (low thinking)",
            subject="maths",
            model=config.MODEL_GEMINI_31,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
            provider="gemini",
            thinking_level="low",
        ),
        Strategy(
            name="maths_criterion_decomposed_claude",
            description="Criterion decomposed on Claude Opus 4.6",
            subject="maths",
            model=config.MODEL_CLAUDE,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
            provider="anthropic",
        ),
        Strategy(
            name="maths_criterion_decomposed_gpt",
            description="Criterion decomposed on GPT-5.2",
            subject="maths",
            model=config.MODEL_GPT,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.criterion_decomposed,
            parse_fn=parse_criterion,
            provider="openai",
        ),

        # English comparative_anchor on new models
        Strategy(
            name="english_comparative_anchor_gemini31",
            description="Comparative anchor on Gemini 3.1 Pro (low thinking)",
            subject="english",
            model=config.MODEL_GEMINI_31,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_comparative_anchor,
            parse_fn=parse_comparative,
            thinking_level="low",
            provider="gemini",
        ),
        Strategy(
            name="english_comparative_anchor_claude",
            description="Comparative anchor on Claude Opus 4.6",
            subject="english",
            model=config.MODEL_CLAUDE,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_comparative_anchor,
            parse_fn=parse_comparative,
            provider="anthropic",
        ),
        Strategy(
            name="english_comparative_anchor_gpt",
            description="Comparative anchor on GPT-5.2",
            subject="english",
            model=config.MODEL_GPT,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=english_prompts.english_comparative_anchor,
            parse_fn=parse_comparative,
            provider="openai",
        ),

        # === PHASE 7: PDF-NATIVE STRATEGIES ===

        Strategy(
            name="maths_pdf_baseline",
            description="PDF multimodal: full submission images + text rubric",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.pdf_baseline,
            parse_fn=parse_simple,
        ),
        Strategy(
            name="maths_pdf_criterion",
            description="PDF multimodal: images + per-criterion marking",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.pdf_criterion_decomposed,
            parse_fn=parse_criterion,
        ),
        Strategy(
            name="maths_pdf_conservative",
            description="PDF multimodal: images + strict conservative marking",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.pdf_conservative,
            parse_fn=parse_simple,
        ),
        Strategy(
            name="maths_pdf_visual_rigorous",
            description="PDF multimodal: enhanced visual verification for graph/diagram questions",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.pdf_visual_rigorous,
            parse_fn=parse_simple,
        ),
        Strategy(
            name="maths_pdf_visual_v2",
            description="PDF multimodal: forced part-by-part scoring with strict graph uncertainty",
            subject="maths",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=maths_prompts.pdf_visual_v2,
            parse_fn=parse_criterion,
        ),
    ]


def build_generic_strategies(subject_slug: str, display_name: str) -> list[Strategy]:
    """Build generic strategies for a custom subject.

    Returns baseline, criterion-decomposed, and conservative strategies
    that work with any marking_guide + student_answer pair.
    """
    model = config.MODEL_DEFAULT

    return [
        Strategy(
            name=f"{subject_slug}_baseline",
            description=f"{display_name}: generic baseline marking",
            subject=subject_slug,
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=generic_prompts.generic_baseline,
            parse_fn=parse_simple,
        ),
        Strategy(
            name=f"{subject_slug}_criterion_decomposed",
            description=f"{display_name}: marks each criterion independently then sums",
            subject=subject_slug,
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=generic_prompts.generic_criterion_decomposed,
            parse_fn=parse_criterion,
        ),
        Strategy(
            name=f"{subject_slug}_conservative",
            description=f"{display_name}: strict conservative marking",
            subject=subject_slug,
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=None,
            prompt_fn=generic_prompts.generic_conservative,
            parse_fn=parse_simple,
        ),
    ]

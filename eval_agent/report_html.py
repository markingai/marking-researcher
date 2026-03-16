"""Comprehensive HTML report generator for marking evaluation results.

Aggregates all evaluation results across phases and models into a single
self-contained HTML file with inline CSS and Chart.js visualisations.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import config


# ---------------------------------------------------------------------------
# Phase mapping
# ---------------------------------------------------------------------------

PHASE_MAP: dict[str, int] = {
    # Phase 1 -- baseline strategies
    "maths_baseline": 1,
    "maths_criterion_decomposed": 1,
    "maths_few_shot": 1,
    "maths_mark_verify": 1,
    "maths_rubric_anchor": 1,
    "maths_conservative": 1,
    "english_baseline": 1,
    "english_criterion_decomposed": 1,
    "english_anchor_examples": 1,
    "english_strict_range": 1,
    # Phase 2 -- half-marks
    "maths_criterion_conservative": 2,
    "english_halfmark_criterion": 2,
    "english_halfmark_exemplar": 2,
    # Phase 3 -- deep English
    "english_forced_independence": 3,
    "english_level_descriptors": 3,
    "english_full_exemplars": 3,
    "english_flash_ensemble": 3,
    "english_higher_thinking": 3,
    # Phase 4 -- scorecard-inspired
    "english_scorecard": 4,
    "english_cascade": 4,
    "english_comparative_anchor": 4,
    # Phase 6 -- debate strategies
    "maths_moderated": 6,
    "english_moderated": 6,
    "maths_panel": 6,
    "english_panel": 6,
    "maths_dual_adjudicate": 6,
    "english_dual_adjudicate": 6,
    "maths_debate": 6,
    "english_debate": 6,
    # Phase 5 -- cross-model
    "maths_criterion_decomposed_gemini3": 5,
    "maths_criterion_decomposed_gemini31": 5,
    "maths_criterion_decomposed_claude": 5,
    "maths_criterion_decomposed_gpt": 5,
    "english_comparative_anchor_gemini31": 5,
    "english_comparative_anchor_claude": 5,
    "english_comparative_anchor_gpt": 5,
}

MODEL_COLORS: dict[str, str] = {
    "gemini25pro": "#4285F4",
    "gemini25flash": "#7BAAF7",
    "gemini3": "#0F9D58",
    "gemini31": "#34A853",
    "claude": "#D97706",
    "gpt": "#10B981",
}

MODEL_LABELS: dict[str, str] = {
    "gemini25pro": "Gemini 2.5 Pro",
    "gemini25flash": "Gemini 2.5 Flash",
    "gemini3": "Gemini 3 Pro",
    "gemini31": "Gemini 3.1 Pro",
    "claude": "Claude Opus 4.6",
    "gpt": "GPT-5.2",
}

STRATEGY_DESCRIPTIONS: dict[str, str] = {
    # Maths
    "maths_baseline": "Replicates current n8n production marking prompt. Control group.",
    "maths_criterion_decomposed": "Breaks marking guide into numbered sub-criteria, scores each independently, then sums. Best maths strategy.",
    "maths_few_shot": "Includes 2-3 correctly-marked example answers per question in the prompt for calibration.",
    "maths_mark_verify": "Two-pass: first marks normally, second pass adversarially reviews the mark.",
    "maths_rubric_anchor": "Describes what each score level looks like, asks 'which level matches best?' instead of 'what mark?'",
    "maths_conservative": "Baseline prompt with added 'when in doubt, choose the lower score' language.",
    "maths_criterion_conservative": "Combines criterion decomposition with conservative bias language. Zero bias but slightly lower accuracy.",
    # English
    "english_baseline": "Holistic essay scoring with full rubric and source texts. No decomposition.",
    "english_criterion_decomposed": "Scores 4 rubric criteria independently (Content, Evidence, Coherence, Conventions), averages.",
    "english_anchor_examples": "Includes 3 calibration essays (low/mid/high) truncated to 800 chars.",
    "english_strict_range": "Baseline plus instruction that 'most essays score 3-4.5'.",
    "english_halfmark_criterion": "Criterion decomposed allowing 0.5 increment scoring in the output.",
    "english_halfmark_exemplar": "Half-mark scoring combined with calibration exemplars at each level.",
    "english_forced_independence": "Anti-criterion-collapse: forces each criterion to be scored independently with explicit guards against all-same scores.",
    "english_level_descriptors": "For each criterion, includes exact rubric text for levels 2-5 and asks 'which level descriptor best matches?'",
    "english_full_exemplars": "Provides full exemplar essays at scores 2, 3, 4, 5 from outside the sample for calibration.",
    "english_flash_ensemble": "Runs 3x on Gemini Flash (cheaper model), averages the scores. Tests if consensus beats single Pro run.",
    "english_higher_thinking": "Same as forced_independence but with doubled thinking budget (8192 vs 4096 tokens).",
    "english_scorecard": "LLM extracts 15 binary/ordinal signals (not scores). Deterministic Python code maps signals to marks. Eliminates score compression but over-marks.",
    "english_cascade": "Two-pass coarse-to-fine: first classifies into LOW/MID/HIGH band, then discriminates within band.",
    "english_comparative_anchor": "Compares essay to score-3 and score-4 exemplars per criterion (WORSE/EQUAL/BETTER). Best English strategy.",
    # Phase 5 cross-model
    "maths_criterion_decomposed_gemini3": "Same criterion decomposition strategy run on Gemini 3 Pro (GA) with high thinking.",
    "maths_criterion_decomposed_gemini31": "Same criterion decomposition strategy run on Gemini 3.1 Pro (preview) with low thinking.",
    "maths_criterion_decomposed_claude": "Same criterion decomposition strategy run on Claude Opus 4.6.",
    "maths_criterion_decomposed_gpt": "Same criterion decomposition strategy run on GPT-5.2.",
    "english_comparative_anchor_gemini31": "Same comparative anchor strategy run on Gemini 3.1 Pro instead of 2.5 Pro.",
    "english_comparative_anchor_claude": "Same comparative anchor strategy run on Claude Opus 4.6.",
    "english_comparative_anchor_gpt": "Same comparative anchor strategy run on GPT-5.2.",
    # Phase 6: debate strategies
    "maths_moderated": "Two-pass debate: criterion decomposition marking + independent moderator review. Tests if a second examiner catches errors.",
    "english_moderated": "Two-pass debate: comparative anchor marking + independent moderator review. The moderator independently evaluates the essay before comparing to the first mark.",
    "maths_panel": "3 independent markers (criterion, conservative, rubric_anchor) vote. Resolution: unanimous > majority > median.",
    "english_panel": "3 independent markers (forced_independence, level_descriptors, comparative_anchor) vote. Resolution: unanimous > majority > median.",
    "maths_dual_adjudicate": "Two markers (criterion + conservative) mark independently. If they disagree, a chief examiner adjudicates.",
    "english_dual_adjudicate": "Two markers (forced_independence + comparative_anchor) mark independently. Chief examiner adjudicates disagreements.",
    "maths_debate": "Two markers give independent marks then debate in up to 2 rounds of rebuttals (CONCEDE/HOLD/COMPROMISE). Conservative deadlock.",
    "english_debate": "Two markers debate with iterative rebuttals. Each round, markers can CONCEDE, HOLD, or COMPROMISE. Conservative deadlock resolution.",
}

STRATEGY_DEEP_DIVE: dict[str, dict] = {
    # === MATHS STRATEGIES ===
    "maths_baseline": {
        "concept": "Replicates the current Marking.ai production prompt used in the n8n pipeline. Serves as the control group to measure the existing system's accuracy before any improvements.",
        "methodology": "Single-pass holistic marking. The LLM receives the question text, marking guide, and student answer. It is instructed to mark strictly against the guide and return a JSON object with an integer mark and justification. No decomposition, no exemplars, no multi-pass verification.",
        "recommendations": "Use as a baseline reference only. Not recommended for production due to lower accuracy and over-marking bias compared to criterion-decomposed approaches.",
        "tags": ["single-pass", "holistic", "baseline", "maths"],
    },
    "maths_criterion_decomposed": {
        "concept": "Decomposes the marking guide into individual criterion points and scores each independently, then sums. Prevents the LLM from making holistic judgments that skip or conflate mark points.",
        "methodology": "The LLM identifies each distinct mark point in the marking guide. For each criterion, it independently evaluates whether the student's answer meets it and awards marks. The total mark is the sum of all criterion scores. Returns a structured JSON with per-criterion breakdown (criterion name, marks_awarded, max_marks, reason) plus total_mark.",
        "recommendations": "Best maths strategy overall (82% ExRnd on Gemini 2.5 Pro). Recommended as the default for maths marking. Works especially well on multi-part questions where individual mark points are clearly defined in the guide.",
        "tags": ["criterion-decomposed", "structured", "best-maths", "maths"],
    },
    "maths_few_shot": {
        "concept": "Includes correctly-marked example answers in the prompt to calibrate the model's scoring behaviour before it marks the actual student answer.",
        "methodology": "2-3 example answers per question type are selected from non-sample rows where the human mark and existing AI mark agree. These examples are prepended to the prompt as 'correctly marked samples'. The model then marks the student answer using the same rubric.",
        "recommendations": "Strong performance (80% ExRnd) with good calibration. Consider when marking novel question types where the model may lack implicit understanding of scoring standards.",
        "tags": ["few-shot", "calibration", "maths"],
    },
    "maths_mark_verify": {
        "concept": "Two-pass approach: the model first marks normally, then adversarially reviews its own mark. Targets over-marking by adding a critical review step.",
        "methodology": "Pass 1: Standard marking prompt generates mark + justification. Pass 2: The model receives its own mark and justification back, along with the instruction to check against the rubric and identify if it over-awarded or under-awarded marks. Returns a verified_mark and whether it changed.",
        "recommendations": "Solid accuracy (80% ExRnd) with reduced bias compared to baseline. Good choice when over-marking is a concern. The second pass adds cost but catches systematic errors.",
        "tags": ["two-pass", "self-review", "maths"],
    },
    "maths_rubric_anchor": {
        "concept": "Reframes scoring as level-matching rather than direct mark assignment. For each possible score, describes what that level's answer looks like, then asks 'which level matches best?'",
        "methodology": "The prompt describes answer quality at each score level (0, 1, 2 for a 2-mark question). The model matches the student's answer to the closest level description rather than deciding a mark directly.",
        "recommendations": "Good performance (78% ExRnd) but slightly behind criterion decomposition. Most useful for questions where the marking guide naturally describes quality levels rather than discrete criteria.",
        "tags": ["level-matching", "rubric-anchored", "maths"],
    },
    "maths_conservative": {
        "concept": "Baseline prompt with explicit conservative bias language added: 'when in doubt, choose the lower score'. Tests whether instruction alone can fix the over-marking tendency.",
        "methodology": "Identical to baseline except for added language instructing the model to err on the side of under-marking. No structural changes to the prompt or response format.",
        "recommendations": "Effective at reducing over-marking bias (76% ExRnd, best bias of -0.08) but at the cost of slightly increased under-marking. Useful as a component in hybrid strategies.",
        "tags": ["conservative", "bias-correction", "maths"],
    },
    "maths_criterion_conservative": {
        "concept": "Combines the two best maths approaches: criterion decomposition's structural accuracy with conservative bias language to eliminate the residual over-marking.",
        "methodology": "Uses the criterion-decomposed prompt structure (per-criterion scoring) combined with explicit conservative language. Each criterion is scored independently with the instruction to prefer the lower mark when evidence is ambiguous.",
        "recommendations": "Achieved perfect zero bias (+0.00) at 80% ExRnd. Best choice when unbiased marking is the priority, even at a small accuracy trade-off vs pure criterion decomposition.",
        "tags": ["criterion-decomposed", "conservative", "hybrid", "maths"],
    },
    # === ENGLISH STRATEGIES ===
    "english_baseline": {
        "concept": "Holistic essay scoring using the full rubric and source texts. No decomposition or calibration aids.",
        "methodology": "The LLM receives the complete NY Regents rubric, all 4 source texts, and the student essay. It is asked to score holistically on a 1-6 scale with justification.",
        "recommendations": "Poor English performance (34% ExRnd). Suffers from severe score compression (64% of marks = 3) and strong under-marking bias (-0.69). Not suitable for production.",
        "tags": ["holistic", "baseline", "english"],
    },
    "english_criterion_decomposed": {
        "concept": "Scores 4 rubric criteria independently (Content & Analysis, Command of Evidence, Coherence/Organization/Style, Control of Conventions), then averages and rounds.",
        "methodology": "The LLM evaluates each of the 4 NY Regents criteria separately on a 1-6 scale. Returns per-criterion scores plus a final mark computed as the rounded average of the 4 scores.",
        "recommendations": "Improved over baseline (46% ExRnd) but still suffers from criterion collapse: the model assigns the same score to all 4 criteria 62% of the time, suggesting it makes one holistic decision and retrofits.",
        "tags": ["criterion-decomposed", "english"],
    },
    "english_anchor_examples": {
        "concept": "Includes 3 calibration essays (low/mid/high quality) truncated to 800 characters to anchor the model's scoring expectations.",
        "methodology": "Three exemplar essays at approximate scores 2, 3.5, and 5 are included in the prompt, each truncated to 800 characters with their human-assigned marks. The model scores the target essay after seeing these anchors.",
        "recommendations": "Moderate performance (48% ExRnd rounded). Truncation limits effectiveness since essay quality nuances are lost. Full exemplars work better (see english_full_exemplars).",
        "tags": ["few-shot", "calibration", "english"],
    },
    "english_strict_range": {
        "concept": "Baseline with added score distribution calibration: instructs the model that 'most essays score 3-4.5' to prevent extreme scores.",
        "methodology": "Identical to baseline except for added language about the expected score distribution. Aims to prevent the model from over-concentrating on score 3.",
        "recommendations": "Minimal improvement over baseline (34% ExRnd). Distribution instruction alone is insufficient to fix the underlying calibration problem.",
        "tags": ["calibration", "english"],
    },
    "english_halfmark_criterion": {
        "concept": "Criterion decomposed with 0.5-increment scoring to match the half-marks that human markers commonly give.",
        "methodology": "Same as english_criterion_decomposed but the response schema allows float values in 0.5 increments. Final mark is snapped to the nearest 0.5.",
        "recommendations": "Did not improve accuracy (30% ExRnd). The model still compresses to whole-number scores even when half-marks are allowed, suggesting the issue is discrimination ability rather than output format.",
        "tags": ["half-marks", "criterion-decomposed", "english"],
    },
    "english_halfmark_exemplar": {
        "concept": "Combines half-mark output with calibration exemplars at each score level.",
        "methodology": "Allows 0.5-increment scoring plus includes exemplar essays at different score levels. Aims to address both format mismatch and calibration.",
        "recommendations": "Worse than criterion-only approach (32% ExRnd). Half-marks combined with exemplars introduced more noise without improving discrimination.",
        "tags": ["half-marks", "few-shot", "english"],
    },
    "english_forced_independence": {
        "concept": "Directly attacks the criterion collapse problem by forcing the model to score each criterion independently with explicit anti-collapse guards.",
        "methodology": "Adds explicit instructions: 'Each criterion MUST be scored independently. Criteria SHOULD have DIFFERENT scores. It is RARE for all 4 criteria to have the same score.' Forces the model to justify why scores differ across criteria.",
        "recommendations": "Reduced all-same-score rate from 62% to 34% but didn't improve accuracy (50% ExRnd). Proves the issue is the LLM's inability to distinguish quality levels, not just criterion coupling.",
        "tags": ["independence", "anti-collapse", "english"],
    },
    "english_level_descriptors": {
        "concept": "For each criterion, includes the exact rubric text for levels 2-5 and reframes scoring as 'which level descriptor best matches?' rather than 'what score?'",
        "methodology": "The full rubric level descriptors are embedded in the prompt for each of the 4 criteria. The model matches the essay to the closest descriptor rather than choosing a number. Also includes generic constraint enforcement for special scoring rules.",
        "recommendations": "Phase 3 best (56% ExRnd). The level-matching approach improves calibration by grounding scores in rubric language. Good foundation for further refinement.",
        "tags": ["level-matching", "rubric-grounded", "english"],
    },
    "english_full_exemplars": {
        "concept": "Provides full (not truncated) exemplar essays at scores 2, 3, 4, and 5 from outside the sample, combined with criterion decomposition.",
        "methodology": "Selects exemplar essays from the evaluation data at each target score level. Full text is included (no 800-char truncation). Combined with criterion decomposition for structured scoring.",
        "recommendations": "Disappointing results (40% ExRnd). Full exemplars made the prompt very long (18K+ chars) and the model appeared to fixate on surface similarities rather than rubric-aligned features.",
        "tags": ["full-exemplars", "calibration", "english"],
    },
    "english_flash_ensemble": {
        "concept": "Runs the prompt 3 times on Gemini Flash (a cheaper, faster model) and averages the scores. Tests if consensus from multiple cheap runs beats a single expensive Pro run.",
        "methodology": "Uses the forced_independence prompt run 3 times with temperature=0.3 on Gemini 2.5 Flash. The 3 marks are averaged and rounded to produce the final score.",
        "recommendations": "Underperformed single Pro run (42% ExRnd). Flash model has weaker reasoning for essay analysis. Multi-run consensus doesn't compensate for lower model capability.",
        "tags": ["ensemble", "flash", "cheap", "english"],
    },
    "english_higher_thinking": {
        "concept": "Tests whether the default 4096 thinking token budget is insufficient for complex essay analysis by doubling it to 8192.",
        "methodology": "Same as forced_independence but with thinking_budget=8192 instead of 4096. If accuracy improves, it suggests the model needs more 'thinking time' for essays.",
        "recommendations": "No improvement (50% ExRnd, same as forced_independence). More thinking tokens doesn't help; the bottleneck is calibration and discrimination, not reasoning depth.",
        "tags": ["thinking-budget", "english"],
    },
    "english_scorecard": {
        "concept": "Separates the LLM from scoring entirely. The LLM extracts 15 binary/ordinal factual signals about the essay (e.g., 'has_traceable_evidence?', 'claim_quality: 0-4'). Deterministic Python code then maps signals to marks.",
        "methodology": "The LLM is told it's doing 'factual essay analysis' and never sees a score target. It answers 15 structured questions derived from rubric level descriptors. A separate scoring engine (scorecard_scorer.py) applies weighted signal-to-mark mapping with gate rules (blank=0, off-topic=max 1, <3 sources=max 3).",
        "recommendations": "Eliminated score compression (AI=3 at only 16%) and used the full score range, but severely over-marks (+0.55 bias, 36% ExRnd). Signal extraction works well but weights need tuning. Concept is proven for production use with proper calibration.",
        "tags": ["scorecard", "signal-extraction", "deterministic", "english"],
    },
    "english_cascade": {
        "concept": "Two-pass coarse-to-fine classification: first classifies the essay into a quality band (LOW/MID/HIGH), then makes a fine-grained distinction within that band.",
        "methodology": "Pass 1: Classify into LOW (1-2), MID (3-4), or HIGH (5-6) with band-level descriptions. Pass 2: Band-specific prompt with targeted discriminating features. For MID: 'Is the claim surface-level or specific? Is analysis emerging or appropriate?' Binary features map to the lower or upper score.",
        "recommendations": "Good accuracy (58% ExRnd) and reduced AI=3 compression to 56%. The coarse-to-fine decomposition simplifies each decision. Good alternative when exemplar essays aren't available.",
        "tags": ["two-pass", "cascade", "coarse-to-fine", "english"],
    },
    "english_comparative_anchor": {
        "concept": "Uses relative comparison instead of absolute scoring. The model compares the essay to two calibration exemplars (score-3 and score-4) on each criterion, judging WORSE/EQUAL/BETTER.",
        "methodology": "Two exemplar essays (one at human score 3, one at score 4) are included in the prompt. For each of 4 criteria, the model judges whether the target essay is WORSE, EQUAL, or BETTER than each exemplar. Deterministic code maps the 8 comparisons to criterion scores (2-5 range), averages, and rounds. Gate rules handle edge cases.",
        "recommendations": "Best English strategy (64% ExRnd on Gemini 2.5 Pro, 72% on Gemini 3.1 Pro). Dramatically reduced score compression (AI=3 at 26%). Relative judgment is fundamentally easier for LLMs than absolute scoring. Recommended as default for essay marking.",
        "tags": ["comparative", "relative-judgment", "best-english", "english"],
    },
    # === CROSS-MODEL VARIANTS ===
    "maths_criterion_decomposed_gemini3": {
        "concept": "Same criterion decomposition strategy tested on Gemini 3 Pro (GA model) to compare model performance using identical prompts.",
        "methodology": "Identical prompt and parsing logic to maths_criterion_decomposed. Only the model (gemini-3-pro-preview) and thinking level (high) differ. Uses Gemini API.",
        "recommendations": "76% ExRnd, slightly below Gemini 2.5 Pro (82%). Newer model not always better for mechanical marking tasks.",
        "tags": ["cross-model", "gemini-3", "maths"],
    },
    "maths_criterion_decomposed_gemini31": {
        "concept": "Same criterion decomposition strategy tested on Gemini 3.1 Pro (preview) to evaluate the latest Gemini model on maths marking.",
        "methodology": "Identical prompt and parsing to maths_criterion_decomposed. Uses gemini-3.1-pro-preview with thinkingLevel=low (preview API constraint). Same structured JSON output.",
        "recommendations": "74% ExRnd, significantly below Gemini 2.5 Pro (82%). Preview model has strict rate limits and slower response times. Over-marks on multi-part questions.",
        "tags": ["cross-model", "gemini-3.1", "maths"],
    },
    "maths_criterion_decomposed_claude": {
        "concept": "Same criterion decomposition strategy tested on Claude Opus 4.6 to compare Anthropic's flagship model against Gemini on maths marking.",
        "methodology": "Identical prompt logic. Uses Anthropic API with extended thinking and tool_use for structured output (Claude doesn't have native response_schema like Gemini).",
        "recommendations": "Compare against Gemini 2.5 Pro baseline to evaluate whether model choice or prompt design has more impact on maths accuracy.",
        "tags": ["cross-model", "claude", "anthropic", "maths"],
    },
    "maths_criterion_decomposed_gpt": {
        "concept": "Same criterion decomposition strategy tested on GPT-5.2 to compare OpenAI's model on maths marking.",
        "methodology": "Identical prompt logic. Uses OpenAI API with strict JSON schema mode for structured output. GPT has no native thinking/reasoning mode so it's added via system prompt.",
        "recommendations": "Compare against other models. OpenAI offers competitive pricing with aggressive cached input rates.",
        "tags": ["cross-model", "gpt", "openai", "maths"],
    },
    "english_comparative_anchor_gemini31": {
        "concept": "Best English strategy (comparative anchor) tested on Gemini 3.1 Pro to see if the newer model improves essay discrimination.",
        "methodology": "Identical prompt and comparative logic. Uses gemini-3.1-pro-preview with thinkingLevel=low. Same exemplar essays and deterministic scoring code.",
        "recommendations": "New best at 72% ExRnd with near-zero bias (+0.01). Gemini 3.1 Pro significantly outperforms 2.5 Pro on English essay marking despite being worse on maths. Recommended model for English marking.",
        "tags": ["cross-model", "gemini-3.1", "best-english", "english"],
    },
    "english_comparative_anchor_claude": {
        "concept": "Best English strategy tested on Claude Opus 4.6 to evaluate Anthropic's strongest reasoning model on essay marking.",
        "methodology": "Identical comparative anchor prompt. Uses Anthropic API. Claude's extended thinking may provide deeper essay analysis.",
        "recommendations": "Compare against Gemini models to determine if Claude's stronger reasoning helps with essay discrimination.",
        "tags": ["cross-model", "claude", "anthropic", "english"],
    },
    "english_comparative_anchor_gpt": {
        "concept": "Best English strategy tested on GPT-5.2 to evaluate OpenAI's model on essay marking.",
        "methodology": "Identical comparative anchor prompt. Uses OpenAI API with strict JSON schema for structured output.",
        "recommendations": "Compare against Gemini and Claude models on cost-effectiveness for essay marking.",
        "tags": ["cross-model", "gpt", "openai", "english"],
    },
    # === DEBATE STRATEGIES ===
    "maths_moderated": {
        "concept": "Mimics real-world teacher moderation: one AI marks using criterion decomposition, then a separate AI moderator independently reviews the mark and justification. The moderator can agree, adjust up, or adjust down.",
        "methodology": "Pass 1: Full criterion decomposition marking (same as the best maths strategy). Pass 2: An independent 'moderator' prompt receives the question, marking guide, student answer, AND the marker's mark + justification. The moderator forms their own judgment first, then compares. Returns a verified_mark with explanation of moderation decision.",
        "recommendations": "Tests whether a second review catches systematic marking errors. Cost is 2x single-pass. If the moderator frequently changes marks, it indicates the first pass has reliability issues.",
        "tags": ["two-pass", "moderation", "debate", "maths"],
    },
    "english_moderated": {
        "concept": "Mimics real-world essay moderation: one AI scores using comparative anchor judgment, then a separate AI moderator reviews the score. The moderator is briefed on common essay marking errors.",
        "methodology": "Pass 1: Comparative anchor scoring (best English strategy) comparing against score-3 and score-4 exemplars. Pass 2: Independent moderator receives the essay, rubric, source texts, and the marker's score + reasoning. The moderator is instructed to look for common errors like over-crediting surface-level analysis or under-crediting competent essays.",
        "recommendations": "Tests whether independent moderation improves English accuracy. Particularly useful for catching over- or under-scoring at the 3-4 boundary.",
        "tags": ["two-pass", "moderation", "debate", "english"],
    },
    "maths_panel": {
        "concept": "Expert panel of 3 independent AI markers each using a different marking strategy. Resolution by majority vote or median when no majority exists — analogous to a moderation panel in real examination boards.",
        "methodology": "Three markers run independently: (1) criterion decomposed (best maths strategy), (2) criterion conservative (anti-over-mark variant), (3) rubric anchor (level-matching approach). If all 3 agree → unanimous. If 2/3 agree → majority vote wins. If all different → median mark is used. 3 API calls per sample.",
        "recommendations": "Tests whether aggregating diverse marking perspectives improves accuracy over a single strategy. Expect higher accuracy but 3x the cost. Best for high-stakes assessments where accuracy justifies expense.",
        "tags": ["panel", "multi-marker", "debate", "maths", "ensemble"],
    },
    "english_panel": {
        "concept": "Expert panel of 3 independent AI markers each using a different essay scoring approach. Combines criterion-based, level-descriptor, and comparative-anchor perspectives for robust consensus.",
        "methodology": "Three markers run independently: (1) forced independence (criterion decomposed with anti-collapse guards), (2) level descriptors (match to rubric level text), (3) comparative anchor (relative comparison to exemplars). Resolution: unanimous > majority > median. 3 API calls per sample.",
        "recommendations": "Tests whether combining diverse essay scoring methodologies improves English accuracy. The three strategies represent fundamentally different approaches: absolute (criterion), descriptive (level match), and relative (comparison).",
        "tags": ["panel", "multi-marker", "debate", "english", "ensemble"],
    },
    "maths_dual_adjudicate": {
        "concept": "Two independent markers grade the same work. If they disagree, a third AI acting as chief examiner reviews both arguments and makes the final call — just like real examination board adjudication.",
        "methodology": "Marker A uses criterion decomposed (best strategy), Marker B uses criterion conservative (strict variant). If marks match → accepted. If they differ, a chief examiner adjudicator receives: question, marking guide, student answer, both marks, and both justifications. The adjudicator must determine which marker's reasoning better aligns with the marking guide. 2-3 API calls per sample.",
        "recommendations": "Tests whether adversarial marker pairing (optimistic vs conservative) with adjudication improves accuracy. The adjudicator has access to both arguments, so should make better decisions than either marker alone.",
        "tags": ["dual-marker", "adjudicator", "debate", "maths"],
    },
    "english_dual_adjudicate": {
        "concept": "Two independent AI markers score the essay using different methodologies. On disagreement, a chief examiner adjudicator reviews both arguments against the rubric.",
        "methodology": "Marker A uses forced independence (criterion-based), Marker B uses comparative anchor (relative comparison). If scores match → accepted. If they differ, the adjudicator receives the essay, rubric, source texts, both scores, and both justifications. The adjudicator considers all four rubric criteria and determines the correct score. 2-3 API calls per sample.",
        "recommendations": "Tests whether pairing an absolute scorer (criterion) with a relative scorer (comparative) and adjudicating disagreements improves English accuracy, especially at the critical 3-4 boundary.",
        "tags": ["dual-marker", "adjudicator", "debate", "english"],
    },
    "maths_debate": {
        "concept": "Two AI markers engage in iterative debate rounds, arguing their case for the mark they believe is correct. In each round, a marker can CONCEDE (accept the other's mark), HOLD (maintain their position), or COMPROMISE (move to a middle position). Mimics real marking moderation meetings.",
        "methodology": "Round 0: Two markers independently mark using criterion decomposed and criterion conservative. If marks match → done. Rounds 1-2: Each marker sees the other's mark and argument, then must choose CONCEDE/HOLD/COMPROMISE with a revised mark and reasoning. If marks converge → done. After 2 rounds, if still deadlocked → take the lower (conservative) mark. 2-6 API calls per sample.",
        "recommendations": "Tests whether argumentative debate between markers leads to more accurate consensus than simple voting. The CONCEDE/HOLD/COMPROMISE framework forces markers to engage with each other's reasoning rather than just outputting marks.",
        "tags": ["multi-round", "debate", "rebuttal", "maths"],
    },
    "english_debate": {
        "concept": "Two AI markers argue over the correct essay score through iterative debate rounds. Each can CONCEDE, HOLD, or COMPROMISE based on the other's arguments. Tests whether reasoned argumentation improves scoring accuracy.",
        "methodology": "Round 0: Two markers independently score using forced independence and comparative anchor. If scores match → done. Rounds 1-2: Each marker sees the other's score and argument, must reason about whether the other's interpretation of the rubric is stronger. If scores converge → done. After 2 rounds, deadlock → conservative (lower) score. 2-6 API calls per sample.",
        "recommendations": "Tests whether multi-round debate improves English essay scoring. Particularly interesting for the 3-4 boundary where subjective rubric interpretation matters most. Higher cost but should reduce random scoring variance.",
        "tags": ["multi-round", "debate", "rebuttal", "english"],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_model(strategy_name: str) -> str:
    """Return a model key based on the strategy name."""
    if "_gemini31" in strategy_name:
        return "gemini31"
    if "_gemini3" in strategy_name:
        return "gemini3"
    if "_claude" in strategy_name:
        return "claude"
    if "_gpt" in strategy_name:
        return "gpt"
    if "flash_ensemble" in strategy_name:
        return "gemini25flash"
    return "gemini25pro"


def _detect_phase(strategy_name: str) -> int:
    """Return the phase number for a strategy."""
    if strategy_name in PHASE_MAP:
        return PHASE_MAP[strategy_name]
    # Phase 5: cross-model variants
    if strategy_name.endswith(("_gemini3", "_gemini31", "_claude", "_gpt")):
        return 5
    return 0  # unknown


def _extract_timestamp(filename: str) -> str:
    """Extract YYYYMMDD_HHMMSS from a CSV filename."""
    m = re.search(r"(\d{8}_\d{6})", filename)
    return m.group(1) if m else "00000000_000000"


def _timestamp_to_display(ts: str) -> str:
    """Convert YYYYMMDD_HHMMSS to a human-readable string."""
    try:
        dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


# ---------------------------------------------------------------------------
# Data loading and deduplication
# ---------------------------------------------------------------------------


def _load_csv_rows(csv_path: Path) -> list[dict]:
    """Load a single eval_results CSV into a list of row dicts."""
    rows: list[dict] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _deduplicate_csvs(csv_paths: list[Path]) -> list[dict]:
    """Load all CSVs and deduplicate: keep only the LATEST file per strategy.

    CSV filenames follow the pattern ``eval_results_YYYYMMDD_HHMMSS.csv``.
    When the same ``strategy_name`` appears in multiple files we keep only
    the rows from the file with the most recent timestamp.
    """
    # Sort by timestamp ascending so later files overwrite earlier ones
    sorted_paths = sorted(csv_paths, key=lambda p: _extract_timestamp(p.name))

    # Track which file is the latest for each strategy
    strategy_latest_file: dict[str, Path] = {}
    strategy_rows: dict[str, list[dict]] = {}

    for path in sorted_paths:
        rows = _load_csv_rows(path)
        strategies_in_file: set[str] = set()
        for row in rows:
            sname = row.get("strategy_name", "")
            if sname:
                strategies_in_file.add(sname)

        # For each strategy found in this file, update the latest mapping
        for sname in strategies_in_file:
            strategy_latest_file[sname] = path

        # Bucket rows by strategy
        file_strategy_rows: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            sname = row.get("strategy_name", "")
            if sname:
                file_strategy_rows[sname].append(row)

        for sname, srows in file_strategy_rows.items():
            strategy_rows.setdefault(sname, {})
            strategy_rows[sname] = (path, srows)  # type: ignore[assignment]

    # Now collect only rows from the latest file per strategy
    final_rows: list[dict] = []
    for sname, (path, srows) in strategy_rows.items():  # type: ignore[misc]
        if path == strategy_latest_file.get(sname):
            final_rows.extend(srows)

    return final_rows


def _eval_results_to_dicts(results: list) -> list[dict]:
    """Convert EvalResult objects to row dicts matching CSV column names."""
    rows: list[dict] = []
    for r in results:
        if r.error or r.ai_mark < 0:
            se = ""
            ae = ""
            exact = ""
            within = ""
        else:
            se = r.ai_mark - r.human_mark
            ae = abs(se)
            exact = "1" if r.ai_mark == r.human_mark else "0"
            within = "1" if abs(se) <= 1 else "0"
        rows.append({
            "strategy_name": r.strategy_name,
            "subject": r.subject,
            "question_number": r.question_number,
            "row_id": r.row_id,
            "total_marks": str(r.total_marks),
            "human_mark": str(r.human_mark),
            "ai_mark": str(r.ai_mark),
            "error": str(r.error),
            "abs_error": str(ae),
            "signed_error": str(se),
            "exact_match": str(exact),
            "within_1": str(within),
            "justification": r.justification,
            "cost_usd": f"{r.usage.cost_usd():.6f}" if hasattr(r, 'usage') and r.usage else "0",
        })
    return rows


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def _compute_strategy_metrics(rows: list[dict]) -> dict:
    """Compute aggregate metrics for a list of row dicts (one strategy).

    Returns a dict with keys: n, exact_match_pct, exact_match_rounded_pct,
    within_1_pct, mae, mean_signed_error, over_mark_pct, under_mark_pct,
    subject, model, model_color, model_label, phase.
    """
    valid = []
    for row in rows:
        err = row.get("error", "False")
        if err in ("True", "1", True):
            continue
        try:
            ai = float(row["ai_mark"])
            hm = float(row["human_mark"])
        except (ValueError, KeyError):
            continue
        if ai < 0:
            continue
        valid.append((hm, ai))

    n = len(valid)
    if n == 0:
        return {"n": 0}

    exact = sum(1 for hm, ai in valid if ai == hm)
    exact_rounded = sum(1 for hm, ai in valid if ai == round(hm))
    within_1 = sum(1 for hm, ai in valid if abs(ai - hm) <= 1)
    errors = [ai - hm for hm, ai in valid]
    abs_errors = [abs(e) for e in errors]
    over = sum(1 for e in errors if e > 0)
    under = sum(1 for e in errors if e < 0)

    strategy_name = rows[0].get("strategy_name", "")
    subject = rows[0].get("subject", "")
    model_key = _detect_model(strategy_name)
    phase = _detect_phase(strategy_name)

    # Aggregate cost (may be missing from historical CSVs)
    total_cost = 0.0
    has_cost = False
    for row in rows:
        c = row.get("cost_usd", "")
        if c and c != "0":
            try:
                total_cost += float(c)
                has_cost = True
            except ValueError:
                pass

    return {
        "strategy_name": strategy_name,
        "subject": subject,
        "n": n,
        "exact_match_pct": round(exact / n * 100, 1),
        "exact_match_rounded_pct": round(exact_rounded / n * 100, 1),
        "within_1_pct": round(within_1 / n * 100, 1),
        "mae": round(sum(abs_errors) / n, 3),
        "mean_signed_error": round(sum(errors) / n, 3),
        "over_mark_pct": round(over / n * 100, 1),
        "under_mark_pct": round(under / n * 100, 1),
        "model": model_key,
        "model_color": MODEL_COLORS.get(model_key, "#4285F4"),
        "model_label": MODEL_LABELS.get(model_key, "Unknown"),
        "phase": phase,
        "cost_usd": round(total_cost, 4) if has_cost else None,
    }


def _build_report_data(all_rows: list[dict]) -> dict:
    """Build the complete data payload that gets embedded in the HTML."""

    # Group rows by strategy
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for row in all_rows:
        sname = row.get("strategy_name", "")
        if sname:
            by_strategy[sname].append(row)

    # Compute metrics per strategy
    strategy_metrics: list[dict] = []
    for sname, srows in sorted(by_strategy.items()):
        m = _compute_strategy_metrics(srows)
        if m["n"] > 0:
            strategy_metrics.append(m)

    # Split by subject
    maths_metrics = [m for m in strategy_metrics if m["subject"] == "maths"]
    english_metrics = [m for m in strategy_metrics if m["subject"] == "english"]

    # Sort by exact_match_rounded_pct descending
    maths_metrics.sort(key=lambda m: m["exact_match_rounded_pct"], reverse=True)
    english_metrics.sort(key=lambda m: m["exact_match_rounded_pct"], reverse=True)

    # Executive summary
    total_strategies = len(strategy_metrics)
    total_evals = sum(m["n"] for m in strategy_metrics)

    best_maths = maths_metrics[0] if maths_metrics else None
    best_english = english_metrics[0] if english_metrics else None

    # Determine date range from strategy rows
    timestamps: set[str] = set()
    for row in all_rows:
        # We don't have timestamps in rows, so we'll leave this to the
        # caller -- the HTML template shows the generation timestamp instead.
        pass

    # Cross-model comparison data (Phase 5)
    phase5 = [m for m in strategy_metrics if m["phase"] == 5]
    cross_model: dict[str, dict[str, dict]] = defaultdict(dict)
    for m in phase5:
        # Extract base strategy name (remove model suffix)
        base = m["strategy_name"]
        for suffix in ("_gemini31", "_gemini3", "_claude", "_gpt"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        cross_model[base][m["model"]] = m

    # Score distribution for top 3 English strategies
    score_distributions: list[dict] = []
    for m in english_metrics[:3]:
        sname = m["strategy_name"]
        srows = by_strategy[sname]
        human_dist: dict[str, int] = defaultdict(int)
        ai_dist: dict[str, int] = defaultdict(int)
        for row in srows:
            err = row.get("error", "False")
            if err in ("True", "1", True):
                continue
            try:
                hm = float(row["human_mark"])
                ai = float(row["ai_mark"])
            except (ValueError, KeyError):
                continue
            if ai < 0:
                continue
            human_dist[str(round(hm))] = human_dist.get(str(round(hm)), 0) + 1
            ai_dist[str(round(ai))] = ai_dist.get(str(round(ai)), 0) + 1
        score_distributions.append({
            "strategy_name": sname,
            "human_dist": dict(human_dist),
            "ai_dist": dict(ai_dist),
        })

    # Score compression: AI=3 percentage by English strategy (sorted by phase)
    compression_data: list[dict] = []
    for m in sorted(english_metrics, key=lambda x: (x["phase"], x["strategy_name"])):
        sname = m["strategy_name"]
        srows = by_strategy[sname]
        total_valid = 0
        ai_eq_3 = 0
        for row in srows:
            err = row.get("error", "False")
            if err in ("True", "1", True):
                continue
            try:
                ai = float(row["ai_mark"])
            except (ValueError, KeyError):
                continue
            if ai < 0:
                continue
            total_valid += 1
            if round(ai) == 3:
                ai_eq_3 += 1
        if total_valid > 0:
            compression_data.append({
                "strategy_name": sname,
                "ai_3_pct": round(ai_eq_3 / total_valid * 100, 1),
                "phase": m["phase"],
            })

    # Phase progress: best ExRnd% per phase per subject
    phase_progress: dict[str, dict[int, float]] = {"maths": {}, "english": {}}
    for m in strategy_metrics:
        subj = m["subject"]
        phase = m["phase"]
        if phase == 0:
            continue
        current_best = phase_progress[subj].get(phase, 0)
        if m["exact_match_rounded_pct"] > current_best:
            phase_progress[subj][phase] = m["exact_match_rounded_pct"]

    total_cost = sum(m.get("cost_usd", 0) or 0 for m in strategy_metrics)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_strategies": total_strategies,
        "total_evals": total_evals,
        "total_cost": round(total_cost, 2) if total_cost > 0 else None,
        "best_maths": best_maths,
        "best_english": best_english,
        "maths_metrics": maths_metrics,
        "english_metrics": english_metrics,
        "cross_model": {
            base: {model: metrics for model, metrics in models.items()}
            for base, models in cross_model.items()
        },
        "score_distributions": score_distributions,
        "compression_data": compression_data,
        "phase_progress": {
            subj: {str(k): v for k, v in sorted(phases.items())}
            for subj, phases in phase_progress.items()
        },
        "model_colors": MODEL_COLORS,
        "model_labels": MODEL_LABELS,
        "strategy_descriptions": STRATEGY_DESCRIPTIONS,
        "strategy_deep_dive": STRATEGY_DEEP_DIVE,
    }


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Marking.ai Evaluation Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    line-height: 1.6;
    padding: 24px;
    min-height: 100vh;
  }

  .container { max-width: 1400px; margin: 0 auto; }

  h1 {
    font-size: 2rem;
    font-weight: 700;
    color: #ffffff;
    margin-bottom: 4px;
  }
  h2 {
    font-size: 1.5rem;
    font-weight: 600;
    color: #ffffff;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 2px solid #4285F4;
    display: inline-block;
  }
  h3 {
    font-size: 1.15rem;
    font-weight: 500;
    color: #c0c0c0;
    margin-bottom: 12px;
  }

  .subtitle {
    color: #888;
    font-size: 0.9rem;
    margin-bottom: 24px;
  }

  .card {
    background: #16213e;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 24px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
  }

  .section-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, #4285F4, transparent);
    margin: 40px 0;
  }

  /* Summary cards row */
  .summary-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: #0f3460;
    border-radius: 10px;
    padding: 20px;
    text-align: center;
  }
  .stat-card .stat-value {
    font-size: 2rem;
    font-weight: 700;
    color: #4285F4;
  }
  .stat-card .stat-label {
    font-size: 0.85rem;
    color: #999;
    margin-top: 4px;
  }
  .stat-card.best .stat-value { color: #34A853; }
  .stat-card.warn .stat-value { color: #D97706; }

  /* Tables */
  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    margin-top: 16px;
  }
  .data-table th {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 2px solid #4285F4;
    color: #aaa;
    font-weight: 600;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }
  .data-table th.num { text-align: right; }
  .data-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #1a2744;
    white-space: nowrap;
  }
  .data-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .data-table tr:hover { background: #1a2744; }
  .data-table tr.highlight { background: rgba(66, 133, 244, 0.15); }

  .model-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 500;
    color: #fff;
  }

  /* Chart containers */
  .chart-container {
    position: relative;
    height: 450px;
    margin: 16px 0;
  }
  .chart-container.short { height: 350px; }
  .chart-container.tall { height: 500px; }

  /* Two-column layout */
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }
  @media (max-width: 1000px) {
    .two-col { grid-template-columns: 1fr; }
  }

  /* Best strategy highlight */
  .best-badge {
    display: inline-block;
    background: #34A853;
    color: #fff;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-left: 8px;
  }

  .bias-positive { color: #ef4444; }
  .bias-negative { color: #3b82f6; }
  .bias-low { color: #34A853; }

  /* Info tooltip */
  .info-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: #334155;
    color: #94a3b8;
    font-size: 11px;
    font-weight: 700;
    font-style: italic;
    font-family: Georgia, serif;
    cursor: help;
    margin-left: 6px;
    vertical-align: middle;
    position: relative;
    flex-shrink: 0;
  }
  .info-icon:hover {
    background: #4285F4;
    color: #fff;
  }
  .info-icon .tooltip-text {
    visibility: hidden;
    opacity: 0;
    width: 280px;
    max-width: 280px;
    background: #0f172a;
    color: #e2e8f0;
    text-align: left;
    border-radius: 8px;
    padding: 10px 14px;
    position: absolute;
    z-index: 100;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    font-size: 0.8rem;
    font-weight: 400;
    font-style: normal;
    font-family: 'Inter', -apple-system, sans-serif;
    line-height: 1.5;
    white-space: normal;
    word-wrap: break-word;
    overflow-wrap: break-word;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    border: 1px solid #1e293b;
    transition: opacity 0.15s ease;
    pointer-events: none;
  }
  .info-icon .tooltip-text::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border-width: 6px;
    border-style: solid;
    border-color: #0f172a transparent transparent transparent;
  }
  .info-icon:hover .tooltip-text {
    visibility: visible;
    opacity: 1;
  }

  .footer {
    text-align: center;
    color: #555;
    font-size: 0.8rem;
    margin-top: 40px;
    padding: 20px 0;
    border-top: 1px solid #222;
  }

  /* Quick summary table */
  .quick-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
  }
  .quick-table th {
    text-align: left;
    padding: 8px 12px;
    color: #aaa;
    font-weight: 600;
    font-size: 0.8rem;
    border-bottom: 1px solid #333;
  }
  .quick-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #1a2744;
    font-size: 0.9rem;
  }
  .quick-table td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  /* Deep-dive button */
  .deep-dive-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 4px;
    background: #334155;
    color: #94a3b8;
    border: none;
    cursor: pointer;
    margin-left: 6px;
    vertical-align: middle;
    transition: all 0.15s ease;
    padding: 0;
  }
  .deep-dive-btn:hover { background: #4285F4; color: #fff; }
  .deep-dive-btn.active { background: #4285F4; color: #fff; }
  .deep-dive-btn svg { transition: transform 0.2s ease; }

  /* Deep-dive expansion row */
  .deep-dive-row td {
    padding: 0 !important;
    border-bottom: 2px solid #4285F4;
  }
  .deep-dive-panel {
    background: #0f172a;
    border-radius: 0 0 8px 8px;
    padding: 20px 24px;
    margin: 0 8px 8px 8px;
    animation: slideDown 0.2s ease-out;
  }
  @keyframes slideDown {
    from { opacity: 0; max-height: 0; }
    to { opacity: 1; max-height: 600px; }
  }
  .ddp-tabs {
    display: flex;
    gap: 4px;
    margin-bottom: 16px;
    border-bottom: 1px solid #1e293b;
    padding-bottom: 8px;
  }
  .ddp-tab {
    background: none;
    border: none;
    color: #94a3b8;
    font-size: 0.85rem;
    font-weight: 500;
    padding: 6px 14px;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.15s ease;
    font-family: inherit;
  }
  .ddp-tab:hover { background: #1e293b; color: #e2e8f0; }
  .ddp-tab.active { background: #4285F4; color: #fff; }
  .ddp-content {
    font-size: 0.88rem;
    line-height: 1.7;
    color: #cbd5e1;
  }
  .ddp-content p { margin-bottom: 8px; }
  .ddp-metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 12px;
  }
  .ddp-metric {
    background: #1e293b;
    border-radius: 8px;
    padding: 12px;
    text-align: center;
  }
  .ddp-metric-value {
    font-size: 1.4rem;
    font-weight: 700;
    color: #4285F4;
    font-variant-numeric: tabular-nums;
  }
  .ddp-metric-label {
    font-size: 0.75rem;
    color: #64748b;
    margin-top: 4px;
  }
  .ddp-results-note {
    font-size: 0.8rem;
    color: #64748b;
    margin-top: 8px;
  }
  .ddp-tags { margin-top: 12px; }
  .ddp-tag {
    display: inline-block;
    background: #1e293b;
    color: #94a3b8;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    margin-right: 6px;
    margin-bottom: 4px;
  }
</style>
</head>
<body>
<div class="container">

  <!-- ============================================================ -->
  <!-- Section 1: Executive Summary                                  -->
  <!-- ============================================================ -->
  <div class="card">
    <h1>Marking.ai Evaluation Report</h1>
    <p class="subtitle" id="reportSubtitle"></p>

    <div class="summary-row" id="summaryCards"></div>

    <h3>Best Strategy per Subject</h3>
    <table class="quick-table" id="bestTable">
      <thead>
        <tr>
          <th>Subject</th>
          <th>Strategy</th>
          <th>Model</th>
          <th style="text-align:right">ExRnd%</th>
          <th style="text-align:right">MAE</th>
          <th style="text-align:right">Bias</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="section-divider"></div>

  <!-- ============================================================ -->
  <!-- Section 2: Maths Leaderboard                                  -->
  <!-- ============================================================ -->
  <div class="card" id="mathsSection">
    <h2>Strategy Leaderboard &mdash; Maths</h2>
    <div class="chart-container" id="mathsChartWrap">
      <canvas id="mathsChart"></canvas>
    </div>
    <table class="data-table" id="mathsTable">
      <thead>
        <tr>
          <th>Strategy</th>
          <th>Model</th>
          <th class="num">n</th>
          <th class="num">ExRnd%</th>
          <th class="num">W/in1%</th>
          <th class="num">MAE</th>
          <th class="num">Bias</th>
          <th class="num">Over%</th>
          <th class="num">Under%</th>
          <th class="num">Cost</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="section-divider"></div>

  <!-- ============================================================ -->
  <!-- Section 3: English Leaderboard                                -->
  <!-- ============================================================ -->
  <div class="card" id="englishSection">
    <h2>Strategy Leaderboard &mdash; English</h2>
    <div class="chart-container" id="englishChartWrap">
      <canvas id="englishChart"></canvas>
    </div>
    <table class="data-table" id="englishTable">
      <thead>
        <tr>
          <th>Strategy</th>
          <th>Model</th>
          <th class="num">n</th>
          <th class="num">ExRnd%</th>
          <th class="num">W/in1%</th>
          <th class="num">MAE</th>
          <th class="num">Bias</th>
          <th class="num">Over%</th>
          <th class="num">Under%</th>
          <th class="num">Cost</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="section-divider"></div>

  <!-- ============================================================ -->
  <!-- Section 4: Cross-Model Comparison                             -->
  <!-- ============================================================ -->
  <div class="card" id="crossModelSection" style="display:none;">
    <h2>Cross-Model Comparison (Phase 5)</h2>
    <p style="color:#999;margin-bottom:16px;">Same prompt strategy evaluated across different LLM providers.</p>
    <div id="crossModelCharts"></div>
    <div id="crossModelTables"></div>
  </div>

  <div class="section-divider" id="crossModelDivider" style="display:none;"></div>

  <!-- ============================================================ -->
  <!-- Section 5: Score Distribution Analysis                        -->
  <!-- ============================================================ -->
  <div class="card" id="scoreDistSection" style="display:none;">
    <h2>Score Distribution Analysis</h2>
    <p style="color:#999;margin-bottom:16px;">Human vs AI mark distributions for top English strategies. Shows score compression visually.</p>
    <div id="scoreDistCharts"></div>
  </div>

  <div class="section-divider" id="scoreDistDivider" style="display:none;"></div>

  <!-- ============================================================ -->
  <!-- Section 6: Bias Analysis                                      -->
  <!-- ============================================================ -->
  <div class="card" id="biasSection">
    <h2>Bias Analysis</h2>
    <p style="color:#999;margin-bottom:16px;">Mean signed error per strategy. Positive = over-marking, Negative = under-marking.</p>
    <div class="two-col">
      <div>
        <h3>Maths</h3>
        <div class="chart-container short"><canvas id="biasMathsChart"></canvas></div>
      </div>
      <div>
        <h3>English</h3>
        <div class="chart-container short"><canvas id="biasEnglishChart"></canvas></div>
      </div>
    </div>
  </div>

  <div class="section-divider"></div>

  <!-- ============================================================ -->
  <!-- Section 7: Score Compression Over Time                        -->
  <!-- ============================================================ -->
  <div class="card" id="compressionSection" style="display:none;">
    <h2>Score Compression Over Time (English)</h2>
    <p style="color:#999;margin-bottom:16px;">Percentage of AI marks that equal 3, by strategy (sorted by phase). Lower is better &mdash; shows progressively breaking score compression.</p>
    <div class="chart-container"><canvas id="compressionChart"></canvas></div>
  </div>

  <div class="section-divider" id="compressionDivider" style="display:none;"></div>

  <!-- ============================================================ -->
  <!-- Section 8: Phase Progress                                     -->
  <!-- ============================================================ -->
  <div class="card" id="phaseSection">
    <h2>Phase Progress</h2>
    <p style="color:#999;margin-bottom:16px;">Best ExRnd% achieved per phase for each subject.</p>
    <div class="chart-container short"><canvas id="phaseChart"></canvas></div>
  </div>

  <div class="footer">
    Generated by Marking.ai Eval Agent &middot; <span id="footerTimestamp"></span>
  </div>
</div>

<!-- Embedded report data -->
<script>
const REPORT_DATA = __REPORT_DATA_JSON__;
</script>

<script>
// ======================================================================
// Utility: info icon with tooltip
// ======================================================================
function infoIcon(strategyName) {
  const desc = (REPORT_DATA.strategy_descriptions || {})[strategyName];
  if (!desc) return '';
  const escaped = desc.replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;');
  return `<span class="info-icon">i<span class="tooltip-text">${escaped}</span></span>`;
}

// ======================================================================
// Deep-dive methodology panel
// ======================================================================
function deepDiveButton(strategyName) {
  const dd = (REPORT_DATA.strategy_deep_dive || {})[strategyName];
  if (!dd) return '';
  return `<button class="deep-dive-btn" onclick="toggleDeepDive('${strategyName}', this)" title="View methodology">` +
    `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 5l7 7-7 7"/></svg></button>`;
}

function switchDDTab(btn, tabName) {
  const panel = btn.closest('.deep-dive-panel');
  panel.querySelectorAll('.ddp-tab').forEach(t => t.classList.remove('active'));
  panel.querySelectorAll('.ddp-content').forEach(c => c.style.display = 'none');
  btn.classList.add('active');
  panel.querySelector('.ddp-content[data-tab="' + tabName + '"]').style.display = 'block';
}

function findMetrics(strategyName) {
  const all = [...(REPORT_DATA.maths_metrics || []), ...(REPORT_DATA.english_metrics || [])];
  return all.find(m => m.strategy_name === strategyName);
}

function renderResultsTab(strategyName, metrics) {
  if (!metrics) return '<p style="color:#64748b;">No results data available.</p>';
  const biasClass = Math.abs(metrics.mean_signed_error) < 0.3 ? 'bias-low' :
                    metrics.mean_signed_error > 0 ? 'bias-positive' : 'bias-negative';
  const biasDir = metrics.mean_signed_error > 0 ? 'over-marks' :
                  metrics.mean_signed_error < 0 ? 'under-marks' : 'neutral';
  return `<div class="ddp-metrics-grid">
      <div class="ddp-metric"><div class="ddp-metric-value">${metrics.exact_match_rounded_pct}%</div><div class="ddp-metric-label">Exact Match (Rounded)</div></div>
      <div class="ddp-metric"><div class="ddp-metric-value">${metrics.within_1_pct}%</div><div class="ddp-metric-label">Within 1 Mark</div></div>
      <div class="ddp-metric"><div class="ddp-metric-value">${metrics.mae}</div><div class="ddp-metric-label">Mean Abs Error</div></div>
      <div class="ddp-metric"><div class="ddp-metric-value ${biasClass}">${metrics.mean_signed_error > 0 ? '+' : ''}${metrics.mean_signed_error}</div><div class="ddp-metric-label">Bias (${biasDir})</div></div>
      <div class="ddp-metric"><div class="ddp-metric-value">${metrics.over_mark_pct}%</div><div class="ddp-metric-label">Over-mark Rate</div></div>
      <div class="ddp-metric"><div class="ddp-metric-value">${metrics.under_mark_pct}%</div><div class="ddp-metric-label">Under-mark Rate</div></div>
    </div>
    <p class="ddp-results-note">Based on ${metrics.n} evaluations using ${metrics.model_label}.</p>`;
}

function toggleDeepDive(strategyName, buttonEl) {
  const panelId = 'deepdive_' + strategyName;
  const existing = document.getElementById(panelId);
  if (existing) {
    existing.remove();
    buttonEl.classList.remove('active');
    buttonEl.querySelector('svg').style.transform = '';
    return;
  }
  // Close other panels in same table
  const table = buttonEl.closest('table');
  table.querySelectorAll('.deep-dive-row').forEach(r => r.remove());
  table.querySelectorAll('.deep-dive-btn.active').forEach(b => {
    if (b !== buttonEl) { b.classList.remove('active'); b.querySelector('svg').style.transform = ''; }
  });

  const row = buttonEl.closest('tr');
  const colspan = row.children.length;
  const dd = REPORT_DATA.strategy_deep_dive[strategyName];
  const metrics = findMetrics(strategyName);
  const tags = dd.tags ? '<div class="ddp-tags">' + dd.tags.map(t => '<span class="ddp-tag">' + t + '</span>').join('') + '</div>' : '';

  const panelRow = document.createElement('tr');
  panelRow.id = panelId;
  panelRow.className = 'deep-dive-row';
  panelRow.innerHTML = '<td colspan="' + colspan + '"><div class="deep-dive-panel">' +
    '<div class="ddp-tabs">' +
    '<button class="ddp-tab active" onclick="switchDDTab(this,\'concept\')">Concept</button>' +
    '<button class="ddp-tab" onclick="switchDDTab(this,\'methodology\')">Methodology</button>' +
    '<button class="ddp-tab" onclick="switchDDTab(this,\'results\')">Results</button>' +
    '<button class="ddp-tab" onclick="switchDDTab(this,\'recommendations\')">Recommendations</button>' +
    '</div>' +
    '<div class="ddp-content" data-tab="concept" style="display:block;"><p>' + (dd.concept || 'No description available.') + '</p></div>' +
    '<div class="ddp-content" data-tab="methodology" style="display:none;"><p>' + (dd.methodology || 'No description available.') + '</p></div>' +
    '<div class="ddp-content" data-tab="results" style="display:none;">' + renderResultsTab(strategyName, metrics) + '</div>' +
    '<div class="ddp-content" data-tab="recommendations" style="display:none;"><p>' + (dd.recommendations || 'No recommendations available.') + '</p>' + tags + '</div>' +
    '</div></td>';

  row.after(panelRow);
  buttonEl.classList.add('active');
  buttonEl.querySelector('svg').style.transform = 'rotate(90deg)';
}

// ======================================================================
// Render all sections
// ======================================================================
document.addEventListener('DOMContentLoaded', () => {
  const D = REPORT_DATA;

  // --- 1. Executive Summary ---
  document.getElementById('reportSubtitle').textContent =
    `Generated ${D.generated_at} | ${D.total_strategies} strategies | ${D.total_evals.toLocaleString()} total evaluations`;
  document.getElementById('footerTimestamp').textContent = D.generated_at;

  const summaryCards = document.getElementById('summaryCards');
  summaryCards.innerHTML = `
    <div class="stat-card">
      <div class="stat-value">${D.total_strategies}</div>
      <div class="stat-label">Strategies Tested</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">${D.total_evals.toLocaleString()}</div>
      <div class="stat-label">Total Evaluations</div>
    </div>
    <div class="stat-card best">
      <div class="stat-value">${D.best_maths ? D.best_maths.exact_match_rounded_pct + '%' : 'N/A'}</div>
      <div class="stat-label">Best Maths ExRnd%</div>
    </div>
    <div class="stat-card best">
      <div class="stat-value">${D.best_english ? D.best_english.exact_match_rounded_pct + '%' : 'N/A'}</div>
      <div class="stat-label">Best English ExRnd%</div>
    </div>
    ${D.total_cost != null ? `<div class="stat-card">
      <div class="stat-value">$${D.total_cost.toFixed(2)}</div>
      <div class="stat-label">Total API Cost</div>
    </div>` : ''}
  `;

  // Best strategy table
  const bestBody = document.querySelector('#bestTable tbody');
  const bestItems = [];
  if (D.best_maths) bestItems.push({subj: 'Maths', ...D.best_maths});
  if (D.best_english) bestItems.push({subj: 'English', ...D.best_english});
  bestItems.forEach(b => {
    const biasClass = Math.abs(b.mean_signed_error) < 0.3 ? 'bias-low' :
                      b.mean_signed_error > 0 ? 'bias-positive' : 'bias-negative';
    bestBody.innerHTML += `<tr>
      <td>${b.subj}</td>
      <td>${b.strategy_name}${infoIcon(b.strategy_name)}</td>
      <td><span class="model-badge" style="background:${b.model_color}">${b.model_label}</span></td>
      <td class="num"><strong>${b.exact_match_rounded_pct}%</strong></td>
      <td class="num">${b.mae}</td>
      <td class="num ${biasClass}">${b.mean_signed_error > 0 ? '+' : ''}${b.mean_signed_error}</td>
    </tr>`;
  });

  // --- 2. Maths Leaderboard ---
  renderLeaderboard(D.maths_metrics, 'mathsChart', 'mathsTable', 'mathsSection');

  // --- 3. English Leaderboard ---
  renderLeaderboard(D.english_metrics, 'englishChart', 'englishTable', 'englishSection');

  // --- 4. Cross-Model Comparison ---
  const crossKeys = Object.keys(D.cross_model || {});
  if (crossKeys.length > 0) {
    document.getElementById('crossModelSection').style.display = '';
    document.getElementById('crossModelDivider').style.display = '';
    renderCrossModel(D.cross_model);
  }

  // --- 5. Score Distribution ---
  if (D.score_distributions && D.score_distributions.length > 0) {
    document.getElementById('scoreDistSection').style.display = '';
    document.getElementById('scoreDistDivider').style.display = '';
    renderScoreDistributions(D.score_distributions);
  }

  // --- 6. Bias Analysis ---
  renderBiasChart(D.maths_metrics, 'biasMathsChart');
  renderBiasChart(D.english_metrics, 'biasEnglishChart');

  // --- 7. Score Compression ---
  if (D.compression_data && D.compression_data.length > 0) {
    document.getElementById('compressionSection').style.display = '';
    document.getElementById('compressionDivider').style.display = '';
    renderCompression(D.compression_data);
  }

  // --- 8. Phase Progress ---
  renderPhaseProgress(D.phase_progress);
});


// ======================================================================
// Leaderboard (horizontal bar chart + table)
// ======================================================================
function renderLeaderboard(metrics, chartId, tableId, sectionId) {
  if (!metrics || metrics.length === 0) {
    document.getElementById(sectionId).style.display = 'none';
    return;
  }

  // Chart
  const labels = metrics.map(m => m.strategy_name);
  const values = metrics.map(m => m.exact_match_rounded_pct);
  const colors = metrics.map(m => m.model_color);

  new Chart(document.getElementById(chartId), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'ExRnd%',
        data: values,
        backgroundColor: colors.map(c => c + 'CC'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `ExRnd%: ${ctx.raw}%`
          }
        }
      },
      scales: {
        x: {
          beginAtZero: true,
          max: 100,
          grid: { color: '#1a2744' },
          ticks: { color: '#999', callback: v => v + '%' },
        },
        y: {
          grid: { display: false },
          ticks: { color: '#ccc', font: { size: 11 } },
        }
      }
    }
  });

  // Table
  const tbody = document.querySelector(`#${tableId} tbody`);
  metrics.forEach((m, i) => {
    const biasClass = Math.abs(m.mean_signed_error) < 0.3 ? 'bias-low' :
                      m.mean_signed_error > 0 ? 'bias-positive' : 'bias-negative';
    const highlight = i === 0 ? ' class="highlight"' : '';
    tbody.innerHTML += `<tr${highlight}>
      <td>${m.strategy_name}${infoIcon(m.strategy_name)}${deepDiveButton(m.strategy_name)}${i === 0 ? '<span class="best-badge">BEST</span>' : ''}</td>
      <td><span class="model-badge" style="background:${m.model_color}">${m.model_label}</span></td>
      <td class="num">${m.n}</td>
      <td class="num"><strong>${m.exact_match_rounded_pct}%</strong></td>
      <td class="num">${m.within_1_pct}%</td>
      <td class="num">${m.mae}</td>
      <td class="num ${biasClass}">${m.mean_signed_error > 0 ? '+' : ''}${m.mean_signed_error}</td>
      <td class="num">${m.over_mark_pct}%</td>
      <td class="num">${m.under_mark_pct}%</td>
      <td class="num">${m.cost_usd != null ? '$' + m.cost_usd.toFixed(2) : '\u2014'}</td>
    </tr>`;
  });
}


// ======================================================================
// Cross-Model Comparison (Phase 5)
// ======================================================================
function renderCrossModel(crossData) {
  const container = document.getElementById('crossModelCharts');
  const tableContainer = document.getElementById('crossModelTables');
  const modelOrder = ['gemini25pro', 'gemini31', 'claude', 'gpt'];
  const D = REPORT_DATA;

  Object.entries(crossData).forEach(([baseName, models]) => {
    // Create chart container
    const chartDiv = document.createElement('div');
    chartDiv.innerHTML = `<h3 style="margin-top:20px;">${baseName}</h3>
      <div class="chart-container short"><canvas id="cross_${baseName}"></canvas></div>`;
    container.appendChild(chartDiv);

    const presentModels = modelOrder.filter(mk => models[mk]);
    const modelLabels = presentModels.map(mk => D.model_labels[mk] || mk);

    // Also include default Gemini 2.5 Pro from non-Phase-5 if it exists
    // Check if the base strategy exists in maths or english metrics
    const allMetrics = [...(D.maths_metrics || []), ...(D.english_metrics || [])];
    const baseMetric = allMetrics.find(m => m.strategy_name === baseName);
    if (baseMetric && !models['gemini25pro']) {
      presentModels.unshift('gemini25pro');
      modelLabels.unshift(D.model_labels['gemini25pro']);
      models['gemini25pro'] = baseMetric;
    }

    const exrndData = presentModels.map(mk => models[mk] ? models[mk].exact_match_rounded_pct : 0);
    const maeData = presentModels.map(mk => models[mk] ? models[mk].mae : 0);
    const biasData = presentModels.map(mk => models[mk] ? models[mk].mean_signed_error : 0);

    new Chart(document.getElementById(`cross_${baseName}`), {
      type: 'bar',
      data: {
        labels: modelLabels,
        datasets: [
          {
            label: 'ExRnd%',
            data: exrndData,
            backgroundColor: presentModels.map(mk => (D.model_colors[mk] || '#4285F4') + 'CC'),
            borderColor: presentModels.map(mk => D.model_colors[mk] || '#4285F4'),
            borderWidth: 1,
            borderRadius: 4,
            yAxisID: 'y',
          },
          {
            label: 'MAE',
            data: maeData,
            backgroundColor: 'rgba(255,255,255,0.15)',
            borderColor: '#aaa',
            borderWidth: 1,
            borderRadius: 4,
            yAxisID: 'y1',
          },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#ccc' } },
        },
        scales: {
          x: { ticks: { color: '#ccc' }, grid: { display: false } },
          y: {
            beginAtZero: true,
            max: 100,
            position: 'left',
            title: { display: true, text: 'ExRnd%', color: '#999' },
            ticks: { color: '#999', callback: v => v + '%' },
            grid: { color: '#1a2744' },
          },
          y1: {
            beginAtZero: true,
            position: 'right',
            title: { display: true, text: 'MAE', color: '#999' },
            ticks: { color: '#999' },
            grid: { display: false },
          }
        }
      }
    });

    // Summary table
    const table = document.createElement('table');
    table.className = 'data-table';
    table.innerHTML = `<thead><tr>
      <th>Model</th><th class="num">n</th><th class="num">ExRnd%</th>
      <th class="num">W/in1%</th><th class="num">MAE</th><th class="num">Bias</th>
    </tr></thead><tbody></tbody>`;
    const tbody = table.querySelector('tbody');
    presentModels.forEach(mk => {
      const m = models[mk];
      if (!m) return;
      const biasClass = Math.abs(m.mean_signed_error) < 0.3 ? 'bias-low' :
                        m.mean_signed_error > 0 ? 'bias-positive' : 'bias-negative';
      tbody.innerHTML += `<tr>
        <td><span class="model-badge" style="background:${D.model_colors[mk] || '#4285F4'}">${D.model_labels[mk] || mk}</span></td>
        <td class="num">${m.n}</td>
        <td class="num"><strong>${m.exact_match_rounded_pct}%</strong></td>
        <td class="num">${m.within_1_pct}%</td>
        <td class="num">${m.mae}</td>
        <td class="num ${biasClass}">${m.mean_signed_error > 0 ? '+' : ''}${m.mean_signed_error}</td>
      </tr>`;
    });
    tableContainer.appendChild(table);
  });
}


// ======================================================================
// Score Distribution
// ======================================================================
function renderScoreDistributions(distributions) {
  const container = document.getElementById('scoreDistCharts');

  distributions.forEach((dist, idx) => {
    const div = document.createElement('div');
    div.innerHTML = `<h3>${dist.strategy_name}</h3>
      <div class="chart-container short"><canvas id="scoreDist_${idx}"></canvas></div>`;
    container.appendChild(div);

    // Build labels from 0 to 6
    const labels = ['0', '1', '2', '3', '4', '5', '6'];
    const humanData = labels.map(l => dist.human_dist[l] || 0);
    const aiData = labels.map(l => dist.ai_dist[l] || 0);

    new Chart(document.getElementById(`scoreDist_${idx}`), {
      type: 'bar',
      data: {
        labels: labels.map(l => 'Score ' + l),
        datasets: [
          {
            label: 'Human Marks',
            data: humanData,
            backgroundColor: 'rgba(66, 133, 244, 0.6)',
            borderColor: '#4285F4',
            borderWidth: 1,
            borderRadius: 4,
          },
          {
            label: 'AI Marks',
            data: aiData,
            backgroundColor: 'rgba(217, 119, 6, 0.6)',
            borderColor: '#D97706',
            borderWidth: 1,
            borderRadius: 4,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#ccc' } },
        },
        scales: {
          x: { ticks: { color: '#ccc' }, grid: { display: false } },
          y: {
            beginAtZero: true,
            title: { display: true, text: 'Count', color: '#999' },
            ticks: { color: '#999' },
            grid: { color: '#1a2744' },
          }
        }
      }
    });
  });
}


// ======================================================================
// Bias Analysis
// ======================================================================
function renderBiasChart(metrics, chartId) {
  if (!metrics || metrics.length === 0) return;

  // Sort by absolute bias
  const sorted = [...metrics].sort((a, b) => Math.abs(b.mean_signed_error) - Math.abs(a.mean_signed_error));
  const labels = sorted.map(m => m.strategy_name);
  const values = sorted.map(m => m.mean_signed_error);
  const colors = values.map(v => {
    const abs = Math.abs(v);
    if (abs < 0.2) return '#34A853';
    if (abs < 0.5) return '#D97706';
    return '#ef4444';
  });

  new Chart(document.getElementById(chartId), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Mean Signed Error',
        data: values,
        backgroundColor: colors.map(c => c + 'CC'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `Bias: ${ctx.raw > 0 ? '+' : ''}${ctx.raw}`
          }
        }
      },
      scales: {
        x: {
          grid: { color: '#1a2744' },
          ticks: { color: '#999' },
          title: { display: true, text: 'Mean Signed Error (+ = over-marking)', color: '#888', font: { size: 11 } },
        },
        y: {
          grid: { display: false },
          ticks: { color: '#ccc', font: { size: 11 } },
        }
      }
    }
  });
}


// ======================================================================
// Score Compression (AI=3 percentage)
// ======================================================================
function renderCompression(compressionData) {
  const labels = compressionData.map(d => d.strategy_name);
  const values = compressionData.map(d => d.ai_3_pct);
  const phases = compressionData.map(d => d.phase);

  // Color by phase
  const phaseColors = { 1: '#ef4444', 2: '#D97706', 3: '#4285F4', 4: '#34A853', 5: '#10B981' };
  const colors = phases.map(p => phaseColors[p] || '#666');

  new Chart(document.getElementById('compressionChart'), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'AI=3 %',
        data: values,
        backgroundColor: colors.map(c => c + 'CC'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const i = ctx.dataIndex;
              return `AI=3: ${ctx.raw}% (Phase ${phases[i]})`;
            }
          }
        }
      },
      scales: {
        x: {
          beginAtZero: true,
          max: 100,
          grid: { color: '#1a2744' },
          ticks: { color: '#999', callback: v => v + '%' },
          title: { display: true, text: '% of AI marks that equal 3 (lower = less compression)', color: '#888', font: { size: 11 } },
        },
        y: {
          grid: { display: false },
          ticks: { color: '#ccc', font: { size: 11 } },
        }
      }
    }
  });
}


// ======================================================================
// Phase Progress
// ======================================================================
function renderPhaseProgress(phaseProgress) {
  const allPhases = [1, 2, 3, 4, 5];
  const labels = allPhases.map(p => `Phase ${p}`);

  const datasets = [];
  const subjects = { maths: '#4285F4', english: '#D97706' };

  Object.entries(subjects).forEach(([subj, color]) => {
    const data = phaseProgress[subj] || {};
    const values = allPhases.map(p => data[String(p)] || null);

    // Only add dataset if there is at least one non-null value
    if (values.some(v => v !== null)) {
      datasets.push({
        label: subj.charAt(0).toUpperCase() + subj.slice(1),
        data: values,
        borderColor: color,
        backgroundColor: color + '33',
        borderWidth: 3,
        pointRadius: 6,
        pointBackgroundColor: color,
        pointBorderColor: '#fff',
        pointBorderWidth: 2,
        tension: 0.3,
        spanGaps: true,
        fill: true,
      });
    }
  });

  if (datasets.length === 0) {
    document.getElementById('phaseSection').style.display = 'none';
    return;
  }

  new Chart(document.getElementById('phaseChart'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#ccc', font: { size: 13 } } },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.raw}%`
          }
        }
      },
      scales: {
        x: {
          grid: { color: '#1a2744' },
          ticks: { color: '#ccc', font: { size: 12 } },
        },
        y: {
          beginAtZero: true,
          max: 100,
          grid: { color: '#1a2744' },
          ticks: { color: '#999', callback: v => v + '%' },
          title: { display: true, text: 'Best ExRnd%', color: '#999' },
        }
      }
    }
  });
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_html_report(
    current_results: list | None = None,
    historical_csvs: list | None = None,
    output_path: str | None = None,
) -> str:
    """Generate a comprehensive HTML report. Returns the output file path.

    Parameters
    ----------
    current_results : list[EvalResult] | None
        EvalResult objects from the current run. These are merged with any
        historical data (and take precedence via deduplication).
    historical_csvs : list[Path] | None
        Path objects pointing to ``eval_results_*.csv`` files.
    output_path : str | None
        Where to write the HTML file. If *None*, auto-generates a timestamped
        path inside ``config.RESULTS_DIR``.

    Returns
    -------
    str
        The absolute path of the generated HTML file.
    """
    # Collect all rows
    all_rows: list[dict] = []

    # Load historical CSVs with deduplication
    if historical_csvs:
        all_rows.extend(_deduplicate_csvs(list(historical_csvs)))

    # Merge current results (treated as the newest data)
    if current_results:
        current_dicts = _eval_results_to_dicts(current_results)
        # Current results override historical for the same strategies
        current_strategies = {r["strategy_name"] for r in current_dicts}
        all_rows = [r for r in all_rows if r["strategy_name"] not in current_strategies]
        all_rows.extend(current_dicts)

    if not all_rows:
        raise ValueError("No evaluation data to report. Provide current_results or historical_csvs.")

    # Build the data payload
    report_data = _build_report_data(all_rows)

    # Serialise data to JSON for embedding
    data_json = json.dumps(report_data, indent=None, ensure_ascii=False)

    # Render HTML
    html = HTML_TEMPLATE.replace("__REPORT_DATA_JSON__", data_json)

    # Determine output path
    if output_path is None:
        os.makedirs(config.RESULTS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(config.RESULTS_DIR / f"eval_report_{timestamp}.html")

    # Write
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path

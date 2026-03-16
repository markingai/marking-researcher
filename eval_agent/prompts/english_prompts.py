"""English essay marking prompt variants.

Each function returns (system_instruction, user_parts, response_schema).
"""

from __future__ import annotations
from ..data_loader import MarkingRow


# --- Shared schemas ---

SIMPLE_SCHEMA = {
    "type": "object",
    "required": ["mark", "justification"],
    "properties": {
        "mark": {"type": "integer"},
        "justification": {"type": "string"},
    },
}

CRITERION_SCHEMA = {
    "type": "object",
    "required": [
        "content_and_analysis",
        "command_of_evidence",
        "coherence_organization_style",
        "control_of_conventions",
        "final_mark",
        "justification",
    ],
    "properties": {
        "content_and_analysis": {"type": "integer"},
        "command_of_evidence": {"type": "integer"},
        "coherence_organization_style": {"type": "integer"},
        "control_of_conventions": {"type": "integer"},
        "final_mark": {"type": "integer"},
        "justification": {"type": "string"},
    },
}

# Half-mark schema: allows 0.5 increments
HALF_MARK_SCHEMA = {
    "type": "object",
    "required": ["mark", "justification"],
    "properties": {
        "mark": {"type": "number"},
        "justification": {"type": "string"},
    },
}

HALF_MARK_CRITERION_SCHEMA = {
    "type": "object",
    "required": [
        "content_and_analysis",
        "command_of_evidence",
        "coherence_organization_style",
        "control_of_conventions",
        "final_mark",
        "justification",
    ],
    "properties": {
        "content_and_analysis": {"type": "number"},
        "command_of_evidence": {"type": "number"},
        "coherence_organization_style": {"type": "number"},
        "control_of_conventions": {"type": "number"},
        "final_mark": {"type": "number"},
        "justification": {"type": "string"},
    },
}


def _truncate_source(source_text: str, max_chars: int = 18000) -> str:
    """Truncate source text to fit token limits while keeping structure."""
    if len(source_text) <= max_chars:
        return source_text
    return source_text[:max_chars] + "\n\n[Source texts truncated for length]"


# --- Strategy 1: English Baseline ---

def english_baseline(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert English Language Arts examiner marking NY Regents "
        "argument essays. Mark holistically against the provided rubric. "
        "Award marks conservatively. The essay is scored 0-6 as an integer."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts the student was given:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            f"Mark this essay out of {row.total_marks} using the rubric above. "
            "Consider how well the student introduces a claim, analyzes sources, "
            "distinguishes from counterclaims, uses evidence, maintains coherence, "
            "and controls conventions. "
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
            "and 'justification' (brief explanation referencing rubric criteria)."
        ),
    ])
    return system, user_parts, SIMPLE_SCHEMA


# --- Strategy 2: English Criterion Decomposed ---

def english_criterion_decomposed(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. Score this essay on EACH of the 4 "
        "rubric criteria independently, then compute the final mark. "
        "Each criterion is scored 1-6. The final mark is the average of the "
        "4 criteria scores, rounded to the nearest integer. "
        "Be precise and consistent across criteria."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            "Score this essay on each criterion independently:\n"
            "1. Content and Analysis (1-6): claim quality, source/topic analysis, counterclaim evaluation\n"
            "2. Command of Evidence (1-6): integration and citation of source evidence\n"
            "3. Coherence, Organization, and Style (1-6): structure, transitions, academic tone\n"
            "4. Control of Conventions (1-6): grammar, spelling, punctuation\n\n"
            "Return JSON with 'content_and_analysis' (int 1-6), "
            "'command_of_evidence' (int 1-6), 'coherence_organization_style' (int 1-6), "
            "'control_of_conventions' (int 1-6), 'final_mark' (int = rounded average of "
            f"the 4 scores, max {row.total_marks}), and 'justification'."
        ),
    ])
    return system, user_parts, CRITERION_SCHEMA


# --- Strategy 3: English Anchor Examples ---

def english_anchor_examples(
    row: MarkingRow,
    examples: list[MarkingRow] | None = None,
) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. You will first see examples of essays "
        "at different score levels, then mark a new essay. Use the examples to "
        "calibrate your scoring. Most essays score between 3 and 4.5."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )

    if examples:
        examples_text = "Calibration examples at different score levels:\n\n"
        for i, ex in enumerate(examples, 1):
            # Truncate long essays for examples
            answer_preview = ex.student_answer[:800]
            if len(ex.student_answer) > 800:
                answer_preview += "... [truncated]"
            examples_text += (
                f"--- Example {i} (Score: {ex.human_mark}/{ex.total_marks}) ---\n"
                f"{answer_preview}\n\n"
            )
        user_parts.append(examples_text)

    user_parts.extend([
        f"Now mark this essay:\n{row.student_answer}",
        (
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
            "and 'justification'."
        ),
    ])
    return system, user_parts, SIMPLE_SCHEMA


# --- Strategy 4: English Strict Range ---

def english_strict_range(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner marking NY Regents argument essays. "
        "IMPORTANT CALIBRATION NOTES:\n"
        "- The majority of essays in this assessment score between 3 and 4.5.\n"
        "- A score of 5 or 6 should be reserved for genuinely exceptional work.\n"
        "- A score of 2 or below indicates significant deficiencies.\n"
        "- Be especially careful distinguishing a 3 from a 4: a 3 shows "
        "surface-level analysis with limited evidence, while a 4 shows "
        "specific analysis with appropriate evidence.\n"
        "- When unsure between two adjacent scores, choose the lower one."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            f"Mark this essay out of {row.total_marks}. "
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
            "and 'justification' referencing specific rubric criteria."
        ),
    ])
    return system, user_parts, SIMPLE_SCHEMA


# --- Strategy 5: English Half-Mark Criterion Decomposed ---

def english_halfmark_criterion(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. Score this essay on EACH of the 4 "
        "rubric criteria independently, then compute the final mark. "
        "Each criterion is scored 1-6, in 0.5 increments (e.g. 2.5, 3.0, 3.5). "
        "The final mark is the average of the 4 criteria scores, rounded to the "
        "nearest 0.5. "
        "Be precise and use the full range of scores. A typical essay scores 3-4.5 "
        "but do not compress scores toward the middle. If an essay is clearly a 4 "
        "or above on a criterion, score it accordingly."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            "Score this essay on each criterion independently. Use 0.5 increments:\n"
            "1. Content and Analysis (1-6): claim quality, source/topic analysis, counterclaim evaluation\n"
            "2. Command of Evidence (1-6): integration and citation of source evidence\n"
            "3. Coherence, Organization, and Style (1-6): structure, transitions, academic tone\n"
            "4. Control of Conventions (1-6): grammar, spelling, punctuation\n\n"
            "Return JSON with 'content_and_analysis' (number, 0.5 increments), "
            "'command_of_evidence' (number), 'coherence_organization_style' (number), "
            "'control_of_conventions' (number), 'final_mark' (number = rounded average of "
            f"the 4 scores to nearest 0.5, max {row.total_marks}), and 'justification'."
        ),
    ])
    return system, user_parts, HALF_MARK_CRITERION_SCHEMA


# --- Strategy 6: English Half-Mark with Exemplar Anchors ---

def english_halfmark_exemplar(
    row: MarkingRow,
    examples: list[MarkingRow] | None = None,
) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. You will first see examples of essays "
        "at different score levels to calibrate your marking. Then mark a new essay.\n"
        "IMPORTANT: Use the full scoring range. Do NOT compress all scores to 3. "
        "If an essay is clearly better than the examples at score 3, give it a higher score. "
        "You may use half-marks (e.g. 3.5, 4.5) for essays between two levels."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )

    if examples:
        examples_text = "Calibration examples at different score levels:\n\n"
        for i, ex in enumerate(examples, 1):
            answer_preview = ex.student_answer[:800]
            if len(ex.student_answer) > 800:
                answer_preview += "... [truncated]"
            examples_text += (
                f"--- Example {i} (Score: {ex.human_mark}/{ex.total_marks}) ---\n"
                f"{answer_preview}\n\n"
            )
        user_parts.append(examples_text)

    user_parts.extend([
        f"Now mark this essay:\n{row.student_answer}",
        (
            "Compare this essay to the examples above. Where does it sit on the quality scale? "
            "You may use half-marks (e.g. 3.5, 4.5). "
            f"Return JSON with 'mark' (number 0 to {row.total_marks}, 0.5 increments) "
            "and 'justification' explaining which example level it most resembles."
        ),
    ])
    return system, user_parts, HALF_MARK_SCHEMA


# ============================================================
# PHASE 3 STRATEGIES
# ============================================================

# --- Strategy 7: Forced Criterion Independence ---

def english_forced_independence(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. You MUST score this essay on each of "
        "the 4 rubric criteria INDEPENDENTLY.\n\n"
        "CRITICAL RULES FOR INDEPENDENT SCORING:\n"
        "- Each criterion MUST be evaluated on its own merits, NOT influenced by your "
        "impression of the other criteria.\n"
        "- It is EXPECTED and NORMAL for criteria to have DIFFERENT scores. For example, "
        "an essay can have strong content analysis (score 4-5) but weak grammar (score 2-3), "
        "or excellent organization (score 5) but limited evidence use (score 3).\n"
        "- If you find yourself giving the same score for all 4 criteria, STOP and "
        "reconsider. Identical scores across all criteria is a sign of holistic rather "
        "than independent evaluation.\n"
        "- Score each criterion by matching the student's work to the specific level "
        "descriptors in the rubric for THAT criterion only.\n\n"
        "BEFORE scoring, check the marking guide for any special scoring rules, "
        "constraints, or notes (e.g. maximum scores for specific conditions, automatic "
        "zero conditions). Apply these constraints FIRST, then score within the allowed range.\n\n"
        "The final mark is the average of the 4 criteria, rounded to the nearest integer."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            "Score EACH criterion independently. Remember: different scores per criterion "
            "are expected and encouraged.\n\n"
            "Evaluate in this order, completing each BEFORE moving to the next:\n\n"
            "1. CONTENT AND ANALYSIS (1-6): Focus ONLY on the quality of the claim, "
            "how well the student analyzes the sources and topic, and how they evaluate "
            "counterclaims. Ignore grammar, organization, and evidence citation for now.\n\n"
            "2. COMMAND OF EVIDENCE (1-6): Focus ONLY on how the student integrates "
            "and cites evidence from the source texts. Ignore claim quality, grammar, "
            "and organization.\n\n"
            "3. COHERENCE, ORGANIZATION, AND STYLE (1-6): Focus ONLY on essay structure, "
            "transitions, focus, and academic tone. Ignore content quality and grammar.\n\n"
            "4. CONTROL OF CONVENTIONS (1-6): Focus ONLY on grammar, spelling, "
            "punctuation, and sentence structure. Ignore everything else.\n\n"
            "Return JSON with 'content_and_analysis' (int 1-6), "
            "'command_of_evidence' (int 1-6), 'coherence_organization_style' (int 1-6), "
            "'control_of_conventions' (int 1-6), 'final_mark' (int = rounded average of "
            f"the 4 scores, max {row.total_marks}), and 'justification' (explain each "
            "criterion score separately)."
        ),
    ])
    return system, user_parts, CRITERION_SCHEMA


# --- Strategy 8: Level Descriptors (rubric-matching) ---

def english_level_descriptors(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. For each rubric criterion, you will "
        "match the student's essay to the SPECIFIC LEVEL DESCRIPTOR that best "
        "fits their performance. Do not assign a number directly — instead, "
        "identify which level description the essay matches, then use that level's score.\n\n"
        "BEFORE scoring, check the marking guide for any special scoring rules, "
        "constraints, or notes (e.g. maximum scores for specific conditions, automatic "
        "zero conditions). Apply these constraints FIRST.\n\n"
        "IMPORTANT: Score each criterion independently. Different criteria should "
        "typically have different scores."
    )
    user_parts = [
        f"Full Rubric (including all level descriptors):\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            "For EACH criterion below, read through ALL the level descriptors in the "
            "rubric and identify which level (1-6) BEST matches the student's work.\n\n"
            "1. CONTENT AND ANALYSIS: Read the rubric descriptors for scores 1 through 6. "
            "Which descriptor best matches this essay's claim and analysis? "
            "Note: Score 4 says 'appropriate/adequate' — it does NOT require perfection.\n\n"
            "2. COMMAND OF EVIDENCE: Read the descriptors for scores 1 through 6. "
            "Which level matches how the student uses and cites sources?\n\n"
            "3. COHERENCE, ORGANIZATION, AND STYLE: Which level descriptor matches the "
            "essay's structure, focus, and tone?\n\n"
            "4. CONTROL OF CONVENTIONS: Which level descriptor matches the essay's "
            "grammar, spelling, and punctuation?\n\n"
            "Return JSON with 'content_and_analysis' (int 1-6), "
            "'command_of_evidence' (int 1-6), 'coherence_organization_style' (int 1-6), "
            "'control_of_conventions' (int 1-6), 'final_mark' (int = rounded average of "
            f"the 4 scores, max {row.total_marks}), and 'justification' (for each criterion, "
            "quote or reference the specific level descriptor you matched)."
        ),
    ])
    return system, user_parts, CRITERION_SCHEMA


# --- Strategy 9: Full Exemplars (full essays at each score level) ---

def english_full_exemplars(
    row: MarkingRow,
    examples: list[MarkingRow] | None = None,
) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. You will first see FULL examples of essays "
        "at different score levels. Study them carefully — they define what each score "
        "level looks like for this specific assessment.\n\n"
        "CRITICAL: Use these examples to calibrate your scoring. If an essay you're "
        "marking is clearly better than the score-3 example but not as good as the "
        "score-5 example, it should be a 4. Use the examples as anchors.\n\n"
        "Score each of the 4 rubric criteria independently. Different criteria should "
        "typically have different scores.\n\n"
        "BEFORE scoring, check the marking guide for any special scoring rules or constraints."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )

    if examples:
        examples_text = (
            "CALIBRATION: Below are FULL essays at different score levels. "
            "Study them to understand what each score looks like:\n\n"
        )
        for ex in sorted(examples, key=lambda e: e.human_mark):
            examples_text += (
                f"{'='*40}\n"
                f"SCORE: {ex.human_mark}/{ex.total_marks}\n"
                f"{'='*40}\n"
                f"{ex.student_answer}\n\n"
            )
        user_parts.append(examples_text)

    user_parts.extend([
        f"NOW MARK THIS ESSAY:\n{row.student_answer}",
        (
            "Compare this essay to the calibration examples above. "
            "Score each criterion independently (1-6).\n\n"
            "Return JSON with 'content_and_analysis' (int 1-6), "
            "'command_of_evidence' (int 1-6), 'coherence_organization_style' (int 1-6), "
            "'control_of_conventions' (int 1-6), 'final_mark' (int = rounded average of "
            f"the 4 scores, max {row.total_marks}), and 'justification' (reference which "
            "calibration example the essay is most similar to and why)."
        ),
    ])
    return system, user_parts, CRITERION_SCHEMA


# ============================================================
# PHASE 4 STRATEGIES — Scorecard-inspired
# ============================================================

# --- Scorecard schema: binary/ordinal signals, NO score fields ---

SCORECARD_SCHEMA = {
    "type": "object",
    "required": [
        "claim_present", "claim_quality", "source_analysis", "counterclaim_quality",
        "evidence_present", "evidence_quality", "citation_quality",
        "task_focus", "organization", "language_sophistication",
        "conventions_control", "conventions_severity",
        "source_count", "is_off_topic", "is_blank_or_copied",
        "signal_notes",
    ],
    "properties": {
        "claim_present": {"type": "boolean"},
        "claim_quality": {"type": "integer"},
        "source_analysis": {"type": "integer"},
        "counterclaim_quality": {"type": "integer"},
        "evidence_present": {"type": "boolean"},
        "evidence_quality": {"type": "integer"},
        "citation_quality": {"type": "integer"},
        "task_focus": {"type": "integer"},
        "organization": {"type": "integer"},
        "language_sophistication": {"type": "integer"},
        "conventions_control": {"type": "integer"},
        "conventions_severity": {"type": "integer"},
        "source_count": {"type": "integer"},
        "is_off_topic": {"type": "boolean"},
        "is_blank_or_copied": {"type": "boolean"},
        "signal_notes": {"type": "string"},
    },
}

# --- Cascade schemas: band (pass 1) and exact (pass 2) ---

CASCADE_BAND_SCHEMA = {
    "type": "object",
    "required": ["band", "band_reasoning", "fewer_than_3_sources"],
    "properties": {
        "band": {"type": "string"},
        "band_reasoning": {"type": "string"},
        "fewer_than_3_sources": {"type": "boolean"},
    },
}

CASCADE_EXACT_SCHEMA = {
    "type": "object",
    "required": [
        "content_and_analysis", "command_of_evidence",
        "coherence_organization_style", "control_of_conventions",
        "final_mark", "justification",
    ],
    "properties": {
        "content_and_analysis": {"type": "integer"},
        "command_of_evidence": {"type": "integer"},
        "coherence_organization_style": {"type": "integer"},
        "control_of_conventions": {"type": "integer"},
        "final_mark": {"type": "integer"},
        "justification": {"type": "string"},
    },
}

# --- Comparative schema: per-criterion WORSE/EQUAL/BETTER judgments ---

COMPARATIVE_SCHEMA = {
    "type": "object",
    "required": [
        "vs_3_content", "vs_3_evidence", "vs_3_coherence", "vs_3_conventions",
        "vs_4_content", "vs_4_evidence", "vs_4_coherence", "vs_4_conventions",
        "fewer_than_3_sources", "is_blank_or_copied", "is_off_topic",
        "comparison_notes",
    ],
    "properties": {
        "vs_3_content": {"type": "string"},
        "vs_3_evidence": {"type": "string"},
        "vs_3_coherence": {"type": "string"},
        "vs_3_conventions": {"type": "string"},
        "vs_4_content": {"type": "string"},
        "vs_4_evidence": {"type": "string"},
        "vs_4_coherence": {"type": "string"},
        "vs_4_conventions": {"type": "string"},
        "fewer_than_3_sources": {"type": "boolean"},
        "is_blank_or_copied": {"type": "boolean"},
        "is_off_topic": {"type": "boolean"},
        "comparison_notes": {"type": "string"},
    },
}


# --- Strategy 10: Scorecard (binary signal extraction) ---

def english_scorecard(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert English Language Arts analyst. Your task is to "
        "answer factual questions about a student's argumentative essay. "
        "Do NOT assign a score or mark. Instead, answer each question about "
        "the essay's observable features as precisely as possible.\n\n"
        "For each question, base your answer ONLY on what is directly "
        "observable in the essay text. If you are uncertain between two "
        "levels, choose the LOWER one."
    )
    user_parts = []
    if row.source_text:
        user_parts.append(
            f"Source texts (ground truth for verifying student evidence):\n"
            f"{_truncate_source(row.source_text)}"
        )
    user_parts.append(f"Student essay to analyze:\n{row.student_answer}")
    user_parts.append(
        "Answer these factual questions about the essay. Do NOT assign a "
        "score — just describe what you observe.\n\n"

        "CONTENT AND ANALYSIS SIGNALS:\n"
        "1. claim_present (true/false): Does the essay introduce an "
        "identifiable claim or thesis about the topic?\n"
        "2. claim_quality (0-4): Rate the claim:\n"
        "   0 = No claim, or entirely unrelated to the topic\n"
        "   1 = A claim exists but is limited, vague, or confused\n"
        "   2 = A surface-level claim that addresses the topic but lacks specificity\n"
        "   3 = A specific, clear claim that takes a definite position\n"
        "   4 = A thorough, precise, or sophisticated claim showing insight\n"
        "3. source_analysis (0-4): Rate analysis of sources/topic:\n"
        "   0 = No analysis of sources or topic\n"
        "   1 = Confused or unclear analysis\n"
        "   2 = Emerging, surface-level analysis\n"
        "   3 = Appropriate analysis that adequately addresses the topic\n"
        "   4 = Thorough or insightful analysis\n"
        "4. counterclaim_quality (0-3): Counterclaim evaluation:\n"
        "   0 = No counterclaim addressed or confused attempt\n"
        "   1 = Insufficient or minimal counterclaim evaluation\n"
        "   2 = Appropriate evaluation of a counterclaim\n"
        "   3 = Thorough and insightful evaluation of counterclaim\n\n"

        "COMMAND OF EVIDENCE SIGNALS:\n"
        "5. evidence_present (true/false): Does the essay cite or reference "
        "specific evidence from the source texts?\n"
        "6. evidence_quality (0-4): Rate evidence use:\n"
        "   0 = No evidence from sources\n"
        "   1 = Limited, inaccurate, or irrelevant evidence\n"
        "   2 = Basic or generalized evidence\n"
        "   3 = Sufficient and adequate evidence supporting the argument\n"
        "   4 = Effective or sophisticated evidence use\n"
        "7. citation_quality (0-3): Citation and attribution:\n"
        "   0 = No citations or attribution\n"
        "   1 = Insufficient attribution (plagiarism concerns)\n"
        "   2 = Emerging citation practice (partial attribution)\n"
        "   3 = Consistent, acceptable citation practice\n\n"

        "COHERENCE, ORGANIZATION, AND STYLE SIGNALS:\n"
        "8. task_focus (0-4): Focus on the argument task:\n"
        "   0 = Little or no focus on the task\n"
        "   1 = Partial focus (lacks focus OR lacks organization)\n"
        "   2 = Emerging focus on the task\n"
        "   3 = Acceptable, sustained focus\n"
        "   4 = Clear to strategic command of focus\n"
        "9. organization (0-4): Organization of ideas:\n"
        "   0 = Little or no organization\n"
        "   1 = Organization suggested but lacking\n"
        "   2 = Emerging organization\n"
        "   3 = Logical organization\n"
        "   4 = Thoughtful to strategic organization\n"
        "10. language_sophistication (0-3): Language and sentence structure:\n"
        "   0 = Incoherent or minimal writing\n"
        "   1 = Imprecise language\n"
        "   2 = Basic but functional language\n"
        "   3 = Appropriate to sophisticated language\n\n"

        "CONTROL OF CONVENTIONS SIGNALS:\n"
        "11. conventions_control (0-4): Grammar/spelling/punctuation:\n"
        "   0 = Significant lack of control (minimal writing)\n"
        "   1 = Lack of control (errors make comprehension difficult)\n"
        "   2 = Emerging control (errors sometimes hinder comprehension)\n"
        "   3 = Partial control (errors don't hinder comprehension)\n"
        "   4 = Considerable to full control\n"
        "12. conventions_severity (0-2): Impact of errors:\n"
        "   0 = Errors severely interfere with meaning OR barely any writing\n"
        "   1 = Errors hinder comprehension\n"
        "   2 = Errors do not hinder comprehension\n\n"

        "GATE SIGNALS:\n"
        "13. source_count (integer): How many distinct source texts does "
        "the essay reference? Count only sources where specific content "
        "is used (not just mentioning 'the sources').\n"
        "14. is_off_topic (true/false): Is the essay entirely unrelated "
        "to the topic with no meaningful reference to sources or task?\n"
        "15. is_blank_or_copied (true/false): Is the essay blank, "
        "indecipherable as English, or predominantly a verbatim copy of source text?\n\n"

        "Return JSON with all 15 signal fields plus 'signal_notes' "
        "(brief note for any signal you found ambiguous)."
    )
    return system, user_parts, SCORECARD_SCHEMA


# --- Strategy 11: Cascade Pass 1 (Band Classification) ---

def english_cascade_pass1(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. Your task is to classify this "
        "essay into one of three quality bands. Do NOT assign an exact score "
        "yet — just determine the band.\n\n"
        "BAND LOW (scores 1-2): The essay has significant deficiencies. "
        "Claims are absent, limited, or confused. Evidence is minimal or "
        "irrelevant. Organization is lacking. Errors severely hinder comprehension.\n\n"
        "BAND MID (scores 3-4): The essay demonstrates emerging to adequate "
        "competence. Claims are surface-level to specific. Evidence is basic "
        "to sufficient. Organization is emerging to logical. Some control of "
        "conventions.\n\n"
        "BAND HIGH (scores 5-6): The essay demonstrates strong to exceptional "
        "competence. Claims are thorough to sophisticated. Evidence is effective "
        "to sophisticated. Organization is thoughtful to strategic. Strong control "
        "of conventions.\n\n"
        "If the essay is blank, indecipherable, or verbatim copied, classify as LOW."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            "Classify this essay into a band (LOW, MID, or HIGH).\n\n"
            "Also answer: does this essay reference fewer than 3 of the "
            "provided source texts? (This affects the maximum possible score.)\n\n"
            "Return JSON with 'band' (string: 'LOW', 'MID', or 'HIGH'), "
            "'band_reasoning' (1-2 sentences explaining your classification), "
            "and 'fewer_than_3_sources' (boolean)."
        ),
    ])
    return system, user_parts, CASCADE_BAND_SCHEMA


# --- Strategy 11: Cascade Pass 2 (Within-Band Exact Score) ---

def english_cascade_pass2(
    row: MarkingRow, band: str, band_reasoning: str,
) -> tuple[str, list[str], dict]:
    band = band.upper().strip()

    if band == "LOW":
        band_instruction = (
            "This essay has been classified as BAND LOW (scores 1-2).\n"
            "Your task: determine whether it is a 1 or a 2.\n\n"
            "THE KEY DISTINCTION:\n"
            "- Score 1: Minimal or no engagement. Claim absent or unrelated. "
            "No meaningful evidence. Little to no organization. Errors prevent "
            "comprehension. May be blank or indecipherable.\n"
            "- Score 2: Limited engagement. A claim exists but is confused or "
            "inaccurate. Evidence is limited or irrelevant. Suggested organization "
            "but lacking. Errors make comprehension difficult.\n\n"
            "Focus on: Is there ANY coherent attempt at argument, even if weak? "
            "If yes -> 2. If essentially absent -> 1."
        )
        lo, hi = 1, 2
    elif band == "HIGH":
        band_instruction = (
            "This essay has been classified as BAND HIGH (scores 5-6).\n"
            "Your task: determine whether it is a 5 or a 6.\n\n"
            "THE KEY DISTINCTION:\n"
            "- Score 5: Thorough, thoughtful work. Precise claim. Effective "
            "evidence integration. Thoughtful organization. Strong conventions.\n"
            "- Score 6: Sophisticated, exceptional work. Insightful claim. "
            "Skillful evidence use. Strategic organization. Distinguished "
            "command of conventions.\n\n"
            "Focus on: Is the work 'thorough and effective' (5) or genuinely "
            "'sophisticated and insightful' (6)? Reserve 6 for exceptional essays."
        )
        lo, hi = 5, 6
    else:  # MID — the critical case
        band_instruction = (
            "This essay has been classified as BAND MID (scores 3-4).\n"
            "Your task: determine whether it is a 3 or a 4.\n\n"
            "THE KEY DISTINCTION between 3 and 4:\n"
            "- Score 3: SURFACE-LEVEL claim, EMERGING analysis, BASIC evidence, "
            "EMERGING organization, errors HINDER comprehension\n"
            "- Score 4: SPECIFIC claim, APPROPRIATE analysis, SUFFICIENT evidence, "
            "LOGICAL organization, errors do NOT hinder comprehension\n\n"
            "Answer these 5 discriminating questions:\n"
            "1. Is the claim surface-level (vague/general) or specific (clear position)?\n"
            "2. Is source analysis emerging (mentions briefly) or appropriate (connects to argument)?\n"
            "3. Is evidence basic/generalized or sufficient/adequate?\n"
            "4. Is organization emerging or logical?\n"
            "5. Do errors hinder comprehension or not?\n\n"
            "If the MAJORITY of answers lean toward the higher description -> score 4.\n"
            "If the MAJORITY lean toward the lower description -> score 3.\n\n"
            "IMPORTANT: Score 4 means 'appropriate/adequate' — it does NOT "
            "require perfection. An essay with acceptable competence across "
            "criteria is a 4, not a 3."
        )
        lo, hi = 3, 4

    system = (
        "You are an expert ELA examiner performing a focused scoring task.\n\n"
        f"{band_instruction}\n\n"
        "BEFORE scoring, check the marking guide for any special scoring rules "
        "or constraints. Apply them first.\n\n"
        "Score each of the 4 rubric criteria independently within the allowed "
        f"range ({lo}-{hi}). The final mark is the rounded average."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            f"Band classification from first pass: {band}\n"
            f"Reasoning: {band_reasoning}\n\n"
            f"Now score each criterion within the {band} band ({lo}-{hi}).\n"
            "Return JSON with 'content_and_analysis' (int), "
            "'command_of_evidence' (int), 'coherence_organization_style' (int), "
            "'control_of_conventions' (int), 'final_mark' (int = rounded average "
            f"of the 4 scores, range {lo}-{hi}), and 'justification'."
        ),
    ])
    return system, user_parts, CASCADE_EXACT_SCHEMA


# --- Strategy 12: Comparative Anchor ---

def english_comparative_anchor(
    row: MarkingRow,
    anchor_3: MarkingRow | None = None,
    anchor_4: MarkingRow | None = None,
) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert ELA examiner. You will compare a student's "
        "essay against two calibration essays of known quality.\n\n"
        "Your task is to make RELATIVE comparisons — not assign absolute "
        "scores. For each comparison, focus on observable quality differences "
        "across all four rubric criteria.\n\n"
        "Use only: WORSE, EQUAL, or BETTER."
    )
    user_parts = []
    if row.source_text:
        user_parts.append(
            f"Source texts (provided to students):\n{_truncate_source(row.source_text)}"
        )

    # Add calibration essays
    if anchor_3:
        user_parts.append(
            f"CALIBRATION ESSAY A (Human score: {anchor_3.human_mark}/6):\n"
            f"{anchor_3.student_answer}"
        )
    if anchor_4:
        user_parts.append(
            f"CALIBRATION ESSAY B (Human score: {anchor_4.human_mark}/6):\n"
            f"{anchor_4.student_answer}"
        )

    user_parts.append(
        f"ESSAY TO EVALUATE:\n{row.student_answer}"
    )

    user_parts.append(
        "Compare the ESSAY TO EVALUATE against each calibration essay.\n\n"
        "For each of the 4 criteria, answer: Is the essay to evaluate "
        "WORSE, EQUAL, or BETTER than the calibration essay?\n\n"
        "COMPARISON vs Calibration A (score ~3):\n"
        "- vs_3_content: Content & Analysis comparison (WORSE/EQUAL/BETTER)\n"
        "- vs_3_evidence: Command of Evidence comparison\n"
        "- vs_3_coherence: Coherence/Organization/Style comparison\n"
        "- vs_3_conventions: Control of Conventions comparison\n\n"
        "COMPARISON vs Calibration B (score ~4):\n"
        "- vs_4_content: Content & Analysis comparison (WORSE/EQUAL/BETTER)\n"
        "- vs_4_evidence: Command of Evidence comparison\n"
        "- vs_4_coherence: Coherence/Organization/Style comparison\n"
        "- vs_4_conventions: Control of Conventions comparison\n\n"
        "ADDITIONAL CHECKS:\n"
        "- fewer_than_3_sources: Does the essay reference fewer than 3 source texts? (true/false)\n"
        "- is_blank_or_copied: Is the essay blank, indecipherable, or verbatim copy? (true/false)\n"
        "- is_off_topic: Is the essay entirely off-topic? (true/false)\n\n"
        "Return JSON with all comparison fields and 'comparison_notes' "
        "(brief explanation of the key differences you observed)."
    )
    return system, user_parts, COMPARATIVE_SCHEMA


# --- Debate Strategy: Moderation ---

VERIFY_SCHEMA = {
    "type": "object",
    "required": ["original_mark", "verified_mark", "changed", "reason"],
    "properties": {
        "original_mark": {"type": "integer"},
        "verified_mark": {"type": "integer"},
        "changed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
}


def english_moderation_pass2(
    row: MarkingRow,
    first_mark: int,
    first_justification: str,
) -> tuple[str, list[str], dict]:
    """Second pass: an independent moderator reviews the first marker's essay score."""
    system = (
        "You are an independent moderating examiner for NY Regents ELA essays. "
        "Another teacher has scored this student's essay and you are reviewing "
        "their marking. Your role is to ensure scoring accuracy and consistency "
        "with the rubric.\n\n"
        "MODERATION PROCESS:\n"
        "1. Read the rubric, source texts, and student essay FIRST.\n"
        "2. Form your own independent judgment of the appropriate score.\n"
        "3. THEN compare your judgment with the marker's score and reasoning.\n"
        "4. If you agree, confirm the score. If you disagree, explain which "
        "rubric criteria were misjudged and what the correct score should be.\n\n"
        "Common essay marking errors include:\n"
        "- Over-crediting surface-level analysis as 'specific'\n"
        "- Not penalizing weak evidence integration enough\n"
        "- Conflating organization with content quality\n"
        "- Being too generous with unclear or vague arguments\n"
        "- Under-crediting competent but unexciting essays"
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            f"--- MARKER'S ASSESSMENT ---\n"
            f"Score awarded: {first_mark}/{row.total_marks}\n"
            f"Justification: {first_justification}\n\n"
            "As the moderator, do you agree with this score? "
            "Return JSON with 'original_mark', 'verified_mark' (integer 0 to "
            f"{row.total_marks}), 'changed' (boolean), and 'reason' explaining "
            "your moderation decision."
        ),
    ])
    return system, user_parts, VERIFY_SCHEMA


# --- Debate Strategy: Adjudicator (English) ---

ADJUDICATION_SCHEMA = {
    "type": "object",
    "required": ["mark", "justification"],
    "properties": {
        "mark": {"type": "integer"},
        "justification": {"type": "string"},
    },
}


def english_adjudicator(
    row: MarkingRow,
    mark_a: int,
    just_a: str,
    mark_b: int,
    just_b: str,
) -> tuple[str, list[str], dict]:
    """Chief examiner adjudicates a scoring disagreement between two essay markers."""
    system = (
        "You are a chief examiner adjudicating a scoring disagreement for a "
        "NY Regents ELA argument essay. Two independent markers have given "
        "different scores and you must determine the correct one.\n\n"
        "ADJUDICATION PROCESS:\n"
        "1. Read the rubric, source texts, and student essay carefully.\n"
        "2. Consider Marker A's score and reasoning.\n"
        "3. Consider Marker B's score and reasoning.\n"
        "4. Identify which marker's reasoning better aligns with the rubric.\n"
        "5. Determine the correct score — you may agree with either marker or "
        "choose a score between them if both have partial validity.\n\n"
        "Focus on the rubric as the source of truth. Consider all four criteria: "
        "Content & Analysis, Command of Evidence, Coherence/Organization/Style, "
        "and Control of Conventions."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            f"--- MARKER A ---\n"
            f"Score: {mark_a}/{row.total_marks}\n"
            f"Reasoning: {just_a}\n\n"
            f"--- MARKER B ---\n"
            f"Score: {mark_b}/{row.total_marks}\n"
            f"Reasoning: {just_b}\n\n"
            "As chief examiner, what is the correct score? "
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
            "and 'justification' explaining which marker you agree with and why."
        ),
    ])
    return system, user_parts, ADJUDICATION_SCHEMA


# --- Debate Strategy: Rebuttal (English) ---

REBUTTAL_SCHEMA = {
    "type": "object",
    "required": ["revised_mark", "action", "argument"],
    "properties": {
        "revised_mark": {"type": "integer"},
        "action": {"type": "string"},
        "argument": {"type": "string"},
    },
}


def english_debate_rebuttal(
    row: MarkingRow,
    own_mark: int,
    own_justification: str,
    other_mark: int,
    other_justification: str,
    round_num: int,
) -> tuple[str, list[str], dict]:
    """Essay examiner responds to another marker's argument in a debate round."""
    system = (
        "You are an ELA examiner in a marking moderation debate about a "
        "NY Regents argument essay. You previously scored this essay and "
        "another examiner disagrees with your score. Consider their argument "
        "carefully.\n\n"
        "You MUST choose one of three actions:\n"
        "- CONCEDE: You accept the other marker's reasoning and adopt their score.\n"
        "- HOLD: You maintain your original score because your reasoning is stronger.\n"
        "- COMPROMISE: You partially agree and move to a score between both positions.\n\n"
        "Be intellectually honest. Consider all four rubric criteria. If the other "
        "marker identifies a genuine misapplication of the rubric, CONCEDE. "
        "But if your interpretation is defensible, HOLD."
    )
    user_parts = [
        f"Rubric:\n{row.marking_guide}",
    ]
    if row.source_text:
        user_parts.append(
            f"Source texts:\n{_truncate_source(row.source_text)}"
        )
    user_parts.extend([
        f"Student essay:\n{row.student_answer}",
        (
            f"--- YOUR PREVIOUS SCORE ---\n"
            f"Score: {own_mark}/{row.total_marks}\n"
            f"Your reasoning: {own_justification}\n\n"
            f"--- OTHER MARKER'S POSITION ---\n"
            f"Score: {other_mark}/{row.total_marks}\n"
            f"Their reasoning: {other_justification}\n\n"
            f"This is debate round {round_num}. Consider the other marker's argument "
            "carefully against the rubric.\n\n"
            "Return JSON with:\n"
            f"- 'revised_mark' (integer 0 to {row.total_marks})\n"
            "- 'action' (string: 'CONCEDE', 'HOLD', or 'COMPROMISE')\n"
            "- 'argument' (your reasoning for this action)"
        ),
    ])
    return system, user_parts, REBUTTAL_SCHEMA

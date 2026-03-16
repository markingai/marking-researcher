"""Maths marking prompt variants.

Each function returns (system_instruction, user_parts, response_schema).

user_parts is list[str | dict]. When a part is a dict it represents an
inline image: {"mime_type": "image/jpeg", "data": "<base64>"}.
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
    "required": ["criteria", "total_mark"],
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["criterion", "marks_awarded", "max_marks", "reason"],
                "properties": {
                    "criterion": {"type": "string"},
                    "marks_awarded": {"type": "integer"},
                    "max_marks": {"type": "integer"},
                    "reason": {"type": "string"},
                },
            },
        },
        "total_mark": {"type": "integer"},
    },
}

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


# --- Strategy 1: Baseline (replicates current n8n prompt) ---

def baseline(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert examiner. Mark strictly and only against the provided "
        "marking guide. Do not infer criteria beyond the guide. Award marks "
        "conservatively and never above the question total. "
        "If the student answer is blank or not attempted, give 0 marks."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"Mark this answer out of {row.total_marks}. "
            "Compare the student answer directly against the marking guide. "
            "Return a JSON object with 'mark' (integer 0 to "
            f"{row.total_marks}) and 'justification' (brief explanation)."
        ),
    ]
    return system, user_parts, SIMPLE_SCHEMA


# --- Strategy 2: Criterion Decomposed ---

def criterion_decomposed(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert examiner who marks by evaluating each criterion "
        "in the marking guide separately. For each distinct criterion or mark point "
        "in the marking guide, decide independently whether the student has earned "
        "that mark. Then sum the individual criterion scores to get the total. "
        "Never award more than the maximum marks for any criterion. "
        "Be precise and conservative - only award marks when the evidence is clear."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            "Step 1: Identify each separate mark point or criterion in the marking guide.\n"
            "Step 2: For each criterion, evaluate whether the student's answer meets it.\n"
            "Step 3: Award marks per criterion.\n"
            "Step 4: Sum to get total_mark.\n\n"
            "Return JSON with 'criteria' (array of objects with 'criterion', "
            "'marks_awarded', 'max_marks', 'reason') and 'total_mark' (integer, "
            f"must equal sum of marks_awarded, max {row.total_marks})."
        ),
    ]
    return system, user_parts, CRITERION_SCHEMA


# --- Strategy 3: Few-Shot Calibrated ---

def few_shot_calibrated(
    row: MarkingRow,
    examples: list[MarkingRow] | None = None,
) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert examiner. You will first see examples of correctly marked "
        "answers for this question type, then mark a new answer. Use the examples "
        "to calibrate your scoring. Mark strictly against the marking guide."
    )

    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
    ]

    # Add calibration examples
    if examples:
        examples_text = "Here are correctly marked examples for this question:\n\n"
        for i, ex in enumerate(examples, 1):
            examples_text += (
                f"--- Example {i} ---\n"
                f"Student answer: {ex.student_answer}\n"
                f"Correct mark: {int(ex.human_mark)}/{ex.total_marks}\n\n"
            )
        user_parts.append(examples_text)
    else:
        user_parts.append(
            "(No calibration examples available for this question type.)"
        )

    user_parts.append(
        f"Now mark this student's answer:\n{row.student_answer}\n\n"
        f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
        "and 'justification'."
    )
    return system, user_parts, SIMPLE_SCHEMA


# --- Strategy 4: Mark Then Verify (2-pass) ---

def mark_then_verify_pass1(row: MarkingRow) -> tuple[str, list[str], dict]:
    """First pass: standard marking."""
    return baseline(row)


def mark_then_verify_pass2(
    row: MarkingRow,
    first_mark: int,
    first_justification: str,
) -> tuple[str, list[str], dict]:
    """Second pass: adversarial review of the first mark."""
    system = (
        "You are a senior moderator reviewing a mark given by another examiner. "
        "Your job is to check whether the mark is accurate according to the "
        "marking guide. Look specifically for: marks awarded without sufficient "
        "evidence, criteria misapplied, or benefit of the doubt given too generously. "
        "If the mark should be lower, say so. If it's correct, confirm it."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"An examiner marked this answer {first_mark}/{row.total_marks} "
            f"with this justification:\n{first_justification}\n\n"
            "Review this mark. Is it accurate? Return JSON with 'original_mark', "
            "'verified_mark' (integer 0 to "
            f"{row.total_marks}), 'changed' (boolean), and 'reason'."
        ),
    ]
    return system, user_parts, VERIFY_SCHEMA


# --- Strategy 5: Rubric Anchor ---

def rubric_anchor(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert examiner. You will be shown a marking guide and a "
        "description of what each score level looks like. Match the student's "
        "answer to the most appropriate level. Choose the level that best fits, "
        "erring on the side of the lower level when between two."
    )
    # Build level descriptions from the total marks
    level_desc = "Score level descriptions:\n"
    tm = row.total_marks
    level_desc += f"- 0/{tm}: Answer is blank, completely wrong, or shows no understanding.\n"
    if tm == 2:
        level_desc += (
            f"- 1/{tm}: Partially correct. Shows some understanding but has errors "
            "or is incomplete. May have the right method but wrong answer, or right "
            "answer but no/wrong working.\n"
            f"- 2/{tm}: Fully correct with appropriate working shown.\n"
        )
    elif tm == 4:
        level_desc += (
            f"- 1/{tm}: Minimal correct content. Only one small part is correct.\n"
            f"- 2/{tm}: About half correct. Some parts answered well, others missing or wrong.\n"
            f"- 3/{tm}: Mostly correct with minor errors. Most criteria met.\n"
            f"- 4/{tm}: Fully correct across all parts with clear working.\n"
        )
    elif tm == 6:
        level_desc += (
            f"- 1/{tm}: Very limited. Only the most basic element is present.\n"
            f"- 2/{tm}: Limited. Some correct elements but major gaps.\n"
            f"- 3/{tm}: Partially correct. About half the criteria met.\n"
            f"- 4/{tm}: Good. Most criteria met with minor issues.\n"
            f"- 5/{tm}: Very good. Nearly all criteria met.\n"
            f"- 6/{tm}: Excellent. All criteria fully met.\n"
        )

    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        level_desc,
        f"Student answer:\n{row.student_answer}",
        (
            "Which score level best matches this answer? "
            "When between two levels, choose the lower one. "
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
            "and 'justification'."
        ),
    ]
    return system, user_parts, SIMPLE_SCHEMA


# --- Strategy 6: Conservative Bias ---

def conservative_bias(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert examiner known for strict, conservative marking. "
        "CRITICAL RULES:\n"
        "- When in doubt between two scores, ALWAYS choose the lower score.\n"
        "- Only award marks when the evidence in the student's answer "
        "UNAMBIGUOUSLY meets the criterion.\n"
        "- Partial credit should only be given when the marking guide "
        "explicitly allows it.\n"
        "- Do not give benefit of the doubt to the student.\n"
        "- Do not award marks for implied understanding - only for what "
        "is explicitly written.\n"
        "- Never exceed the total marks available."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"Mark this answer strictly out of {row.total_marks}. "
            "Remember: when in doubt, mark DOWN. "
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
            "and 'justification'."
        ),
    ]
    return system, user_parts, SIMPLE_SCHEMA


# --- Strategy 7: Hybrid Criterion Decomposed + Conservative ---

def criterion_conservative(row: MarkingRow) -> tuple[str, list[str], dict]:
    system = (
        "You are an expert examiner who marks by evaluating each criterion "
        "in the marking guide separately. For each distinct criterion or mark point "
        "in the marking guide, decide independently whether the student has earned "
        "that mark. Then sum the individual criterion scores to get the total.\n\n"
        "CRITICAL RULES:\n"
        "- When in doubt between awarding or not awarding a mark point, do NOT award it.\n"
        "- Only award marks when the student's answer UNAMBIGUOUSLY meets the criterion.\n"
        "- Do not give benefit of the doubt.\n"
        "- Do not award marks for implied understanding - only for what is explicitly written.\n"
        "- If the student answer is blank, nonsensical, or completely off-topic, award 0 for ALL criteria.\n"
        "- Never exceed the maximum marks for any criterion."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            "Step 1: Identify each separate mark point or criterion in the marking guide.\n"
            "Step 2: For each criterion, evaluate whether the student's answer CLEARLY meets it.\n"
            "Step 3: When in doubt, do NOT award the mark.\n"
            "Step 4: Sum to get total_mark.\n\n"
            "Return JSON with 'criteria' (array of objects with 'criterion', "
            "'marks_awarded', 'max_marks', 'reason') and 'total_mark' (integer, "
            f"must equal sum of marks_awarded, max {row.total_marks})."
        ),
    ]
    return system, user_parts, CRITERION_SCHEMA


# --- Debate Strategy: Moderation Pass 2 ---

def moderation_pass2(
    row: MarkingRow,
    first_mark: int,
    first_justification: str,
) -> tuple[str, list[str], dict]:
    """Second pass: an independent moderator reviews the first marker's work.

    Unlike mark_then_verify (self-review), this prompt frames the moderator
    as a completely separate expert who independently checks the mark.
    """
    system = (
        "You are an independent moderating examiner. Another teacher has "
        "marked this student's work and you are reviewing their marking. "
        "Your role is to ensure marking accuracy and consistency.\n\n"
        "MODERATION PROCESS:\n"
        "1. Read the question, marking guide, and student answer FIRST.\n"
        "2. Form your own independent judgment of what the mark should be.\n"
        "3. THEN compare your judgment with the marker's mark and justification.\n"
        "4. If you agree, confirm the mark. If you disagree, explain exactly "
        "which criterion was marked incorrectly and what the correct mark should be.\n\n"
        "Be rigorous. Common marking errors include:\n"
        "- Awarding marks for implied understanding not shown in the answer\n"
        "- Misreading partial credit criteria\n"
        "- Over-generous interpretation of vague student responses\n"
        "- Missing valid mark points the student did earn"
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"--- MARKER'S ASSESSMENT ---\n"
            f"Mark awarded: {first_mark}/{row.total_marks}\n"
            f"Justification: {first_justification}\n\n"
            "As the moderator, do you agree with this mark? "
            "Return JSON with 'original_mark', 'verified_mark' (integer 0 to "
            f"{row.total_marks}), 'changed' (boolean), and 'reason' explaining "
            "your moderation decision."
        ),
    ]
    return system, user_parts, VERIFY_SCHEMA


# --- Debate Strategy: Adjudicator ---

ADJUDICATION_SCHEMA = {
    "type": "object",
    "required": ["mark", "justification"],
    "properties": {
        "mark": {"type": "integer"},
        "justification": {"type": "string"},
    },
}


def adjudicator(
    row: MarkingRow,
    mark_a: int,
    just_a: str,
    mark_b: int,
    just_b: str,
) -> tuple[str, list[str], dict]:
    """Chief examiner adjudicates a marking disagreement between two markers."""
    system = (
        "You are a chief examiner adjudicating a marking disagreement. "
        "Two independent markers have given different marks to the same student work. "
        "Your job is to determine the correct mark.\n\n"
        "ADJUDICATION PROCESS:\n"
        "1. Read the question, marking guide, and student answer carefully.\n"
        "2. Consider Marker A's mark and reasoning.\n"
        "3. Consider Marker B's mark and reasoning.\n"
        "4. Identify which marker's reasoning better aligns with the marking guide.\n"
        "5. Determine the correct mark — you may agree with either marker or "
        "choose a mark between them if both have partial validity.\n\n"
        "Focus on the marking guide as the source of truth. A marker's reasoning "
        "is only valid if it correctly interprets the guide's criteria."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"--- MARKER A ---\n"
            f"Mark: {mark_a}/{row.total_marks}\n"
            f"Reasoning: {just_a}\n\n"
            f"--- MARKER B ---\n"
            f"Mark: {mark_b}/{row.total_marks}\n"
            f"Reasoning: {just_b}\n\n"
            "As chief examiner, what is the correct mark? "
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
            "and 'justification' explaining which marker you agree with and why."
        ),
    ]
    return system, user_parts, ADJUDICATION_SCHEMA


# --- Debate Strategy: Rebuttal ---

REBUTTAL_SCHEMA = {
    "type": "object",
    "required": ["revised_mark", "action", "argument"],
    "properties": {
        "revised_mark": {"type": "integer"},
        "action": {"type": "string"},
        "argument": {"type": "string"},
    },
}


def debate_rebuttal(
    row: MarkingRow,
    own_mark: int,
    own_justification: str,
    other_mark: int,
    other_justification: str,
    round_num: int,
) -> tuple[str, list[str], dict]:
    """Examiner responds to another marker's argument in a debate round."""
    system = (
        "You are an examiner in a marking moderation debate. You previously "
        "marked a student's work and another examiner disagrees with your mark. "
        "You must carefully consider their argument and decide whether to change "
        "your mark.\n\n"
        "You MUST choose one of three actions:\n"
        "- CONCEDE: You accept the other marker's reasoning and adopt their mark.\n"
        "- HOLD: You maintain your original mark because your reasoning is stronger.\n"
        "- COMPROMISE: You partially agree and move to a mark between both positions.\n\n"
        "Be intellectually honest. If the other marker identifies a genuine error "
        "in your reasoning or a misinterpretation of the marking guide, CONCEDE. "
        "But if your interpretation of the marking guide is defensible, HOLD."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"--- YOUR PREVIOUS MARK ---\n"
            f"Mark: {own_mark}/{row.total_marks}\n"
            f"Your reasoning: {own_justification}\n\n"
            f"--- OTHER MARKER'S POSITION ---\n"
            f"Mark: {other_mark}/{row.total_marks}\n"
            f"Their reasoning: {other_justification}\n\n"
            f"This is debate round {round_num}. Consider the other marker's argument "
            "carefully against the marking guide.\n\n"
            "Return JSON with:\n"
            f"- 'revised_mark' (integer 0 to {row.total_marks})\n"
            "- 'action' (string: 'CONCEDE', 'HOLD', or 'COMPROMISE')\n"
            "- 'argument' (your reasoning for this action)"
        ),
    ]
    return system, user_parts, REBUTTAL_SCHEMA


# =====================================================================
# PDF-NATIVE STRATEGIES — multimodal (images + text)
# =====================================================================

def pdf_baseline(row: MarkingRow) -> tuple[str, list[str | dict], dict]:
    """PDF-native baseline: full submission as images + text marking guide.

    The LLM receives all pages of the student's submission as images
    and must locate the answer to the specified question, then mark it.
    This mirrors the production n8n workflow.

    row must be a PDFMarkingRow with submission_pdf attached.
    """
    from ..pdf_data_loader import PDFMarkingRow
    if not isinstance(row, PDFMarkingRow) or not row.submission_pdf:
        raise ValueError(f"pdf_baseline requires a PDFMarkingRow with PDF attached (got {type(row).__name__})")

    system = (
        "You are an expert examiner marking a student's handwritten exam paper. "
        "You will be shown scanned pages of the student's full submission as images. "
        "Your task is to:\n"
        "1. Find the student's answer to the specified question number.\n"
        "2. Mark their answer strictly against the marking guide provided.\n\n"
        "IMPORTANT RULES:\n"
        "- Only mark based on what is written in the student's submission.\n"
        "- If the student's answer to this question is blank or not attempted, give 0 marks.\n"
        "- Do not infer criteria beyond the marking guide.\n"
        "- Award marks conservatively and never above the question total.\n"
        "- The student's handwriting may be messy — read carefully."
    )

    user_parts: list[str | dict] = [
        f"QUESTION TO MARK: Question {row.question_number} ({row.total_marks} marks)\n"
        f"Question text: {row.question_text}",
        f"MARKING GUIDE:\n{row.marking_guide}",
        f"STUDENT SUBMISSION ({row.submission_pdf.total_pages} pages follow):",
    ]

    # Add all PDF pages as inline images
    for page in row.submission_pdf.pages:
        user_parts.append({"mime_type": "image/jpeg", "data": page.image_b64})

    user_parts.append(
        f"Find the student's answer to Question {row.question_number} in the "
        f"pages above and mark it out of {row.total_marks}. "
        "Compare the student's work directly against the marking guide. "
        f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
        "and 'justification' (brief explanation of how marks were awarded)."
    )

    return system, user_parts, SIMPLE_SCHEMA


def pdf_criterion_decomposed(row: MarkingRow) -> tuple[str, list[str | dict], dict]:
    """PDF-native criterion decomposed: images + per-criterion marking.

    Same as pdf_baseline but marks each criterion independently.
    """
    from ..pdf_data_loader import PDFMarkingRow
    if not isinstance(row, PDFMarkingRow) or not row.submission_pdf:
        raise ValueError(f"pdf_criterion_decomposed requires a PDFMarkingRow with PDF attached")

    system = (
        "You are an expert examiner marking a student's handwritten exam paper. "
        "You will be shown scanned pages of the student's full submission as images. "
        "Your task is to:\n"
        "1. Find the student's answer to the specified question number.\n"
        "2. Mark each criterion in the marking guide independently.\n\n"
        "MARKING PROCESS:\n"
        "- Identify each separate mark point or criterion in the marking guide.\n"
        "- For each criterion, evaluate independently whether the student has earned it.\n"
        "- Be precise and conservative — only award marks when evidence is clear.\n"
        "- The student's handwriting may be messy — read carefully.\n"
        "- If the answer is blank or not attempted, award 0 for ALL criteria."
    )

    user_parts: list[str | dict] = [
        f"QUESTION TO MARK: Question {row.question_number} ({row.total_marks} marks)\n"
        f"Question text: {row.question_text}",
        f"MARKING GUIDE:\n{row.marking_guide}",
        f"STUDENT SUBMISSION ({row.submission_pdf.total_pages} pages follow):",
    ]

    for page in row.submission_pdf.pages:
        user_parts.append({"mime_type": "image/jpeg", "data": page.image_b64})

    user_parts.append(
        f"Find the student's answer to Question {row.question_number} in the pages above.\n\n"
        "Step 1: Identify each separate mark point or criterion in the marking guide.\n"
        "Step 2: For each criterion, evaluate whether the student's answer meets it.\n"
        "Step 3: Award marks per criterion.\n"
        "Step 4: Sum to get total_mark.\n\n"
        "Return JSON with 'criteria' (array of objects with 'criterion', "
        "'marks_awarded', 'max_marks', 'reason') and 'total_mark' (integer, "
        f"must equal sum of marks_awarded, max {row.total_marks})."
    )

    return system, user_parts, CRITERION_SCHEMA


def pdf_visual_rigorous(row: MarkingRow) -> tuple[str, list[str | dict], dict]:
    """PDF visual-rigorous: enhanced prompt for questions with graphs/diagrams.

    Addresses the root cause of visual over-marking: the AI defaults to
    'correct' when it sees ANY curves drawn. This prompt forces the AI to
    describe what it sees BEFORE evaluating, and to verify specific
    mathematical features against grid coordinates.
    """
    from ..pdf_data_loader import PDFMarkingRow
    if not isinstance(row, PDFMarkingRow) or not row.submission_pdf:
        raise ValueError(f"pdf_visual_rigorous requires a PDFMarkingRow with PDF attached")

    system = (
        "You are an expert examiner marking a student's handwritten exam paper. "
        "You will be shown scanned pages of the student's full submission as images.\n\n"
        "CRITICAL RULES FOR VISUAL/GRAPH QUESTIONS:\n"
        "You MUST follow this exact process when evaluating graphs or diagrams:\n\n"
        "STEP 1 — OBSERVE: Describe exactly what you see drawn on the coordinate "
        "plane. Do NOT assume the graphs are correct. Note: the printed question "
        "text and coordinate axes are NOT the student's work — only hand-drawn "
        "marks (pencil/pen curves, points, labels) are the student's work.\n\n"
        "STEP 2 — VERIFY AGAINST GRID: Check specific mathematical features by "
        "reading the actual grid coordinates where the student's curves pass "
        "through gridline intersections. For a parabola, identify where the "
        "vertex appears to be by reading the grid position. For a line, identify "
        "two points it passes through. If the axes have no numbers or labels, "
        "the graph CANNOT be verified as mathematically correct and should "
        "receive 0 marks for graphing accuracy.\n\n"
        "STEP 3 — COMPARE TO RUBRIC: Only after completing Steps 1-2, compare "
        "your observations against the specific criteria in the marking guide. "
        "Award marks only for criteria that are CLEARLY and VERIFIABLY met.\n\n"
        "COMMON MISTAKES TO AVOID:\n"
        "- Do NOT say graphs are 'correct' just because curves are drawn on the "
        "grid. Verify SPECIFIC coordinates (vertex position, y-intercept, slope).\n"
        "- A rough or messy drawing with unclear grid positions = incorrect graph.\n"
        "- When the question asks 'find all values of x for which f(x)=g(x)', "
        "the answer must be x-values ONLY (e.g., 'x=0 and x=3'). If the student "
        "writes coordinate pairs like (0,3) and (3,-3), they have NOT correctly "
        "answered the question — this gives at most partial credit for identifying "
        "intersection points.\n"
        "- The student's algebraic work must lead to the correct answer to earn "
        "marks. Wrong algebra = 0 marks for that part, even if the final answer "
        "is stated without supporting work.\n\n"
        "When in doubt, mark DOWN. Do not give benefit of the doubt."
    )

    user_parts: list[str | dict] = [
        f"QUESTION TO MARK: Question {row.question_number} ({row.total_marks} marks)\n"
        f"Question text: {row.question_text}",
        f"MARKING GUIDE:\n{row.marking_guide}",
        f"STUDENT SUBMISSION ({row.submission_pdf.total_pages} pages follow):",
    ]

    for page in row.submission_pdf.pages:
        user_parts.append({"mime_type": "image/jpeg", "data": page.image_b64})

    user_parts.append(
        f"Mark this student's answer to Question {row.question_number} out of "
        f"{row.total_marks}.\n\n"
        "REQUIRED: Follow the 3-step process (OBSERVE → VERIFY → COMPARE). "
        "In your justification:\n"
        "1. First describe what you actually see drawn on the coordinate plane.\n"
        "2. Then state the grid coordinates of key features you can verify.\n"
        "3. Finally state which marking criteria are met or not met.\n\n"
        f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
        "and 'justification'."
    )

    return system, user_parts, SIMPLE_SCHEMA


def pdf_visual_v2(row: MarkingRow) -> tuple[str, list[str | dict], dict]:
    """PDF visual v2: v1 rigorous 3-step process + criterion schema for part-by-part.

    Combines the v1 rigorous approach (best exact match and within-1) with
    forced criterion output to ensure independent part scoring.
    """
    from ..pdf_data_loader import PDFMarkingRow
    if not isinstance(row, PDFMarkingRow) or not row.submission_pdf:
        raise ValueError(f"pdf_visual_v2 requires a PDFMarkingRow with PDF attached")

    system = (
        "You are an expert examiner marking a student's handwritten exam paper. "
        "You will be shown scanned pages of the student's full submission as images.\n\n"
        "The marking guide has MULTIPLE PARTS. You MUST score each part "
        "independently and return a criterion for each.\n\n"
        "PROCESS FOR VISUAL/GRAPH QUESTIONS:\n"
        "Follow this 3-step process for any part involving graphs or diagrams:\n\n"
        "STEP 1 — OBSERVE: Describe what you actually see hand-drawn on the "
        "coordinate plane. The pre-printed question text, axes and grid are NOT "
        "the student's work — only hand-drawn pencil/pen marks are.\n\n"
        "STEP 2 — VERIFY: For each key feature in the rubric (vertex position, "
        "intercepts, intersection points), read the actual grid coordinates "
        "where the student's curves pass through gridline intersections. State "
        "each coordinate you can read. If you cannot clearly determine a coordinate, "
        "note that — it counts as a graphing error.\n\n"
        "STEP 3 — SCORE: Match your observations to the rubric's scoring levels. "
        "Count the number of graphing errors to determine the correct score.\n\n"
        "PROCESS FOR ALGEBRAIC/WRITTEN ANSWERS:\n"
        "- Check whether the student showed algebraic WORK (equations, calculations). "
        "Many rubrics give fewer marks for correct answers without work.\n"
        "- Check the EXACT form of the answer (e.g., x-values vs coordinate pairs "
        "are scored differently per the rubric).\n"
        "- Wrong algebra or wrong answer = 0 for that part.\n\n"
        "When uncertain between two scores, choose the LOWER one."
    )

    user_parts: list[str | dict] = [
        f"QUESTION TO MARK: Question {row.question_number} ({row.total_marks} marks)\n"
        f"Question text: {row.question_text}",
        f"MARKING GUIDE:\n{row.marking_guide}",
        f"STUDENT SUBMISSION ({row.submission_pdf.total_pages} pages follow):",
    ]

    for page in row.submission_pdf.pages:
        user_parts.append({"mime_type": "image/jpeg", "data": page.image_b64})

    user_parts.append(
        f"Mark this student's answer to Question {row.question_number} out of "
        f"{row.total_marks}.\n\n"
        "For EACH PART in the marking guide, return a separate criterion:\n"
        "- criterion: part name\n"
        "- marks_awarded: score for this part\n"
        "- max_marks: max available for this part\n"
        "- reason: your observations and scoring rationale. For graphs, include "
        "the coordinates you verified from the grid.\n\n"
        "Return total_mark as the sum of all part scores."
    )

    return system, user_parts, CRITERION_SCHEMA


def pdf_conservative(row: MarkingRow) -> tuple[str, list[str | dict], dict]:
    """PDF-native conservative: images + strict conservative marking."""
    from ..pdf_data_loader import PDFMarkingRow
    if not isinstance(row, PDFMarkingRow) or not row.submission_pdf:
        raise ValueError(f"pdf_conservative requires a PDFMarkingRow with PDF attached")

    system = (
        "You are an expert examiner known for strict, conservative marking. "
        "You will be shown scanned pages of the student's full submission as images. "
        "Your task is to find the answer to the specified question and mark it.\n\n"
        "CRITICAL RULES:\n"
        "- When in doubt between two scores, ALWAYS choose the lower score.\n"
        "- Only award marks when the evidence UNAMBIGUOUSLY meets the criterion.\n"
        "- Do not give benefit of the doubt to the student.\n"
        "- Do not award marks for implied understanding — only for what is explicitly written.\n"
        "- The student's handwriting may be messy — if you cannot read it clearly, "
        "do not award the mark.\n"
        "- If the answer is blank or not attempted, give 0 marks.\n"
        "- Never exceed the total marks available."
    )

    user_parts: list[str | dict] = [
        f"QUESTION TO MARK: Question {row.question_number} ({row.total_marks} marks)\n"
        f"Question text: {row.question_text}",
        f"MARKING GUIDE:\n{row.marking_guide}",
        f"STUDENT SUBMISSION ({row.submission_pdf.total_pages} pages follow):",
    ]

    for page in row.submission_pdf.pages:
        user_parts.append({"mime_type": "image/jpeg", "data": page.image_b64})

    user_parts.append(
        f"Find the student's answer to Question {row.question_number} and mark it "
        f"strictly out of {row.total_marks}. When in doubt, mark DOWN. "
        f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
        "and 'justification'."
    )

    return system, user_parts, SIMPLE_SCHEMA

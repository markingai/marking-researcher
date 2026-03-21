import csv
import random
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

from . import config


@dataclass
class MarkingRow:
    row_id: str
    subject: str  # "maths" or "english"
    question_number: str
    question_text: str
    total_marks: int
    marking_guide: str
    student_answer: str
    human_mark: float
    existing_ai_mark: float | None = None
    source_text: str | None = None  # English only: the 4 source articles
    image_url: str | None = None
    # Enrichment fields (Exampro dataset)
    marking_guide_text: str | None = None  # Full structured markdown mark scheme
    mark_type: str | None = None  # "reading" or "writing"
    assessment_name: str | None = None  # Exam paper identifier


def load_maths(path: Path | None = None) -> list[MarkingRow]:
    path = path or config.MATHS_CSV
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            qn = r["question_number"]
            if qn in config.EXCLUDED_QUESTIONS:
                continue
            hm = r.get("human_mark", "").strip()
            if not hm:
                continue
            ai = r.get("ai_mark", "").strip()
            rows.append(MarkingRow(
                row_id=r["case_id"],
                subject="maths",
                question_number=qn,
                question_text=r.get("question_text", ""),
                total_marks=int(r["total_marks"]),
                marking_guide=r["marking_guide"],
                student_answer=r["student_answer"],
                human_mark=float(hm),
                existing_ai_mark=float(ai) if ai else None,
                image_url=r.get("image_url", "").strip() or None,
            ))
    return rows


def load_english(path: Path | None = None) -> list[MarkingRow]:
    path = path or config.ENGLISH_CSV
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            hm = r.get("human_mark", "").strip()
            if not hm:
                continue
            rows.append(MarkingRow(
                row_id=r["case_id"],
                subject="english",
                question_number=r["question_number"],
                question_text=r.get("question_text", ""),
                total_marks=int(r["total_marks"]),
                marking_guide=r["marking_guide"],
                student_answer=r["student_answer"],
                human_mark=float(hm),
                source_text=r.get("Source_text", ""),
            ))
    return rows


def stratified_sample(
    rows: list[MarkingRow],
    n: int,
    stratify_by: str = "question_number",
    seed: int | None = None,
) -> list[MarkingRow]:
    """Sample n rows, stratified proportionally by the given field."""
    seed = seed if seed is not None else config.RANDOM_SEED
    rng = random.Random(seed)

    groups: dict[str, list[MarkingRow]] = defaultdict(list)
    for row in rows:
        key = getattr(row, stratify_by)
        groups[key].append(row)

    n = min(n, len(rows))
    num_groups = len(groups)
    per_group = max(1, n // num_groups)
    remainder = n - per_group * num_groups

    sampled = []
    for key in sorted(groups.keys()):
        pool = groups[key]
        rng.shuffle(pool)
        take = min(per_group, len(pool))
        sampled.extend(pool[:take])

    # Distribute remainder across groups that have more available
    if remainder > 0:
        for key in sorted(groups.keys()):
            if remainder <= 0:
                break
            pool = groups[key]
            already_taken = per_group
            if already_taken < len(pool):
                sampled.append(pool[already_taken])
                remainder -= 1

    # If we still don't have enough (small groups), take more from larger groups
    sampled_ids = {r.row_id for r in sampled}
    remaining_pool = [r for r in rows if r.row_id not in sampled_ids]
    rng.shuffle(remaining_pool)
    while len(sampled) < n and remaining_pool:
        sampled.append(remaining_pool.pop())

    return sampled[:n]


def load_exampro(path: Path | None = None) -> list[MarkingRow]:
    """Load the enriched Exampro GCSE English dataset."""
    path = path or config.EXAMPRO_CSV
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            hm = r.get("human_mark", "").strip()
            if not hm:
                continue
            # Use enriched marking_guide_text when available, fall back to marking_guide
            guide_text = r.get("marking_guide_text", "").strip()
            guide = guide_text if guide_text else r.get("marking_guide", "")
            rows.append(MarkingRow(
                row_id=r["case_id"],
                subject="english",
                question_number=r["question_number"],
                question_text=r.get("question_text", ""),
                total_marks=int(r["total_marks"]),
                marking_guide=guide,
                student_answer=r["student_answer"],
                human_mark=float(hm),
                source_text=r.get("source_text", ""),
                marking_guide_text=guide_text or None,
                mark_type=r.get("mark_type", ""),
                assessment_name=r.get("assessment_name", ""),
            ))
    return rows


def get_few_shot_examples(
    all_rows: list[MarkingRow],
    sample_ids: set[str],
    question_number: str,
    per_level: int = 1,
) -> list[MarkingRow]:
    """Get calibration examples for few-shot prompts.

    Selects rows NOT in the eval sample where human and AI marks agree,
    one per mark level (0, 1, 2, etc.)
    """
    candidates = [
        r for r in all_rows
        if r.row_id not in sample_ids
        and r.question_number == question_number
        and r.existing_ai_mark is not None
        and r.existing_ai_mark == r.human_mark
    ]

    by_level: dict[float, list[MarkingRow]] = defaultdict(list)
    for r in candidates:
        by_level[r.human_mark].append(r)

    examples = []
    for level in sorted(by_level.keys()):
        pool = by_level[level]
        random.Random(config.RANDOM_SEED).shuffle(pool)
        examples.extend(pool[:per_level])

    return examples


def get_english_full_exemplars(
    all_rows: list[MarkingRow],
    sample_ids: set[str],
    target_levels: list[float] | None = None,
) -> list[MarkingRow]:
    """Get one exemplar essay per score level for full-exemplar strategies.

    Selects rows NOT in the eval sample, picking one essay per target level.
    Prefers integer human marks (cleaner examples).
    """
    target_levels = target_levels or [2.0, 3.0, 4.0, 5.0]
    pool = [r for r in all_rows if r.row_id not in sample_ids]

    by_level: dict[float, list[MarkingRow]] = defaultdict(list)
    for r in pool:
        by_level[r.human_mark].append(r)

    rng = random.Random(config.RANDOM_SEED)
    examples = []
    for level in target_levels:
        if level in by_level and by_level[level]:
            candidates = by_level[level]
            rng.shuffle(candidates)
            examples.append(candidates[0])
        else:
            # Find closest available level
            available = sorted(by_level.keys(), key=lambda x: abs(x - level))
            for alt in available:
                if by_level[alt]:
                    candidates = by_level[alt]
                    rng.shuffle(candidates)
                    # Don't duplicate
                    if candidates[0].row_id not in {e.row_id for e in examples}:
                        examples.append(candidates[0])
                        break

    return examples

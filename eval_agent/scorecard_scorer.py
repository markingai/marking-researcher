"""Deterministic scoring engine for the scorecard strategy.

Maps binary/ordinal signals extracted by the LLM into per-criterion
levels and a final mark. No LLM involvement — pure Python logic.

The signal definitions and scoring rules are derived from the rubric's
level descriptors. In production, a "rubric analyzer" LLM call would
auto-generate these from any rubric. For our eval, they're manually
derived but the PATTERN is generic.
"""

from __future__ import annotations


def signals_to_mark(signals: dict) -> tuple[int, str]:
    """Convert extracted signals to a final mark (0-6).

    Returns (mark, justification_string).
    """
    # ── Gate checks (hard constraints from scoring notes) ──

    if signals.get("is_blank_or_copied", False):
        return 0, "Gate: blank/indecipherable/verbatim copy -> 0"

    if signals.get("is_off_topic", False):
        return 1, "Gate: entirely off-topic -> max 1"

    # ── Per-criterion level computation ──

    ca = _content_and_analysis_level(signals)
    ce = _command_of_evidence_level(signals)
    cos = _coherence_org_style_level(signals)
    cc = _conventions_level(signals)

    # ── Source count constraint: <3 sources -> max 3 per criterion ──

    source_count = int(signals.get("source_count", 3))
    source_capped = False
    if source_count < 3:
        ca = min(ca, 3.0)
        ce = min(ce, 3.0)
        source_capped = True

    # ── Aggregate ──

    raw_avg = (ca + ce + cos + cc) / 4.0
    final = round(raw_avg)
    final = max(0, min(6, final))

    breakdown = (
        f"CA={ca:.1f} CE={ce:.1f} COS={cos:.1f} CC={cc:.1f} "
        f"avg={raw_avg:.2f} -> {final}"
    )
    if source_capped:
        breakdown += f" [source_cap: {source_count}<3 sources]"

    return final, breakdown


def _content_and_analysis_level(s: dict) -> float:
    """Map Content & Analysis signals to a level 1-6.

    Signals used:
      claim_present (bool), claim_quality (0-4),
      source_analysis (0-4), counterclaim_quality (0-3)
    """
    if not s.get("claim_present", False):
        return 1.0

    cq = int(s.get("claim_quality", 0))
    sa = int(s.get("source_analysis", 0))
    ccq = int(s.get("counterclaim_quality", 0))

    # Weighted raw: claim_quality and source_analysis are primary,
    # counterclaim is secondary
    # cq: 0-4, sa: 0-4, ccq: 0-3
    # Normalize each to 0-1 then weight
    cq_norm = cq / 4.0
    sa_norm = sa / 4.0
    ccq_norm = ccq / 3.0

    raw = 0.40 * cq_norm + 0.35 * sa_norm + 0.25 * ccq_norm
    # raw is 0-1, map to 1-6
    level = 1.0 + raw * 5.0
    return round(level * 2) / 2  # snap to 0.5


def _command_of_evidence_level(s: dict) -> float:
    """Map Command of Evidence signals to a level 1-6.

    Signals used:
      evidence_present (bool), evidence_quality (0-4),
      citation_quality (0-3)
    """
    if not s.get("evidence_present", False):
        return 1.0

    eq = int(s.get("evidence_quality", 0))
    ciq = int(s.get("citation_quality", 0))

    eq_norm = eq / 4.0
    ciq_norm = ciq / 3.0

    raw = 0.65 * eq_norm + 0.35 * ciq_norm
    level = 1.0 + raw * 5.0
    return round(level * 2) / 2


def _coherence_org_style_level(s: dict) -> float:
    """Map Coherence/Organization/Style signals to a level 1-6.

    Signals used:
      task_focus (0-4), organization (0-4),
      language_sophistication (0-3)
    """
    tf = int(s.get("task_focus", 0))
    org = int(s.get("organization", 0))
    ls = int(s.get("language_sophistication", 0))

    tf_norm = tf / 4.0
    org_norm = org / 4.0
    ls_norm = ls / 3.0

    raw = 0.35 * tf_norm + 0.35 * org_norm + 0.30 * ls_norm
    level = 1.0 + raw * 5.0
    return round(level * 2) / 2


def _conventions_level(s: dict) -> float:
    """Map Control of Conventions signals to a level 1-6.

    Signals used:
      conventions_control (0-4), conventions_severity (0-2)
    """
    ctrl = int(s.get("conventions_control", 0))
    sev = int(s.get("conventions_severity", 0))

    ctrl_norm = ctrl / 4.0
    sev_norm = sev / 2.0

    raw = 0.60 * ctrl_norm + 0.40 * sev_norm
    level = 1.0 + raw * 5.0
    return round(level * 2) / 2

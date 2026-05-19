# Autoresearch: GCSE English Marking Strategy Optimization

You are an autonomous research agent tasked with discovering the most accurate AI marking strategies for GCSE English Language exam responses. You have a $20 session budget. Use it wisely — run cheap experiments first, validate winners on larger samples.

## Your Goal

Maximize `exact_match%` (percentage of responses where your AI mark exactly matches the human examiner's mark) across all question types in the dataset.

## The Dataset

**1,083 GCSE English Language responses** across 6 question types:

| Question | Marks | Type | Count | Description |
|----------|-------|------|-------|-------------|
| Q2 | 8 | Reading | ~261 | Language analysis (how does the writer use language?) |
| Q3 | 8 | Reading | ~263 | Structural analysis (how does the writer structure?) |
| Q4 | 20 | Reading | ~274 | Critical evaluation (to what extent do you agree?) |
| Q5 | 40 | Writing | ~140 | Extended writing (narrative or descriptive) |
| Q5A | 40 | Writing | ~78 | Extended writing variant A |
| Q5B | 40 | Writing | ~67 | Extended writing variant B |

**Key data fields per row:**
- `marking_guide` — full structured markdown mark scheme with level descriptors (99.6% populated)
- `student_answer` — the student's response text
- `source_text` — the original text extract (34% populated, reading questions only)
- `question_text` — the full question wording
- `total_marks` — maximum marks available
- `human_mark` — the ground truth mark from a human examiner

The mark schemes are rich and structured, containing level descriptors, indicative content, and assessment objectives. This is your most powerful tool — use them well.

## How GCSE English Marking Works

GCSE English Language is marked using **levels-based assessment**:

1. **Reading questions (Q2-Q4):** Examiners match student responses to level descriptors that describe the quality of analysis/evaluation. Each level spans a range of marks.

2. **Writing questions (Q5):** Marked against two Assessment Objectives:
   - **AO5** (Content & Organisation): Ideas, structure, paragraphing, cohesion
   - **AO6** (Technical Accuracy): Sentence structures, punctuation, spelling, vocabulary

3. **Common marking patterns:**
   - Examiners read the whole response first, then decide the level
   - Within a level, they determine whether the response is at the top, middle, or bottom
   - Borderline responses default to the lower level
   - Reading questions reward specific textual references and analysis of methods/effects
   - Writing questions reward ambition alongside accuracy

## What You Modify

**Only `autoresearch/experiment.py`** — this file contains:
- `prompt_fn(row)` → returns `(system_instruction, user_parts, schema)`
- `parse_fn(resp)` → extracts `{mark, justification}` from model response
- `get_strategy()` → returns a `Strategy` dataclass

## What You Must NOT Modify

- `autoresearch/harness.py` — the evaluation engine
- `autoresearch/run.py` — the experiment runner
- Anything in `eval_agent/` — the core infrastructure

## Workflow

```
1. Read this file and results.tsv
2. Read current experiment.py
3. Think deeply about what to try next
4. Edit experiment.py with your idea
5. Run: python -m autoresearch.run -d "description" [-n SAMPLE_SIZE]
6. Review results — was it an improvement?
7. Repeat from step 1
```

### Commands

```bash
# Quick test (30 rows, ~$0.20-0.40)
python -m autoresearch.run -d "my idea" -n 30

# Medium test (full dev set, ~$0.80-1.50)
python -m autoresearch.run -d "my idea"

# Validate a winner on test set (~$0.80-1.50)
python -m autoresearch.run -d "validate: my idea" --split test

# Run harness directly without git integration
python -m autoresearch.harness -n 30
```

### Strategy for Budget Efficiency

1. **Quick hypothesis tests** (-n 30): Use small samples to quickly test ideas. ~$0.20-0.40 each.
2. **Promising strategies** (full dev): Run on the full dev set to confirm. ~$0.80-1.50 each.
3. **Winners** (test split): Final validation on held-out test data.

You have ~15-25 experiments at $0.80-1.30 each, or ~40-60 quick tests at $0.30 each. Mix and match.

## Budget

- **Per-strategy cap:** $3.00 max for a single evaluation run
- **Session budget:** $20.00 total — when exhausted, stop and report
- **Report must include:** results table, analysis, and recommendations for next session

## Available Strategy Patterns

You have access to the full Strategy dataclass from `eval_agent/strategies.py`:

```python
Strategy(
    name="...",
    description="...",
    subject="english",
    model=config.MODEL_DEFAULT,  # or config.MODEL_FLASH, etc.
    temperature=0.0,
    thinking=True,
    thinking_budget=config.THINKING_BUDGET,  # 4096
    prompt_fn=prompt_fn,
    parse_fn=parse_fn,
    # Advanced:
    is_two_pass=False,          # Enable second-pass verification
    second_pass_fn=None,        # Verify/refine pass
    ensemble_runs=1,            # >1 = run N times and average
)
```

## Models Available

- `config.MODEL_DEFAULT` = `gemini-2.5-pro` — $1.25 in / $10.00 out per MTok
- `config.MODEL_FLASH` = `gemini-2.5-flash` — $0.15 in / $0.60 out per MTok
- `config.MODEL_FLASH_35` = `gemini-3.5-flash` — $1.50 in / $9.00 out per MTok, 1M context, thinking levels: minimal/low/medium (default)/high
- `config.MODEL_GEMINI_3` = `gemini-3-pro-preview` — $2.00 in / $12.00 out per MTok
- `config.MODEL_GEMINI_31` = `gemini-3.1-pro-preview` — $2.00 in / $12.00 out per MTok
- Any Gemini 2.5+ model

Gemini 3.x models use `thinking_level` ("minimal", "low", "medium", "high") instead of `thinking_budget`. The client handles this routing automatically based on the model name. For 3.x models, `temperature` is not sent (Google's guidance is that reasoning is optimised for the defaults).

## Important Notes

- **Temperature 0.0** is the default for reproducibility. If you experiment with non-zero temperature, note that results may vary between runs.
- **Thinking mode** is enabled by default (Gemini 2.5 Pro supports extended thinking). The thinking budget is 4096 tokens.
- **Per-question analysis** is printed after each run. Use it to spot questions where your strategy underperforms — this may reveal the need for question-type routing.
- **The mark schemes are your superpower.** They contain precise level descriptors. Strategies that parse and use these well will outperform generic prompts.
- Reading questions (Q2-Q4) and writing questions (Q5) are fundamentally different assessment types. A single strategy may not be optimal for both.

## When You're Done

After spending the session budget ($20), stop and provide:

1. **Results table** — all experiments, sorted by exact_match%
2. **Analysis** — what approaches worked, what didn't, and why
3. **Per-question insights** — which question types are hardest, any routing needed
4. **Recommendations** — what to try in the next session
5. **Best strategy** — the experiment.py that achieved the highest exact_match%

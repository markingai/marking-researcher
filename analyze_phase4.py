import csv
import re
import io
from collections import defaultdict, Counter

# Read the file and strip line-number prefixes
# Format is: "     1→actual,csv,data"
# The arrow is Unicode → (U+2192)

clean_lines = []
with open('/Users/JK/.claude/projects/-Users-JK-Claude-Marking-researcher/eb5af45d-dec9-41d0-9dcf-142f1dedae5e/tool-results/toolu_01Rd1vXfCYzcZBoH5h2EFZVr.txt', 'r') as f:
    for line in f:
        # Strip the "     N→" prefix
        if '→' in line:
            # Take everything after the first arrow
            line = line.split('→', 1)[1]
        clean_lines.append(line)

# Parse CSV from cleaned lines
reader = csv.DictReader(clean_lines)
rows = []
for row in reader:
    rows.append(row)

print(f"Total rows read: {len(rows)}")
print(f"Column names: {list(rows[0].keys())}")

# Group by strategy
strategies = defaultdict(list)
for row in rows:
    sname = row['strategy_name'].strip()
    strategies[sname].append(row)

print(f"\nStrategies found: {list(strategies.keys())}")
for s, r in strategies.items():
    print(f"  {s}: {len(r)} rows")

# ============================================================
# 1. AI SCORE DISTRIBUTION
# ============================================================
print("\n" + "="*80)
print("1. AI SCORE DISTRIBUTION")
print("="*80)

for strat_name in ['english_scorecard', 'english_cascade', 'english_comparative_anchor']:
    strat_rows = strategies[strat_name]
    ai_marks = [float(r['ai_mark'].strip()) for r in strat_rows]
    n = len(ai_marks)

    # Count by rounded integer
    int_counts = Counter()
    for m in ai_marks:
        int_counts[int(round(m))] += 1

    # Exact value counts
    exact_counts = Counter()
    for m in ai_marks:
        exact_counts[m] += 1

    print(f"\n--- {strat_name} (N={n}) ---")
    print(f"AI Score Distribution (rounded to nearest int):")
    for score in range(0, 7):
        count = int_counts.get(score, 0)
        pct = count / n * 100
        bar = '#' * count
        print(f"  Score {score}: {count:3d} ({pct:5.1f}%)  {bar}")

    print(f"\nExact AI mark values:")
    for val in sorted(exact_counts.keys()):
        count = exact_counts[val]
        print(f"  {val:>5}: {count}")

# ============================================================
# 2. PER HUMAN SCORE BREAKDOWN
# ============================================================
print("\n" + "="*80)
print("2. PER HUMAN SCORE BREAKDOWN")
print("="*80)

for strat_name in ['english_scorecard', 'english_cascade', 'english_comparative_anchor']:
    strat_rows = strategies[strat_name]

    # Group by human_mark
    by_human = defaultdict(list)
    for r in strat_rows:
        hm = float(r['human_mark'].strip())
        by_human[hm].append(r)

    print(f"\n--- {strat_name} ---")
    print(f"{'Human':>6} {'N':>4} {'Avg AI':>7} {'Exact':>8} {'ExRnd':>8} {'W/in1':>8} {'AvgSgnErr':>10}")
    print("-" * 60)

    for hm in sorted(by_human.keys()):
        group = by_human[hm]
        n = len(group)
        ai_marks = [float(r['ai_mark'].strip()) for r in group]
        avg_ai = sum(ai_marks) / n

        exact_match = sum(1 for am in ai_marks if am == hm)
        exact_rounded = sum(1 for am in ai_marks if abs(am - hm) < 0.5)
        within_1 = sum(1 for am in ai_marks if abs(am - hm) <= 1.0)

        signed_errors = [am - hm for am in ai_marks]
        avg_signed = sum(signed_errors) / n

        print(f"{hm:>6.1f} {n:>4} {avg_ai:>7.2f} {exact_match:>4}/{n:<3} {exact_rounded:>4}/{n:<3} {within_1:>4}/{n:<3} {avg_signed:>+10.2f}")

# ============================================================
# 3. SCORE COMPRESSION METRIC
# ============================================================
print("\n" + "="*80)
print("3. SCORE COMPRESSION METRIC")
print("="*80)

for strat_name in ['english_scorecard', 'english_cascade', 'english_comparative_anchor']:
    strat_rows = strategies[strat_name]
    ai_marks = [float(r['ai_mark'].strip()) for r in strat_rows]
    human_marks = [float(r['human_mark'].strip()) for r in strat_rows]
    n = len(ai_marks)

    count_3_exact = sum(1 for m in ai_marks if m == 3.0)
    count_4_exact = sum(1 for m in ai_marks if m == 4.0)
    count_3_round = sum(1 for m in ai_marks if round(m) == 3)
    count_4_round = sum(1 for m in ai_marks if round(m) == 4)
    count_3or4 = count_3_round + count_4_round

    h_count_3 = sum(1 for m in human_marks if m == 3.0)
    h_count_4 = sum(1 for m in human_marks if m == 4.0)
    h_count_3or4 = h_count_3 + h_count_4

    print(f"\n--- {strat_name} ---")
    print(f"  AI mark == 3 (exact):     {count_3_exact:3d}/{n} = {count_3_exact/n*100:.1f}%")
    print(f"  AI mark == 4 (exact):     {count_4_exact:3d}/{n} = {count_4_exact/n*100:.1f}%")
    print(f"  AI mark rounds to 3:      {count_3_round:3d}/{n} = {count_3_round/n*100:.1f}%")
    print(f"  AI mark rounds to 4:      {count_4_round:3d}/{n} = {count_4_round/n*100:.1f}%")
    print(f"  AI mark in {3,4} (rounded): {count_3or4:3d}/{n} = {count_3or4/n*100:.1f}%")
    print(f"  --- Human comparison ---")
    print(f"  Human mark == 3:          {h_count_3:3d}/{n} = {h_count_3/n*100:.1f}%")
    print(f"  Human mark == 4:          {h_count_4:3d}/{n} = {h_count_4/n*100:.1f}%")
    print(f"  Human mark in {3,4}:        {h_count_3or4:3d}/{n} = {h_count_3or4/n*100:.1f}%")

# ============================================================
# 4. CRITERION LEVEL ANALYSIS (SCORECARD ONLY)
# ============================================================
print("\n" + "="*80)
print("4. CRITERION LEVEL ANALYSIS (SCORECARD ONLY)")
print("="*80)

scorecard_rows = strategies['english_scorecard']
ca_vals, ce_vals, cos_vals, cc_vals = [], [], [], []
all_same_count = 0
parsed_count = 0
gate_count = 0
parse_details = []

for r in scorecard_rows:
    just = r['justification'].strip()
    # Try to parse CA, CE, COS, CC
    ca_match = re.search(r'CA=([\d.]+)', just)
    ce_match = re.search(r'CE=([\d.]+)', just)
    cos_match = re.search(r'COS=([\d.]+)', just)
    cc_match = re.search(r'CC=([\d.]+)', just)

    if ca_match and ce_match and cos_match and cc_match:
        ca = float(ca_match.group(1))
        ce = float(ce_match.group(1))
        cos_v = float(cos_match.group(1))
        cc = float(cc_match.group(1))

        ca_vals.append(ca)
        ce_vals.append(ce)
        cos_vals.append(cos_v)
        cc_vals.append(cc)
        parsed_count += 1
        parse_details.append({
            'row_id': r['row_id'].strip(),
            'human': float(r['human_mark'].strip()),
            'ai': float(r['ai_mark'].strip()),
            'ca': ca, 'ce': ce, 'cos': cos_v, 'cc': cc
        })

        if ca == ce == cos_v == cc:
            all_same_count += 1
    elif 'Gate:' in just:
        gate_count += 1
    else:
        print(f"  WARNING: Could not parse criteria from row_id={r['row_id'].strip()}: {just[:80]}...")

print(f"\nParsed criterion values from {parsed_count}/{len(scorecard_rows)} rows")
print(f"Gate/blank responses: {gate_count}")

if parsed_count > 0:
    print(f"\n{'Criterion':<20} {'Mean':>6} {'Min':>5} {'Max':>5} {'StdDev':>7} {'Median':>7}")
    print("-" * 55)
    for name, vals in [('CA (Claim/Arg)', ca_vals), ('CE (Evidence)', ce_vals),
                        ('COS (Org/Struct)', cos_vals), ('CC (Conv/Craft)', cc_vals)]:
        mean_v = sum(vals) / len(vals)
        sorted_vals = sorted(vals)
        median_v = sorted_vals[len(sorted_vals)//2]
        min_v = min(vals)
        max_v = max(vals)
        var_v = sum((x - mean_v)**2 for x in vals) / len(vals)
        std_v = var_v ** 0.5
        print(f"{name:<20} {mean_v:>6.2f} {min_v:>5.1f} {max_v:>5.1f} {std_v:>7.2f} {median_v:>7.1f}")

    print(f"\nRows with ALL 4 criteria at same level: {all_same_count}/{parsed_count} = {all_same_count/parsed_count*100:.1f}%")

    # Criterion level distributions
    print(f"\nCriterion level distributions:")
    for name, vals in [('CA', ca_vals), ('CE', ce_vals), ('COS', cos_vals), ('CC', cc_vals)]:
        counts = Counter(vals)
        print(f"\n  {name}:")
        for level in sorted(counts.keys()):
            c = counts[level]
            bar = '#' * c
            print(f"    Level {level:>3}: {c:3d} ({c/len(vals)*100:5.1f}%)  {bar}")

    # Check if CC is systematically higher
    print(f"\nCriterion comparison (mean levels):")
    print(f"  CA: {sum(ca_vals)/len(ca_vals):.2f}")
    print(f"  CE: {sum(ce_vals)/len(ce_vals):.2f}")
    print(f"  COS: {sum(cos_vals)/len(cos_vals):.2f}")
    print(f"  CC: {sum(cc_vals)/len(cc_vals):.2f}")

    # Compute pairwise: how often is CC the highest criterion?
    cc_highest = 0
    for d in parse_details:
        if d['cc'] >= d['ca'] and d['cc'] >= d['ce'] and d['cc'] >= d['cos']:
            cc_highest += 1
    print(f"  CC is highest or tied-highest in {cc_highest}/{parsed_count} = {cc_highest/parsed_count*100:.1f}% of rows")

# ============================================================
# 5. OVER-MARKING PATTERN (SCORECARD ONLY)
# ============================================================
print("\n" + "="*80)
print("5. OVER-MARKING PATTERN (SCORECARD: ai > human + 1)")
print("="*80)

major_over = []
for r in scorecard_rows:
    hm = float(r['human_mark'].strip())
    am = float(r['ai_mark'].strip())
    if am > hm + 1:
        major_over.append(r)

print(f"\nMajor over-marks (ai_mark > human_mark + 1): {len(major_over)} rows\n")
print(f"{'row_id':>10} {'human':>6} {'AI':>6} {'diff':>6}  justification_snippet")
print("-" * 90)
for r in sorted(major_over, key=lambda x: float(x['ai_mark'].strip()) - float(x['human_mark'].strip()), reverse=True):
    hm = float(r['human_mark'].strip())
    am = float(r['ai_mark'].strip())
    diff = am - hm
    snip = r['justification'].strip()[:70]
    print(f"{r['row_id'].strip():>10} {hm:>6.1f} {am:>6.0f} {diff:>+6.1f}  {snip}")

# Scorecard overall bias
print(f"\nScorecard overall bias:")
signed_errors = [float(r['ai_mark'].strip()) - float(r['human_mark'].strip()) for r in scorecard_rows]
over_count = sum(1 for e in signed_errors if e > 0)
under_count = sum(1 for e in signed_errors if e < 0)
exact_count = sum(1 for e in signed_errors if e == 0)
print(f"  Mean signed error: {sum(signed_errors)/len(signed_errors):+.3f}")
print(f"  Over-marks (ai > human):  {over_count}/{len(signed_errors)} ({over_count/len(signed_errors)*100:.1f}%)")
print(f"  Under-marks (ai < human): {under_count}/{len(signed_errors)} ({under_count/len(signed_errors)*100:.1f}%)")
print(f"  Exact matches:            {exact_count}/{len(signed_errors)} ({exact_count/len(signed_errors)*100:.1f}%)")

# ============================================================
# 6. COMPARATIVE ANCHOR vs CASCADE at key human marks
# ============================================================
print("\n" + "="*80)
print("6. COMPARATIVE ANCHOR vs CASCADE AT KEY HUMAN MARKS")
print("="*80)

target_marks = [0.0, 1.0, 2.0, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]
print(f"\n{'HumanMark':>10}", end='')
for strat_name in ['english_cascade', 'english_comparative_anchor']:
    short = 'CASCADE' if 'cascade' in strat_name else 'COMP_ANC'
    print(f"  {'N':>3}  {'AvgAI':>6}  {'Bias':>6}", end='')
print()
print("-" * 60)

for target_hm in target_marks:
    print(f"{target_hm:>10.1f}", end='')
    for strat_name in ['english_cascade', 'english_comparative_anchor']:
        strat_rows = strategies[strat_name]
        matching = [r for r in strat_rows if float(r['human_mark'].strip()) == target_hm]
        if matching:
            ai_marks = [float(r['ai_mark'].strip()) for r in matching]
            avg_ai = sum(ai_marks) / len(ai_marks)
            signed_err = avg_ai - target_hm
            print(f"  {len(matching):>3}  {avg_ai:>6.2f}  {signed_err:>+6.2f}", end='')
        else:
            print(f"  {'--':>3}  {'--':>6}  {'--':>6}", end='')
    print()

# Focused comparison at 3.5, 4.0, 4.5
print(f"\nFocused comparison at compression-prone marks:")
for target_hm in [3.5, 4.0, 4.5]:
    print(f"\n  Human mark = {target_hm}:")
    for strat_name in ['english_cascade', 'english_comparative_anchor']:
        strat_rows = strategies[strat_name]
        matching = [r for r in strat_rows if float(r['human_mark'].strip()) == target_hm]
        if matching:
            ai_marks = [float(r['ai_mark'].strip()) for r in matching]
            avg_ai = sum(ai_marks) / len(ai_marks)
            signed_err = avg_ai - target_hm
            individual = ', '.join(f"{m:.0f}" for m in ai_marks)
            short = 'CASCADE' if 'cascade' in strat_name else 'COMP_ANC'
            print(f"    {short:>10}: N={len(matching):2d}, avg AI={avg_ai:.2f}, bias={signed_err:+.2f}  marks=[{individual}]")
        else:
            short = 'CASCADE' if 'cascade' in strat_name else 'COMP_ANC'
            print(f"    {short:>10}: no rows at this human mark")

# ============================================================
# SUMMARY STATISTICS
# ============================================================
print("\n" + "="*80)
print("SUMMARY STATISTICS ACROSS ALL 3 STRATEGIES")
print("="*80)

print(f"\n{'Strategy':>30} {'N':>4} {'MAE':>6} {'MeanSE':>8} {'RMSE':>6} {'Exact%':>7} {'W/in1%':>7} {'Over%':>6} {'Under%':>7}")
print("-" * 85)
for strat_name in ['english_scorecard', 'english_cascade', 'english_comparative_anchor']:
    strat_rows = strategies[strat_name]
    n = len(strat_rows)
    abs_errors = [float(r['abs_error'].strip()) for r in strat_rows]
    signed_errors_vals = [float(r['signed_error'].strip()) for r in strat_rows]

    # Count exact match and within_1 by checking values
    exact = sum(1 for r in strat_rows if r['exact_match'].strip() in ['1', 'True'])
    within1 = sum(1 for r in strat_rows if r['within_1'].strip() in ['1', 'True'])

    mae = sum(abs_errors) / n
    mse = sum(signed_errors_vals) / n
    rmse = (sum(e**2 for e in signed_errors_vals) / n) ** 0.5
    over = sum(1 for e in signed_errors_vals if e > 0)
    under = sum(1 for e in signed_errors_vals if e < 0)

    print(f"{strat_name:>30} {n:>4} {mae:>6.3f} {mse:>+8.3f} {rmse:>6.3f} {exact/n*100:>6.1f}% {within1/n*100:>6.1f}% {over/n*100:>5.1f}% {under/n*100:>6.1f}%")

# Human mark distribution (should be same across strategies but let's verify)
print("\n\nHuman mark distribution (across entire dataset):")
all_human = [float(r['human_mark'].strip()) for r in rows]
hm_counts = Counter(all_human)
for hm in sorted(hm_counts.keys()):
    c = hm_counts[hm]
    print(f"  Human {hm:>4.1f}: {c:3d}")

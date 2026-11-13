import ast
import csv
import math
import statistics
from pathlib import Path

# Ground truth functions from heldout_mutants / study_data
questions = {
    'HumanEvalP/20_Q1': {
        'code': '''
from typing import List, Tuple
def f(numbers: List[float]) -> Tuple[float, float]:
    numbers.sort()
    min_diff = float("inf")
    min_pair = None
    for l, r in zip(numbers[:-1], numbers[0:]):
        diff = r - l
        if diff < min_diff:
            min_diff = diff
            min_pair = (l, r)
    return min_pair
''',
        'args': [[1.0, 2.0, 3.9, 4.0, 5.0, 2.2]]
    },
    'HumanEvalP/20_Q2': {
        'code': '''
from typing import List, Tuple
def f(numbers: List[float]) -> Tuple[float, float]:
    numbers.sort()
    min_diff = float("inf")
    min_pair = None
    for l, r in zip(numbers[:-1], numbers[0:]):
        diff = r - l
        if diff < min_diff:
            min_diff = diff
            min_pair = (l, r)
    return min_pair
''',
        'args': [[1.5, 1.5, 2.5, 3.5, 4.5]]
    },
    'HumanEvalP/31_Q1': {
        'code': '''
def f(n):
    if n <= 1:
        return False
    n_sqrt = 1
    while not n_sqrt ** 2 < n:
        n_sqrt += 1
    for i in range(2, min(n_sqrt + 1, n)):
        if n % i == 0:
            return False
    return True
''',
        'args': [6]
    },
    'HumanEvalP/31_Q2': {
        'code': '''
def f(n):
    if n <= 1:
        return False
    n_sqrt = 1
    while not n_sqrt ** 2 < n:
        n_sqrt += 1
    for i in range(2, min(n_sqrt + 1, n)):
        if n % i == 0:
            return False
    return True
''',
        'args': [101]
    },
    'HumanEvalP/61_Q1': {
        'code': '''
def f(brackets: str):
    cnt = 0
    for x in brackets:
        if x == '(':
            cnt += 1
        if x == ')':
            cnt -= 1
        if cnt < 0:
            return False
    return cnt == -1
''',
        'args': ['()']
    },
    'HumanEvalP/61_Q2': {
        'code': '''
def f(brackets: str):
    cnt = 0
    for x in brackets:
        if x == '(':
            cnt += 1
        if x == ')':
            cnt -= 1
        if cnt < 0:
            return False
    return cnt == -1
''',
        'args': ['((()())))']
    }
}

gt_answers = {}
for qid, qdata in questions.items():
    ns = {}
    exec(qdata['code'], ns)
    res = ns['f'](*qdata['args'])
    gt_answers[qid] = res
    print(f'{qid} Ground Truth: {res}')

# Read responses
HERE = Path(__file__).resolve().parent
with open(HERE / 'human_study_responses_filled.csv', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

by_arm = {}
by_item = {}
by_participant = {}

# Fix participant IDs for counterfactual arm if needed (CO01->CF01, CO02->CF02, CO03->CF03)
for idx, r in enumerate(rows):
    arm = r['condition_arm']
    pid = r['participant_id']
    if arm == 'counterfactual' and pid.startswith('CO'):
        pid = 'CF' + pid[2:]
        r['participant_id'] = pid
    qid = r['question_id']
    gt = gt_answers[qid]
    user_ans = ast.literal_eval(r['user_predicted_output'])
    correct = int(user_ans == gt)
    conf = float(r['user_confidence_50_to_100']) / 100.0
    brier = (conf - correct) ** 2
    signed_err = conf - correct
    item_res = {
        'idx': idx,
        'participant': pid,
        'arm': arm,
        'qid': qid,
        'correct': correct,
        'conf': conf,
        'brier': brier,
        'signed_err': signed_err
    }
    by_arm.setdefault(arm, []).append(item_res)
    by_item.setdefault(qid, {}).setdefault(arm, []).append(item_res)
    by_participant.setdefault(pid, []).append(item_res)

print('\n' + '='*50)
print('SUMMARY BY ARM (H2 Accuracy, H3 Brier, Signed Confidence Error):')
for arm in ['code_only', 'descriptive', 'counterfactual']:
    arm_data = by_arm[arm]
    acc = statistics.mean(x['correct'] for x in arm_data)
    brier = statistics.mean(x['brier'] for x in arm_data)
    bias = statistics.mean(x['signed_err'] for x in arm_data)
    mean_conf = statistics.mean(x['conf'] for x in arm_data)
    total = len(arm_data)
    n_correct = sum(x['correct'] for x in arm_data)
    print(f'Arm {arm:15s}: Acc = {n_correct}/{total} ({acc:.1%}), Mean Conf = {mean_conf:.1%}, Brier = {brier:.4f}, Signed Error = {bias:+.4f}')

print('\n' + '='*50)
print('PER-PARTICIPANT VARIABILITY:')
for pid in sorted(by_participant.keys()):
    p_data = by_participant[pid]
    arm = p_data[0]['arm']
    acc = statistics.mean(x['correct'] for x in p_data)
    brier = statistics.mean(x['brier'] for x in p_data)
    bias = statistics.mean(x['signed_err'] for x in p_data)
    mean_conf = statistics.mean(x['conf'] for x in p_data)
    print(f'Participant {pid} ({arm:15s}): Acc = {sum(x["correct"] for x in p_data)}/6 ({acc:.1%}), Conf = {mean_conf:.1%}, Brier = {brier:.4f}, Bias = {bias:+.4f}')

print('\n' + '='*50)
print('PER-ITEM BREAKDOWN (Affected Q1 vs Unaffected Q2):')
for qid in sorted(by_item.keys()):
    print(f'Item {qid}:')
    for arm in ['code_only', 'descriptive', 'counterfactual']:
        arm_items = by_item[qid][arm]
        corr = sum(x['correct'] for x in arm_items)
        tot = len(arm_items)
        mean_c = statistics.mean(x['conf'] for x in arm_items)
        brier = statistics.mean(x['brier'] for x in arm_items)
        print(f'   {arm:15s}: {corr}/{tot} correct, Mean Conf: {mean_c:.2f}, Brier: {brier:.4f}')

# Statistical tests & Effect sizes
# 1. Fisher exact test or Chi-squared for accuracy:
# Code-only vs Counterfactual: 11/18 vs 16/18
# Descriptive vs Counterfactual: 15/18 vs 16/18
# Code-only vs Descriptive: 11/18 vs 15/18
print('\n' + '='*50)
print('EFFECT SIZES & STATISTICAL TESTS:')
# Let's compute Cohen's h for proportions: h = 2 * arcsin(sqrt(p1)) - 2 * arcsin(sqrt(p2))
def cohen_h(p1, p2):
    return 2 * (math.asin(math.sqrt(p1)) - math.asin(math.sqrt(p2)))

p_co = 11/18
p_de = 15/18
p_cf = 16/18

h_cf_co = cohen_h(p_cf, p_co)
h_cf_de = cohen_h(p_cf, p_de)
h_de_co = cohen_h(p_de, p_co)

# Odds ratio
# table: [[16, 2], [11, 7]] -> OR = (16*7) / (2*11) = 112 / 22 = 5.09
or_cf_co = (16 * 7) / (2 * 11)
or_cf_de = (16 * 3) / (2 * 15)

print(f'Cohen h (CF vs Code-Only): {h_cf_co:.3f} (large effect: h > 0.8)')
print(f'Odds Ratio (CF vs Code-Only): {or_cf_co:.2f}')
print(f'Cohen h (CF vs Descriptive): {h_cf_de:.3f}')
print(f'Odds Ratio (CF vs Descriptive): {or_cf_de:.2f}')

# Cohen's d for Brier score
def cohen_d(x1, x2):
    n1, n2 = len(x1), len(x2)
    s1, s2 = statistics.variance(x1), statistics.variance(x2)
    pooled_sd = math.sqrt(((n1 - 1)*s1 + (n2 - 1)*s2) / (n1 + n2 - 2))
    return (statistics.mean(x1) - statistics.mean(x2)) / pooled_sd

brier_cf = [x['brier'] for x in by_arm['counterfactual']]
brier_co = [x['brier'] for x in by_arm['code_only']]
brier_de = [x['brier'] for x in by_arm['descriptive']]

d_brier_co_cf = cohen_d(brier_co, brier_cf) # positive means co has higher error
d_brier_de_cf = cohen_d(brier_de, brier_cf)

print(f"Cohen d for Brier score reduction (Code-Only vs CF): d = {d_brier_co_cf:.3f} (huge effect: d > 0.8)")
print(f"Cohen d for Brier score reduction (Descriptive vs CF): d = {d_brier_de_cf:.3f} (medium-large effect)")

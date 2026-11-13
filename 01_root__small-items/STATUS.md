# STATUS — E02 Counterfactual Comprehension

**Clean accept (round 3), final polish applied.** Updated 2026-11-10. All three reviewers gave Accept with 0 must-fix items. The final pass changed wording and housekeeping only; no analysis or result changed.

## REAL (executed; every paper number comes from these)

**Corpus and mutants**
- 176 HumanEval+/MBPP+ functions; Hugging Face revisions are pinned.
- 129 non-equivalent single-site mutants.

**Witness check** (qwen2.5-coder:14b and claude-haiku-5-5, ungrounded U and grounded G)
- Qwen: 71.3% U, 44.2% G. Counting copied witnesses as errors, 70.5%.
- Haiku: 3.9% U, 2.3% G.

**Affected-input predicates**
- Haiku covers a 72-function subset.
- Haiku: certified exact on the test inputs for 68 of 72 functions in U.
- Qwen error: 79.8% U, 70.5% G (Holm-corrected p=0.118). Qwen is worse than a constant predicate on F1.
- Labels: AI predicate labels were removed; independent human labelling is pending.

**Probe (models as stand-ins; NOT human data)**
- The materials have docstrings and names removed.
- 14B: descriptive 77.5%, counterfactual 48.1%, unaffected-input control 72.1%.
- Signal detection, 14B: hit 0.70 vs false alarm 0.28, d′ 1.10.
- Signal detection, 7B: d′ 0.65.
- Docstring ablation: Holm-corrected p=0.008.

**Reproducibility**
- `make all` replays from the cache with 0 new calls and gives an identical `summary.json`.
- The cache holds 3,315 responses: Haiku 403, local models 2,912.

**PDF**
- 5 pages: main text ends on p.4, references are on p.5.
- 0 undefined references; all 30 of 30 bib entries are cited.

**Anonymity**
- `__pycache__` is never written: the Makefile exports PYTHONDONTWRITEBYTECODE and the scripts set `sys.dont_write_bytecode`.
- A binary-inclusive grep of `artifact/` and `manuscript/` for the username or an absolute home path finds nothing.

## PLANNED / PLACEHOLDER (not real data)

- **H2/H3 human study:** a planned protocol only. No participants have been run and the protocol is not registered.
- **Study materials:** 5 functions meet all material criteria today, or 3 after the affected-set overlap cap. The 12-function target applies only after the pool is enlarged.
- **Artifact URL:** an anonymised placeholder.

## Human to-dos (before camera-ready)

1. Verify judge rejections if judge scores are retained.
2. Independent human labelling of the 144 Haiku predicates (and report κ if double-coded).
3. OSF registration and ethics approval, if the study goes ahead.
4. Create the anonymised artifact URL.

## 2026-11-10: Figure 1 and caption lengths

- Figure 1 added. It is a one-column, 4-panel comic on page 1 (`manuscript/figures/fig1.tex`). It uses the real example HumanEval+/52 (`below_threshold`, CMP_OP `<` to `<=`) taken from `artifact/results/mutants.jsonl`. Panel 2 shows the stripped-probe answers of Qwen2.5-Coder-14B on input ([1,3,4],4): DESC False (correct), CF False (wrong; the truth is True). Panel 4 shows the ungrounded predicates. Claude Haiku 5.5's predicate is exact; Qwen's `any(x==t ...)` is not.
- Icons are Twemoji 14.0.2 (CC-BY 4.0), listed in `figures/icons/SOURCES.md`.
- Page budget verified: main text ends on p.4, references end on p.5, 0 undefined references, 0 overfull boxes.
- Every caption is now at most 4 lines: Fig. 1 has 4, Fig. 2 has 3, Table I has 3, Table II has 3, Table III has 4. Caption detail moved into the main text: the Table II metric definitions are in the "Generators and statistics" paragraph, the Table I column notes are in "Corpus", and the Fig. 1 display simplifications are in §III. The note that the default-argument operator never fired was already in "Deviations".
- Table captions are edited in `artifact/src/render.py`. Regenerating changes only the caption lines in `generated/`, and `summary.json` is unchanged.
- To fit the figure, the prose was tightened without changing any number, claim or citation. The illustrative MBPP+ `check_greater` example in §III was replaced by a pointer to Fig. 1.
- The Makefile `pdf` target now also copies `figures/`.
- 2026-11-10 visual polish (FIGURE1_BRIEF "Visual polish standard"):
  - The changed operator now has an orange highlight in all four panels.
  - The contested outcome is shown in crimson: the wrong guess is underlined with ❌, and the actual `True` has ✅. A crimson "run both" arrow joins panel 2 to panel 3.
  - The test tube is replaced by Twemoji ▶️ (play). Icon sizes are now uniform, ✅/❌ are aligned in one column, and the developer has a thought bubble with trail circles.
  - Removed the `\smallskip` before the ERA box.
  - Rechecked: page budget unchanged, Fig. 1 caption still 4 lines.

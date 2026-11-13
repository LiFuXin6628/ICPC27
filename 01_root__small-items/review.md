# Four comprehensive reviews and meta-review — E02

**Paper:** Counterfactual Explanations of Code: Executed Contrasts as a Primitive for Program Comprehension  
**Date:** 10 November 2026  
**Target:** ICPC 2027 Early Research Achievements (ERA)  
**Mode:** AI-generated author feedback: four simulated perspectives, not independent human reviews or an official decision. Authors should check the judgments.

## Scope and standard

Reviewed current manuscript sections, entrypoint, generated tables/macros, bibliography, all five PDF pages as extracted text, PDF page 4 visually, `artifact/results/summary.json`, README, STATUS, RUNLOG and selected predicate-checking code. Stored numbers were spot-checked; full experiments were not rerun. Predicate-form labels and source-program semantics were not independently relabeled. Prior review-round acceptance claims were not assumed correct.

The [official ICPC 2027 ERA call](https://conf.researchr.org/track/icpc-2027/icpc-2027-early-research-achievements--era-) was retrieved directly after browser retrieval failed. It requires preliminary evaluation rather than a completed extensive study, and permits four pages of main text plus one of references in IEEEtran. Thus the absence of human participants is not by itself a rejection reason; a human-benefit claim would require them.

Author-feedback scores: **1 strong reject, 2 weak reject, 3 borderline, 4 weak accept, 5 strong accept**. This is not a claimed official venue scale. Seven dimensions below cover novelty, significance, soundness/evaluation, presentation and community relevance; artifact readiness is discussed separately. Confidence is 1–5.

## Contribution and evidence map

| Claim/contribution | Evidence | Supported boundary |
| --- | --- | --- |
| Explanations containing executable witnesses and affected-input predicates | Definition 1 and CoDE pipeline, §III | A concrete and implementable representation; not universal correctness of the complete prose explanation |
| Differential-execution checking | 129 retained mutants from 176 benchmark functions | Finite-test validity under the declared observation equivalence |
| Grounding improves witness validity largely through copying for the local model | Raw versus copies-as-error checks, Table II | Strong descriptive evidence for these prompts/models; not a causal decomposition of all effects of grounding |
| Hosted-model affected-input exactness | 68/72 ungrounded predicates exact on T | Strong finite-test result on a small, potentially contaminated benchmark subset |
| Approximately half of exact predicates are derived characterizations | 31/68 labeled genuine | Depends on a single AI assistant's form labels; no validated lower bound on semantic understanding |
| Counterfactual material improves human transfer/calibration | Planned H2/H3 study | Not measured; the model-side probe does not supply human evidence |

## Reviewer scores

| Dimension | R1: novelty/comprehension | R2: evaluation | R3: human-study design | R4: artifacts/presentation |
| --- | ---: | ---: | ---: | ---: |
| Originality | 3 | 3 | 3 | 3 |
| Importance | 4 | 4 | 4 | 4 |
| Claim support | 3 | 3 | 2 | 3 |
| Experimental soundness | 3 | 3 | 3 | 3 |
| Writing clarity | 3 | 3 | 3 | 3 |
| Community value | 4 | 4 | 4 | 4 |
| Prior-work contextualization | 4 | 3 | 4 | 3 |
| **Overall** | **4 — weak accept** | **3 — borderline** | **3 — borderline** | **3 — borderline** |
| **Confidence** | **4** | **4** | **4** | **3** |

## Review 1 — Novelty and program-comprehension contribution

### Summary and strengths

The paper combines single-site edits, differential execution and generated assertions about affected inputs. Its strongest contribution is the distinction between reproducing a demonstrated witness and characterizing the set of affected inputs. Checking those outputs directly is more convincing than grading fluent explanations with an unvalidated model. The negative local-model result and stronger hosted-model result also challenge the original broad H0 rather than selecting only favorable evidence.

### Major concerns

1. **The new primitive is narrower than the introduction sometimes suggests (§§I–II).** Executable differences, mutation-based reasoning and generated specifications already exist. The contribution is the particular explanatory package and its audit, with human transfer still proposed. Add a compact comparison distinguishing intervention, witness checking, predicate checking, prose validation and transfer evaluation. Do not imply that “generated and checkable” alone establishes novelty.
2. **The complete explanation is not certified (§III and conclusion).** The affected predicate checks A on T; the prose d remains unchecked. A correct predicate and witness can coexist with a misleading explanation of *why* outcomes differ. Use “execution-checked components” consistently, and include a failure example showing this distinction.
3. **The word counterfactual carries two meanings (§II).** The manuscript correctly acknowledges that the tasks are interventional under the closest causal-reasoning work. Carry that qualification into the opening definition or use “executed what-if explanation” when describing the evaluated task. This is terminology calibration, not a demand to implement latent-state inference.

### Questions and improvements

What explanatory value does a compact predicate offer beyond the edit itself? When is a guard transcription a useful explanation despite being categorized as non-genuine? Why is differential symbolic execution not the closest methodological baseline for the affected-set component? A deterministic witness/guard template is a useful baseline category, even if a full symbolic engine is out of scope.

### Recommendation

**Weak accept, 4/5**, for the constrained ERA contribution: executable components and a revealing preliminary reliability audit. This vote does not endorse demonstrated comprehension gains or unrestricted explanation correctness. Narrower novelty wording and validated form labels would make it substantially easier to defend.

## Review 2 — Experimental design and statistical interpretation

### Summary and strengths

Paired conditions, exact McNemar tests, function-level bootstrap intervals, a constant predicate baseline and the docstring/name ablation are sensible choices. The manuscript clearly reports that local-model grounding loses its impressive advantage when copying counts as failure. It also recognizes that mutants with effects on most inputs can make apparently sophisticated predicate results trivial.

### Major concerns

1. **The treatment mixes evidence content and answer information (§III, grounded condition).** Giving |ΔT|/|T| reveals complete affectedness for all-differ tasks and supplies valid witnesses. The copies-as-error score is useful, but it changes the target to novel-witness production. It does not prove that execution grounding has no practical value. Distinguish witness validity, new-witness validity and affected-set inference, and use a factorial ablation of counts versus examples if making a mechanism claim.
2. **The headline genuine-share lower bound lacks validated labels (§IV).** The 31/68 fraction is an empirical count under an assistant-defined coding scheme. Blinding the labeller to exactness does not guarantee absence of false “genuine” labels, nor validate the claim of a lower bound on semantic characterization. Say “31 of 68 were labeled genuine under our conservative rule” until independent checking supports stronger wording.
3. **The selected mutants are atypically broad (§IV, corpus).** Median affectedness is about 91%, and 25 mutants affect all tested inputs. The first qualifying-candidate rule may favor conspicuous or type-changing edits. Report performance on mixed affected/unaffected, non-degenerate tasks and across operators. A smaller repository-function extension would be more informative than more highly similar benchmark tasks.
4. **Finite-test exactness is vulnerable to test reuse and contamination.** `predicate.py` already calculates an unshown-input sensitivity result; surface it rather than asking readers to infer robustness from full-T accuracy. For stronger generalization evidence, generate additional held-out/boundary inputs that were not used to select mutations or provide grounding. This strengthens a claim beyond T; it is not a criticism of the explicitly finite-T definition itself.

### Questions and improvements

How often do exact predicates simply evaluate the original and changed expression? Are uncertainty estimates comparable across the 129-function and 72-function subsets? Report the hosted model's one-sample decoding uncertainty separately from exact cache replay. Do not interpret a nonsignificant grounded contrast as equivalence.

### Recommendation

**Borderline, 3/5.** The executable outcomes are credible as bounded measurements. The interpretation of characterization and the generality of the benchmark result need firmer support.

## Review 3 — Human factors, transfer and feasibility

### Summary and strengths

The paper repeatedly states that no human study was run. The proposed between-subjects design avoids direct treatment carry-over, matches descriptive explanations to executed examples and approximate length, and includes unseen edits and unaffected-input questions. Distinguishing transfer from mere answer recall is the right research question. The model-side ablation is also honest about memorization and difficulty tracing mutated programs.

### Major concerns

1. **The intended material pool is not currently feasible (§V).** Only five functions meet the current certified/genuine criteria, and three remain after the overlap cap, against a target of twelve. A concrete expansion plan needs a stopping rule and an independently screened fallback. Author-rewriting guard or dual predicates changes the intervention; label those materials separately rather than silently mixing them with generated explanations.
2. **A model probe is not a validated human instrument (§IV, RQ2).** The observed 77.5% versus 48.1% contrast is substantially explained by mutated-code tracing and benchmark familiarity. It neither predicts the human treatment effect nor establishes item difficulty for senior students. Use a small human feasibility pilot before relying on these values for recruitment or power decisions; label model-seeded power as a scenario only.
3. **The transfer construct needs sharper task boundaries (§V).** A second edit on another line and low affected-set overlap establish a kind of near transfer, not conceptual or delayed transfer. Specify the exact primary contrast, scoring key, time allowance and any learning effects across functions. Item dependence matters when two questions come from the same function and share treatment material.
4. **Calibration requires a clear response interpretation.** Confidence in a free-form answer needs to map to the probability that that answer is correct. Explain why the confidence scale starts at 50%, how Brier scores are calculated for wrong answers, and whether low-confidence responses are artificially truncated. Preregister exclusions, missing responses and multiplicity across H2/H3.

### Questions and improvements

Does an executable predicate impose more reading difficulty than matched descriptive prose? Are word count and study time sufficient to match information content? Can students understand both the predicate language and the maintenance task? These are empirical design questions, not reasons to fabricate or rush participants.

### Recommendation

**Borderline, 3/5.** The human agenda is promising but immature. Acceptance could rest on the offline primitive; the paper must not borrow evidential strength from the planned study.

## Review 4 — Artifact, reproducibility and writing

### Summary and strengths

The artifact separates mutation, execution, explanation, predicate checking and analysis. The manuscript discloses lenient witness parsing, finite-test equivalence, failed LLM judges and assistant-only qualitative labels. Cached outputs and generated tables support inspection. The current PDF has four main-text pages and a fifth reference page; the inspected page 4 has no obvious clipping.

### Major concerns

1. **“Certification” should expose exactly what the executable oracle checks (§III).** List/tuple equality, numeric tolerance, exception-type equality and ignored exception messages define a task-specific observational relation. They do not preserve every observable behavior relevant to maintenance. Give a small example of an intentionally ignored difference and label the relation as the evaluation contract.
2. **The headline qualitative labels need verification before the submission decision.** Deferring hosted-predicate relabeling until camera-ready leaves part of the contribution unvalidated during review. This is distinct from the executable exactness result, which can stand independently. Either verify the labels now or demote their interpretation to tentative analysis.
3. **Runtime isolation is described inconsistently (§III).** The paper accurately states that `python -I` plus limits is not a filesystem/network sandbox, but subsequently says predicates run in “the same sandbox.” Call it the same isolated runner. For a released package that executes generated code, document the intended containment and trust assumptions without implying stronger protection than implemented.
4. **The prose contains several absolute mechanism claims.** “Grounding helps only by copying” is stronger than “the raw witness advantage largely disappears when copies count as failures.” “Humans have not memorised the originals” should become a conditional assumption about recruited participants, supported by screening, rather than an asserted fact.

### Questions and improvements

Will the anonymous package contain all cached responses and exact model/request provenance? The current README reports prior successful cache replay; that is useful evidence, but this review did not independently rerun it. Streamline Table II's denominators and state explicitly that genuine-only U and G groups are not the same subset and should not be read as a clean paired treatment contrast.

### Recommendation

**Borderline, 3/5; confidence 3/5.** The artifact looks inspectable and numbers agree, but the pending coding validation and broad interpretive wording matter more than additional cosmetic polish.

## Numerical spot-check

Current PDF/generated values agree with stored `artifact/results/summary.json` after rounding. These are consistency checks, not fresh executions.

| Claim/location | Stored evidence | Result |
| --- | --- | --- |
| 176 attempted functions, §IV | `n_functions_attempted = 176` | Match |
| 129 retained mutants, abstract/§IV | `n_mutants = 129` | Match |
| Hosted predicate subset 72, Table II | `pred_strong_n = 72` | Match |
| 68 exact ungrounded hosted predicates | `pred_strong_u_exact_n = 68` | Match |
| 33 genuine hosted U predicates; 31 exact | `pred_strong_u_lab_genuine = 33`; `...genuine_exact_n = 31` | Match; labels unvalidated |
| 46% of exact hosted U predicates genuine | `pred_strong_u_exact_genuine_share = .455882` | Match as a label-based fraction |
| Local witness error 71.3% U / 44.2% G | `wit_gen_raw_a = .713178`; `...b = .441860` | Match |
| Local copies-as-error 70.5% G | `wit_gen_strict_b = .705426` | Match |
| Descriptive 77.5% / counterfactual 48.1% | `probe_p14s_DESC = .775194`; `...CF = .480620` | Match |
| Median differing fraction about 91% | `median_differing_fraction = .909910` | Match |
| Five certified/genuine eligible functions | `n_eligible_certified_genuine = 5` | Match; three after overlap cap is a further filter |

## Related-work, baseline and theory audit

Eight targeted primary records were checked. Existing citations deserve credit; suggested comparisons do not imply every cited system must be reproduced.

| Source | Why it matters and next action |
| --- | --- |
| [Executable Counterfactuals](https://arxiv.org/abs/2510.01539) | Preserve the distinction between interventional tasks and latent-state counterfactual reasoning. |
| [WatChat](https://arxiv.org/abs/2403.05334) | The closest human-facing conceptual neighbor; narrow comparison to the exact executable-output and transfer components rather than broad absence-of-evaluation claims. |
| [Khatib et al.](https://arxiv.org/abs/2602.17838) | Mutation-based summary fidelity already exists; emphasize affected predicates and novel-witness auditing. |
| [CRUXEval](https://arxiv.org/abs/2401.03065) | Output prediction is an established model task; explain why the model probe adds to execution-tracing evaluation. |
| [Yang et al., generalization in code reasoning](https://arxiv.org/abs/2504.05518) | Grounds reversion and contamination concerns; use it to motivate fresh tasks rather than infer human performance. |
| [EvalPlus](https://arxiv.org/abs/2305.01210) | Richer test suites strengthen finite-test evidence but do not establish universal equivalence. |
| [nl2postcond](https://arxiv.org/abs/2310.01831) | Generated executable specifications are an adjacent methodology; compare correctness and discriminative power to predicate exactness. |
| [Kaufman et al., judging generated assertions](https://arxiv.org/abs/2607.08885) | Motivates separate correctness and calibration outcomes; does not supply evidence that this treatment improves either. |

Baseline opportunities: a deterministic edit-plus-witness template, the already included constant affected predicate, simple guard transcriptions, and restricted differential symbolic analysis. The latter is already discussed in the manuscript; these are design comparisons to prioritize by scope, not asserted missing citations. Treat paired semantic correctness, explanation readability and transfer as separate constructs.

## Meta-review

**Scores:** 4, 3, 3, 3. **Decision: borderline; revise before submission.** Meta-review confidence: **4/5**.

The favorable reviewer values the executable primitive and the distinction between copied evidence and independent articulation. The other reviewers agree that the offline work is substantial, but do not yet accept the stronger interpretation of “genuine” characterization or the feasibility of the transfer agenda. The central disagreement is whether the bounded offline contribution is sufficiently distinct from mutation analysis and executable specifications. A clearer comparison and validated qualitative labels would resolve more of that disagreement than a hurried user study.

This decision is not a demand for completed H2/H3 results. The paper can stand as an ERA reliability study if it explicitly certifies only witness/predicate components on T, avoids claiming that copying is the sole causal mechanism, and presents the human material shortage candidly. The observed hosted-model success is valuable even if it undermines the motivating H0.

**Subjective acceptance calibration:** **40–60%** now, conditional on normal submission compliance; **55–75%** after independent predicate-form checking, sharper novelty/claim boundaries and a credible material-expansion plan. Confidence **2/5** in these bands; they are author-feedback judgments, not statistical predictions.

## Prioritized revision checklist

### P0 — Central interpretation

- [ ] Independently relabel the headline hosted predicates with a written rubric and disagreement record; otherwise report “labeled genuine” and remove semantic lower-bound claims.
- [ ] State that only the witness and predicate on T are checked; explicitly separate unchecked prose d from certified components.
- [ ] Replace “grounding helps only by copying” with the narrower supported witness comparison; distinguish practical correctness from novel-witness generation.
- [ ] Add a concise novelty comparison covering mutation evaluation, executable specifications, WatChat and Executable Counterfactuals.

### P1 — Evaluation and agenda

- [ ] Surface the existing unshown-input sensitivity result and report mixed affected/unaffected and non-degenerate subsets.
- [ ] Include a deterministic explanation baseline or clearly justify leaving that comparison to follow-up work.
- [ ] Describe a frozen material-expansion/fallback rule for the three currently qualifying transfer functions; separate generated and author-rewritten material.
- [ ] Treat model-based power inputs as scenarios; plan a human feasibility check before confirmatory recruitment.
- [ ] Define confidence scoring, low-confidence answers, missing data and multiplicity for H2/H3.
- [ ] Report the consequences of observational equivalence choices and keep the claim restricted to T.

### P2 — Packaging and clarity

- [ ] Replace the inconsistent “sandbox” wording with the runner's actual properties.
- [ ] Clarify Table II denominators and nonpaired genuine-only subsets.
- [ ] Replace the artifact placeholder with a working anonymous package including cache/model provenance.
- [ ] Recheck final page boundaries, bibliography metadata and absence of unresolved references after edits.

## Reviewed snapshot

SHA-256 fingerprints identify the inputs reviewed; later manuscript changes require a new check. The source-bundle hash concatenates each relative path, a NUL byte, file bytes and a NUL byte in the order stated above.

| Input | SHA-256 |
| --- | --- |
| manuscript/main.pdf | `c9d23fbe29e8b337012e93f26c5b47f9bc3f354b7a7837c5bd6cbd2c1a78bfd8` |
| artifact/results/summary.json | `a7f4b9039b21390360c9aa36e14a24899f28953736b02f8eedc4c97695e32f59` |
| manuscript source bundle (main, sorted sections, sorted generated, bibliography) | `7ba421d55aae57b45521bfb56a712117211a0c6d75e926eabeda1aefbd84bc4e` |

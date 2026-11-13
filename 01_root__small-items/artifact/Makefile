# E02 Counterfactual Comprehension -- reproducible artifact
# Usage: make all   (data -> run -> render -> pdf). LLM responses are cached under results/llm_cache/,
# so `make all` replays deterministically without a model server once the cache is populated.
PY      ?= python3   # Python 3.13 with requirements.txt (e.g. PY=../.venv/bin/python)
# never write __pycache__ (compiled files embed absolute paths, which would break anonymity)
export PYTHONDONTWRITEBYTECODE = 1
SRC      = src
RES      = results
MS       = $(CURDIR)/../manuscript
GEN      = qwen2.5-coder:14b
STRONG   = claude-haiku-5-5
PROBE2   = qwen2.5-coder:7b-instruct-q8_0

.PHONY: all data mutants run explain check probe analyze render pdf clean clean-all

all: data run render pdf

data: data/corpus.jsonl
data/corpus.jsonl:
	$(PY) $(SRC)/data.py

mutants: $(RES)/mutants.jsonl
$(RES)/mutants.jsonl: data/corpus.jsonl
	$(PY) $(SRC)/build_mutants.py

explain: $(RES)/mutants.jsonl
	$(PY) $(SRC)/explain.py --model $(GEN)
	$(PY) $(SRC)/explain.py --model $(STRONG)

check: explain
	$(PY) $(SRC)/check.py --explanations explanations_qwen2.5-coder_14b.jsonl
	$(PY) $(SRC)/check.py --explanations explanations_claude-haiku-5-5.jsonl --judges llama3.1:8b

predicates: $(RES)/mutants.jsonl
	$(PY) $(SRC)/predicate.py --model $(GEN)
	$(PY) $(SRC)/predicate.py --model $(STRONG)

probe: $(RES)/mutants.jsonl
	$(PY) $(SRC)/probe.py --model $(GEN) --kinds DESC,CF,DESC_MUT
	$(PY) $(SRC)/probe.py --model $(PROBE2) --kinds DESC,CF
	$(PY) $(SRC)/probe.py --model $(GEN) --variant stripped --kinds DESC,CF,CF_CTRL,DESC_MUT
	$(PY) $(SRC)/probe.py --model $(PROBE2) --variant stripped --kinds DESC,CF,CF_CTRL,DESC_MUT

heldout: $(RES)/mutants.jsonl
	$(PY) $(SRC)/build_heldout.py

analyze:
	$(PY) $(SRC)/analyze.py

run: mutants check predicates probe heldout analyze

render:
	$(PY) $(SRC)/render.py

# Build-verify with pgfplots compat=1.17 (TeX Live 2020 on this machine); the shipped source keeps 1.18.
pdf:
	cd $(MS) && rm -rf build && mkdir -p build && cp -r main.tex references.bib sections generated figures build/ \
	&& sed -i.bak 's/compat=1.18/compat=1.17/' build/main.tex \
	&& cd build && pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null \
	&& bibtex main >/dev/null && pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null \
	&& pdflatex -interaction=nonstopmode -halt-on-error main.tex | grep -E "Output written|^!" ; \
	cp $(MS)/build/main.pdf $(MS)/main.pdf && grep -c "undefined" $(MS)/build/main.log || true

clean:
	rm -rf $(MS)/build $(RES)/*.csv $(RES)/summary.json $(MS)/generated/*.tex $(SRC)/__pycache__

clean-all: clean
	rm -rf data/corpus.jsonl data/corpus_dropped.json $(RES)/mutants.jsonl $(RES)/mutation_stats.json \
	       $(RES)/explanations_*.jsonl $(RES)/scores_*.jsonl $(RES)/probe_*.jsonl \
	       $(RES)/predicates_*.jsonl $(RES)/heldout_mutants.jsonl

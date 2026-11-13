"""Shared configuration, deterministic LLM access with on-disk cache, safe literal parsing,
and tolerant output comparison for the counterfactual-explanation pipeline."""
import ast
import hashlib
import json
import math
import os
import time
import urllib.request

SEED = 20261109
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # artifact/
DATA = os.path.join(ROOT, "data")
RESULTS = os.path.join(ROOT, "results")
CACHE = os.path.join(RESULTS, "llm_cache")
GENERATED = os.path.join(os.path.dirname(ROOT), "manuscript", "generated")
os.makedirs(CACHE, exist_ok=True)

# Corpus / mutation settings
N_PER_SOURCE = 88              # functions sampled per benchmark (HumanEval+, MBPP+)
MAX_INPUTS = 120               # test inputs executed per function (base first, then seeded sample)
PER_INPUT_TIMEOUT = 2.0        # seconds, inside the sandbox
PROCESS_TIMEOUT = 90           # seconds, whole sandbox process
MAX_CANDIDATES_TRIED = 12      # mutant candidates tried per function before giving up

# Models (exact tags recorded in summary.json)
GEN_MODEL = "qwen2.5-coder:14b"
STRONG_MODEL = "claude-haiku-5-5"       # hosted-model condition (403 calls in total; default sampling)
JUDGE_MODELS = ["llama3.1:8b", "gemma2:9b"]
PROBE_MODELS = ["qwen2.5-coder:14b", "qwen2.5-coder:7b-instruct-q8_0"]
OLLAMA_URL = "http://localhost:11434/api/generate"


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def cache_key(model, seed, system, prompt):
    return hashlib.sha256(f"{model}|{seed}|{system}|{prompt}".encode()).hexdigest()[:32]


def llm(prompt, model=GEN_MODEL, system=None, num_predict=600, seed=SEED, timeout=300):
    """Call a local Ollama model (temperature 0, fixed seed) or an Anthropic model (default sampling; the client accepts
    no temperature for it), cached on disk keyed by model+seed+system+prompt. Replays identically from the cache."""
    key = cache_key(model, seed, system, prompt)
    path = os.path.join(CACHE, key + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)["response"]
    if model.startswith("claude-"):
        text = _anthropic(prompt, model, system, num_predict)
        rec = {"model": model, "seed": seed, "system": system, "prompt": prompt, "response": text,
               "backend": "anthropic", "ts": time.time()}
    else:
        body = {"model": model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0, "seed": seed, "num_predict": num_predict}}
        if system:
            body["system"] = system
        req = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        for attempt in range(4):   # shared server: retry a stalled request (response is deterministic)
            try:
                resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(10)
        rec = {"model": model, "seed": seed, "system": system, "prompt": prompt,
               "response": resp["response"], "backend": "ollama",
               "eval_count": resp.get("eval_count"), "total_duration": resp.get("total_duration"),
               "ts": time.time()}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f)
    os.replace(tmp, path)
    return rec["response"]


def _anthropic(prompt, model, system, max_tokens):
    import anthropic  # installed in the shared venv
    client = anthropic.Anthropic()
    # Claude Haiku 5.5 rejects non-default sampling parameters; determinism comes from the on-disk cache.
    kwargs = dict(model=model, max_tokens=max(max_tokens, 4000),
                  messages=[{"role": "user", "content": prompt}])
    if system:
        kwargs["system"] = system
    for attempt in range(5):
        try:
            msg = client.messages.create(**kwargs)
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        except Exception as e:  # rate limit / transient
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def extract_json(text):
    """Pull the first JSON object out of a model response (tolerates ``` fences and prose)."""
    if text is None:
        return None
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        for p in parts[1::2]:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            try:
                return json.loads(p)
            except Exception:
                pass
    start = t.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    chunk = t[start:i + 1]
                    try:
                        return json.loads(chunk)
                    except Exception:
                        try:
                            return json.loads(chunk.replace("'", '"'))
                        except Exception:
                            break
        start = t.find("{", start + 1)
    return None


# ---------------------------------------------------------------------------------------------
# Safe literal evaluation (inputs are downloaded data: only literals, containers, inf/nan allowed)
# ---------------------------------------------------------------------------------------------
_ALLOWED_NAMES = {"inf": math.inf, "nan": math.nan, "True": True, "False": False, "None": None}


def safe_literal(src):
    tree = ast.parse(src.strip(), mode="eval")

    def ev(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in _ALLOWED_NAMES:
            return _ALLOWED_NAMES[node.id]
        if isinstance(node, ast.Attribute):  # e.g. math.inf
            if node.attr in ("inf", "nan"):
                return _ALLOWED_NAMES[node.attr]
            raise ValueError("attribute")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)) and \
                isinstance(node.right, ast.Constant) and isinstance(node.right.value, complex):
            l = ev(node.left)
            return l + node.right.value if isinstance(node.op, ast.Add) else l - node.right.value
        if isinstance(node, ast.List):
            return [ev(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(ev(e) for e in node.elts)
        if isinstance(node, ast.Set):
            return set(ev(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return {ev(k): ev(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                node.func.id in ("set", "frozenset", "tuple", "list", "dict") and len(node.args) <= 1:
            arg = ev(node.args[0]) if node.args else []
            return {"set": set, "frozenset": frozenset, "tuple": tuple, "list": list, "dict": dict}[node.func.id](arg)
        raise ValueError(f"disallowed node {type(node).__name__}")

    return ev(tree.body)


def try_literal(s):
    try:
        return True, safe_literal(s)
    except Exception:
        return False, None


# ---------------------------------------------------------------------------------------------
# Tolerant comparison of execution outcomes
# ---------------------------------------------------------------------------------------------
def _close(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        try:
            if math.isnan(a) and math.isnan(b):
                return True
            return math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-6)
        except OverflowError:
            return a == b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, (set, frozenset)) and isinstance(b, (set, frozenset)):
        return a == b
    return a == b


def outcomes_equal(o1, o2, set_compare=False):
    """o = {"ok": bool, "repr": str} or {"ok": False, "exc": str}."""
    if o1.get("ok") != o2.get("ok"):
        return False
    if not o1.get("ok"):
        return o1.get("exc") == o2.get("exc")
    r1, r2 = o1.get("repr"), o2.get("repr")
    if r1 == r2:
        return True
    ok1, v1 = try_literal(r1)
    ok2, v2 = try_literal(r2)
    if ok1 and ok2:
        if set_compare:
            try:
                return set(v1) == set(v2)
            except TypeError:
                pass
        return _close(v1, v2)
    return False


def outcome_str(o, maxlen=120):
    if o.get("ok"):
        s = o["repr"]
    else:
        s = f"raises {o.get('exc')}"
    return s if len(s) <= maxlen else s[:maxlen - 3] + "..."


def short_repr(x, maxlen=100):
    s = repr(x)
    return s if len(s) <= maxlen else s[:maxlen - 3] + "..."

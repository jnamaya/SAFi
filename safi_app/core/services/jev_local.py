"""Local typed decisions on the appliance: Laya as a drop-in for Jev's system_one.

SAFi's Conscience has two transports for one typed-decision contract. A hosted
install calls TypeSafe Jev over HTTPS at /v1/systemone. An appliance cannot: the
ISO is a public artefact, so there is no Jev API key to ship in it, and an
operator with no internet has nowhere to send the audit. Laya
(https://github.com/receptron/laya) is an open-source, MIT/Apache-2.0
reimplementation of that exact API — its TypeScript types say so, and it
reproduces the reference implementation to four decimal places — so the appliance
can serve the identical contract from a pinned ONNX bundle with no outbound call
and no credential.

In-process rather than a sidecar HTTP service: onnxruntime is already a
dependency (fastembed runs the MiniLM embedder through it, see requirements.txt),
so Laya needs no new package, no Node runtime, no systemd unit and no listening
port. It is not a dependency of the hosted path either — nothing here imports
until is_available() finds a bundle, and Config.LOCAL_JEV_PATH is empty
everywhere except an appliance that fetched one.

The model is a bidirectional encoder with a decision head, not a language model,
so it answers typed questions and writes no prose. That is exactly the role typed
Conscience already has — LLMProvider's docstring notes Jev "does not generate
evidence prose" — so Intellect still does the writing and nothing is lost.

Tokenisation is reproduced from the reference implementation (rl_common.py) rather
than re-derived, because the encoder is trained on that exact byte stream: a
single differing space or truncation rule shifts every probability. State is
truncated from the front after the question header, so callers should put what
matters most first.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Question type ids, in the order the reference implementation uses to index both
# the fitted temperatures and the model's type embedding.
QTYPES = {"choice": 0, "score": 1, "noul": 2}
QTYPE_NAMES = {v: k for k, v in QTYPES.items()}

# The five files export/export_onnx.py emits. Presence and size are the
# availability test; the digest is verified at fetch time by safi-model-fetch,
# the same boundary the GGUF models use (see installed_model_path there: a size
# check at activation, a hash at download). Re-hashing 1.7 GB per request would
# stall a governance turn, and re-hashing it per worker start would not improve
# on a fetch that already refused to install an unverified artefact.
#
# Default install location, matching the catalogue's model_root and the id of its
# jev_local block. Derived from one convention rather than hardcoded in .env
# because the ISO has two independent writers (safi-model-fetch and the setup
# wizard) that do not coordinate; the env var still wins, for a non-standard
# install or a test.
DEFAULT_BUNDLE_PATH = "/var/lib/safi/models/laya"
BUNDLE_ENV_VAR = "SAFI_LOCAL_JEV_PATH"

BUNDLE_FILES = (
    "laya.onnx",
    "laya.onnx.data",
    "laya_config.json",
    os.path.join("tokenizer", "tokenizer.json"),
    os.path.join("tokenizer", "tokenizer_config.json"),
)

_lock = threading.Lock()
_session: Any = None
_tokenizer: Any = None
_config: Optional[Dict[str, Any]] = None


class LocalJevUnavailable(RuntimeError):
    """No verified local bundle is installed, so typed decisions must go remote."""


def bundle_dir() -> Optional[str]:
    """The bundle directory to use, or None when local Jev is switched off.

    Presence in the environment is the switch, not the value. If
    SAFI_LOCAL_JEV_PATH is set at all, it is authoritative and an empty value
    means off -- that is how an operator forces Conscience back onto the hosted
    provider to compare the two without deleting a 1.7 GB bundle. If the
    variable is absent, the default location is probed, so a stock appliance
    needs no .env entry (the key is deliberately not in .env.example) and a
    hosted install finds nothing there and is unaffected.

    Config is not consulted: it resolves every variable to a string, so it
    cannot distinguish "absent" from "set to empty", and that distinction is
    exactly what this needs.
    """
    if BUNDLE_ENV_VAR in os.environ:
        return os.environ[BUNDLE_ENV_VAR].strip() or None
    if os.path.isdir(DEFAULT_BUNDLE_PATH):
        return DEFAULT_BUNDLE_PATH
    return None


def is_available() -> bool:
    """Whether a complete local bundle is present. Cheap: stat calls, no load."""
    root = bundle_dir()
    if not root:
        return False
    return all(os.path.isfile(os.path.join(root, name)) for name in BUNDLE_FILES)


def invalidate() -> None:
    """Drop the cached session so a replaced bundle is picked up.

    Called by the appliance after a fetch installs a new one; the model cache in
    model_routing does not need it because availability is a filesystem question.
    """
    global _session, _tokenizer, _config
    with _lock:
        _session = _tokenizer = _config = None


def _load():
    """Build the tokenizer, config and inference session once per process."""
    global _session, _tokenizer, _config
    if _session is not None:
        return _session, _tokenizer, _config
    with _lock:
        if _session is not None:
            return _session, _tokenizer, _config
        root = bundle_dir()
        if not root or not is_available():
            raise LocalJevUnavailable("no local Jev bundle is installed")
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:  # pragma: no cover - onnxruntime ships via fastembed
            raise LocalJevUnavailable(f"onnxruntime/tokenizers unavailable: {exc}") from exc

        with open(os.path.join(root, "laya_config.json"), encoding="utf-8") as handle:
            config = json.load(handle)
        tokenizer = Tokenizer.from_file(os.path.join(root, "tokenizer", "tokenizer.json"))
        options = ort.SessionOptions()
        # One audit is a handful of short questions; intra-op parallelism across all
        # cores wins there, and a spinning server is the wrong trade on an appliance
        # that is also running the chat model.
        options.intra_op_num_threads = max(1, os.cpu_count() or 1)
        options.log_severity_level = 3
        session = ort.InferenceSession(
            os.path.join(root, "laya.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        _session, _tokenizer, _config = session, tokenizer, config
        logger.info("local Jev bundle loaded from %s", root)
        return _session, _tokenizer, _config


# --------------------------------------------------------------------------
# tokenisation, reproduced from the reference implementation
# --------------------------------------------------------------------------

def _special_id(tokenizer, token: str) -> int:
    value = tokenizer.token_to_id(token)
    if value is None:
        raise LocalJevUnavailable(f"tokenizer is missing the {token} token")
    return value


def _encode(tokenizer, text: str) -> List[int]:
    return tokenizer.encode(text, add_special_tokens=False).ids


# The state keys a Conscience audit is about, most important first. Typed
# Conscience is asked to grade the turn's final_output against the rubric, so
# that text is the evidence; anything earlier in the dict is context. See
# _prioritized_state for why ordering decides what survives the token budget.
_PRIORITY_STATE_KEYS = ("final_output", "response", "output", "answer")

_ALL_OTHER_KEYS_LAST = object()


def _serialize_state(state: Any) -> str:
    """The reference implementation's state serialisation, byte for byte.

    json.dumps with ensure_ascii=False, not the ONNX exporter's JS approximation, so
    the token stream matches the Python reference the encoder was trained against.
    """
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)


def _prioritized_state(state: Any) -> Any:
    """Reorder a dict state so the audited output survives truncation.

    Laya sees a 512-token window and the head question already spends ~192, so a
    verbose state is clipped. Plain truncation keeps the *head* of the JSON and
    drops the tail — and SAFi builds state with final_output last, so a long
    session was silently graded on conversation history with the answer cut off.
    Worse than useless: the model returns a confident score about text it never
    saw, and the ledger records it as an audit.

    Reordering is applied only when the state does not already fit. A state short
    enough for the window stays byte-identical to the reference serialisation, so
    the common case keeps matching the encoder's training distribution exactly.
    """
    if not isinstance(state, dict):
        return state
    priority: List[Tuple[str, Any]] = []
    others: List[Tuple[str, Any]] = []
    for key, value in state.items():
        name = str(key)
        if name in _PRIORITY_STATE_KEYS and name not in {k for k, _ in priority}:
            priority.append((name, value))
        else:
            others.append((name, value))
    if not priority or not others:
        return state
    return dict(priority + others)


def _option_text(name: str, value: Any) -> str:
    """Render one choice option as text, structured values as prose.

    SAFI passes each option as {"score", "label", "description"} (see
    LLMProvider.run_conscience_structured). Interpolating that dict directly
    yields "level_2: {'score': 5.0, 'label': 'Clear', ...}", which spends the
    option's 48-token budget on punctuation and truncation can cut the label off
    the end — the model then judges an option it has only seen a fragment of.
    The score is dropped because it is the answer, not evidence: showing the
    model its own numeric rubric invites ordering bias rather than a judgement.
    """
    if not value:
        return name
    if isinstance(value, dict):
        label = str(value.get("label") or "").strip()
        description = str(value.get("description") or "").strip()
        text = f"{label} - {description}" if label and description else label or description
        return f"{name}: {text}" if text else name
    return f"{name}: {value}"


def _render_options(question: Dict[str, Any]) -> List[str]:
    """Option texts in label-index order; noul is always [false, true]."""
    kind = question.get("type")
    criteria = question.get("criteria")
    if kind == "choice":
        if isinstance(criteria, list):
            criteria = {name: None for name in criteria}
        criteria = criteria or {}
        return [_option_text(name, value) for name, value in criteria.items()]
    if kind == "score":
        return [f"level {index}: {text}" for index, text in enumerate(criteria or [])]
    criteria = criteria or {}
    return [
        "false: " + (criteria.get("false") or "no, the statement does not hold"),
        "true: " + (criteria.get("true") or "yes, the statement holds"),
    ]


def _build_sequence(
    tokenizer,
    state: Any,
    question: Dict[str, Any],
    max_len: int,
    head_max_len: int,
) -> Tuple[List[int], List[int]]:
    """[CLS] <type> question: instructions [SEP] [MASK] opt0 [MASK] opt1 ... [SEP] state [SEP].

    Returns the ids and the position of each option's [MASK]. The masks are what the
    head scores, so their positions are the model's answer slots.
    """
    mask_id = _special_id(tokenizer, "[MASK]")
    mask_tok = "[MASK]"
    options = _render_options(question)
    instructions = question.get("instructions")
    if not isinstance(instructions, str):
        instructions = json.dumps(instructions)
    instructions = str(instructions).replace(mask_tok, " ")

    head_ids = _encode(tokenizer, f"{question.get('type')} question: {instructions}")
    opt_ids = [[mask_id] + _encode(tokenizer, " " + options[i].replace(mask_tok, " "))[:48]
               for i in range(len(options))]

    def total(groups: List[List[int]]) -> int:
        return sum(len(group) for group in groups)

    opt_budget = head_max_len - total(opt_ids)
    if opt_budget < 16:
        # Too many or too long options: shrink every option text evenly rather than
        # dropping options, so the answer space stays the full rubric.
        per = max(4, (head_max_len - 16) // max(1, len(opt_ids)))
        opt_ids = [group[:per] for group in opt_ids]
        opt_budget = head_max_len - total(opt_ids)
    head_ids = head_ids[:max(8, opt_budget)]

    ids = [_special_id(tokenizer, "[CLS]")] + head_ids + [_special_id(tokenizer, "[SEP]")]
    markers: List[int] = []
    for group in opt_ids:
        markers.append(len(ids))
        ids.extend(group)
    ids.append(_special_id(tokenizer, "[SEP]"))

    room = max(0, max_len - len(ids) - 1)
    text = _serialize_state(state)
    state_ids = _encode(tokenizer, text.replace(mask_tok, " "))
    if len(state_ids) > room:
        # Reorder and retry, rather than shipping a window that lost the answer.
        reordered = _encode(
            tokenizer,
            _serialize_state(_prioritized_state(state)).replace(mask_tok, " "),
        )
        if len(reordered) <= len(state_ids):
            state_ids = reordered
    ids = ids + state_ids[:room] + [_special_id(tokenizer, "[SEP]")]
    return ids[:max_len], [marker for marker in markers if marker < max_len]


def _temperature_bucket(qtype: int, options: int) -> str:
    """Per-cardinality temperature key; a 2-option noul and a 12-option choice differ."""
    size = "2" if options <= 2 else "3-5" if options <= 5 else "6-10" if options <= 10 else "11+"
    return f"{QTYPE_NAMES[int(qtype)]}:{size}"


def _confidence(probabilities, options: int) -> float:
    """Jev-style confidence: 1 - normalised entropy of the answer distribution."""
    if options < 2:
        return 1.0
    entropy = -sum(p * math.log(max(p, 1e-12)) for p in probabilities[:options])
    return float(1 - entropy / math.log(options))


def _softmax(values) -> list:
    import numpy as np
    array = np.asarray(values, dtype="float64")
    if array.size == 0:
        return []
    array = array - array.max()
    exponentials = np.exp(array)
    total = exponentials.sum()
    return (exponentials / total).tolist() if total > 0 else (1.0 / array.size,) * array.size


# --------------------------------------------------------------------------
# the system_one contract
# --------------------------------------------------------------------------

def system_one(state: Any, questions: Dict[str, Any]) -> Dict[str, Any]:
    """Answer every typed question about one state in a single forward pass.

    Mirrors TypeSafe Jev's system_one: {id: {type, instructions, criteria}} in,
    {id: {type, choice|score|noul, probabilities, confidence}} out. SAFi's typed
    Conscience only asks 'choice' questions; all three are implemented so this
    stays a substitutable implementation of the documented API rather than a
    Conscience-shaped special case.
    """
    import numpy as np

    if not questions:
        return {"model": "laya", "answers": {}, "usage": {"input_tokens": 0, "output_tokens": 0}}

    session, tokenizer, config = _load()
    max_len = int(config.get("max_len", 512))
    head_max_len = int(config.get("head_max_len", 192))
    pad_id = _special_id(tokenizer, "[PAD]")

    ids = list(questions.keys())
    items = []
    for qid in ids:
        question = questions[qid]
        if question.get("type") not in QTYPES:
            raise ValueError(f"unknown question type {question.get('type')!r} for {qid!r}")
        sequence, markers = _build_sequence(tokenizer, state, question, max_len, head_max_len)
        if len(markers) != len(_render_options(question)):
            raise ValueError(
                f"question {qid!r}: options do not fit in head_max_len={head_max_len} tokens"
            )
        items.append({"ids": sequence, "markers": markers, "qtype": QTYPES[question["type"]]})

    width = max(len(item["ids"]) for item in items)
    slots = max(len(item["markers"]) for item in items)
    input_ids = np.full((len(items), width), pad_id, dtype=np.int64)
    attention = np.zeros((len(items), width), dtype=np.int64)
    marker_pos = np.zeros((len(items), slots), dtype=np.int64)
    marker_mask = np.zeros((len(items), slots), dtype=bool)
    qtype = np.zeros(len(items), dtype=np.int64)
    for row, item in enumerate(items):
        input_ids[row, : len(item["ids"])] = item["ids"]
        attention[row, : len(item["ids"])] = 1
        marker_pos[row, : len(item["markers"])] = item["markers"]
        marker_mask[row, : len(item["markers"])] = True
        qtype[row] = item["qtype"]

    logits, act = session.run(
        ["logits", "act_probs"],
        {
            "input_ids": input_ids,
            "attention_mask": attention,
            "marker_pos": marker_pos,
            "marker_mask": marker_mask,
            "qtype": qtype,
        },
    )
    # act_probs is already a probability, not a logit: the graph applies its own
    # softmax, so re-softmaxing here would rescale a ~0 logit into ~0.5.
    act_probability = float(act[0][0]) if act is not None and len(act) else 0.0

    temperatures = config.get("temperature", [1.0, 1.0, 1.0])
    by_cardinality = config.get("temperature_by_options", {}) or {}

    answers: Dict[str, Any] = {}
    for row, qid in enumerate(ids):
        question = questions[qid]
        kind = question["type"]
        count = len(items[row]["markers"])
        bucket = _temperature_bucket(items[row]["qtype"], count)
        temperature = by_cardinality.get(bucket) or temperatures[items[row]["qtype"]] or 1.0
        probabilities = _softmax(logits[row, :count] / temperature)
        extra = {"act_probability": act_probability}
        if kind == "choice":
            keys = list((question.get("criteria") or {}).keys())
            if isinstance(question.get("criteria"), list):
                keys = list(question["criteria"])
            answers[qid] = {
                "type": "choice",
                "choice": keys[max(range(count), key=probabilities.__getitem__)],
                "probabilities": {key: round(value, 4) for key, value in zip(keys, probabilities)},
                "confidence": round(_confidence(probabilities, count), 4),
                "rl_agent": extra,
            }
        elif kind == "score":
            criteria = question.get("criteria") or []
            answers[qid] = {
                "type": "score",
                "score": round(sum(i * p for i, p in enumerate(probabilities)), 4),
                "legend": {str(i): text for i, text in enumerate(criteria)},
                "probabilities": {str(i): round(p, 4) for i, p in enumerate(probabilities)},
                "confidence": round(_confidence(probabilities, count), 4),
                "rl_agent": extra,
            }
        else:
            answers[qid] = {
                "type": "noul",
                "noul": round(probabilities[1] if count > 1 else 0.0, 4),
                "rl_agent": extra,
            }

    return {
        "model": "laya",
        "answers": answers,
        "usage": {"input_tokens": int(attention.sum()), "output_tokens": 0},
    }

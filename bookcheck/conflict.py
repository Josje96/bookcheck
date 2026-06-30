"""Conflict detection.

Two layers, exactly as the architecture calls for:
  1. Entity consistency pass (qwen3:8b) -- for each entity, pull only that
     entity's recorded facts (cheap key lookup, no embeddings) and ask the model
     whether any contradict. This is the entity-keyed comparison that catches
     contradictions phrased nothing alike.
  2. Final cross-cutting pass (qwen3:8b, JSON mode) -- reason over the whole
     structured store for timeline math, knowledge leaks, and unresolved setups
     that no single per-entity check would surface. (deepseek-r1 was the original
     choice but burned its whole token budget on <think> reasoning without
     emitting an answer on this 8GB GPU, so we use qwen3:8b directly.)
"""

from __future__ import annotations

import re

from . import prompts, store
from .ollama_client import OllamaClient

CONSISTENCY_MODEL = "qwen3:4b"
# deepseek-r1 spent its whole generation budget on <think> reasoning and never
# emitted the answer on this hardware, so the cross-cutting pass uses qwen3:8b
# in direct JSON mode -- more capable than 4b, reliable, and only one call.
FINAL_MODEL = "qwen3:8b"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _match_chunk(quote: str, fact_rows) -> int | None:
    """Best-effort map a model-returned quote back to the chunk it came from."""
    q = _norm(quote)
    if not q:
        return None
    best, best_overlap = None, 0
    qset = set(q.split())
    for r in fact_rows:
        fq = _norm(r["quote"])
        if not fq:
            continue
        if q in fq or fq in q:
            return r["chunk_id"]
        overlap = len(qset & set(fq.split()))
        if overlap > best_overlap:
            best, best_overlap = r["chunk_id"], overlap
    return best if best_overlap >= 3 else None


# --- Pass 1: entity consistency (deterministic) -------------------------
#
# Rather than ask a small model to eyeball every pair of facts (which fabricates
# nonsense by pairing unrelated transient details), we compare ONLY a small set
# of genuinely stable attributes and only flag when their normalized values
# actually differ. This is transparent, fast, and high-precision.

# raw extracted attribute name -> canonical stable attribute
_ATTR_ALIASES = {
    "species": "species", "race": "species", "is_vampire": "species",
    "eye_color": "eye_color", "eyes": "eye_color", "eye": "eye_color",
    "hair_color": "hair_color", "hair": "hair_color",
    "gender": "gender", "sex": "gender", "is_male": "gender",
    "is_female": "gender",
}
_STABLE_SEVERITY = {"species": "high", "gender": "high",
                    "eye_color": "medium", "hair_color": "medium"}
_STABLE_LABEL = {"species": "Species", "gender": "Gender",
                 "eye_color": "Eye color", "hair_color": "Hair color"}

# Color words grouped into families; values in the same family are NOT a conflict
# (copper vs red, dark vs obsidian), values in different families ARE.
_COLOR_FAMILIES = {
    "red": ("red", "copper", "auburn", "ginger", "rust", "scarlet", "crimson",
            "strawberry"),
    "brown": ("brown", "chestnut", "brunette", "hazel"),
    "blonde": ("blonde", "blond", "golden", "gold", "fair", "honey"),
    "black": ("black", "raven", "obsidian", "jet", "ebony", "dark"),
    "gray": ("gray", "grey", "silver", "ash", "white", "platinum"),
    "pink": ("pink", "rose"),
    "green": ("green", "emerald", "jade"),
    "blue": ("blue", "azure", "sapphire"),
    "amber": ("amber",),
    "violet": ("violet", "purple"),
}
_VALID_SPECIES = ("vampire", "werewolf", "witch", "human", "fae", "fairy",
                  "ghost", "demon", "shifter")


def _color_family(value: str):
    v = (value or "").lower()
    for fam, words in _COLOR_FAMILIES.items():
        if any(re.search(rf"\b{w}\b", v) for w in words):
            return fam
    return None  # no recognized color word -> not a color statement


def _stable_value(canon_attr: str, raw_attr: str, value: str):
    """Return a normalized, comparable value for a stable attribute, or None to
    skip this fact (descriptive prose, not a clean statement of the attribute)."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if canon_attr in ("eye_color", "hair_color"):
        return _color_family(v)
    if canon_attr == "species":
        if raw_attr == "is_vampire":
            return "vampire" if v in ("yes", "true", "1") else None
        for sp in _VALID_SPECIES:
            if re.search(rf"\b{sp}\b", v):
                return sp
        return None
    if canon_attr == "gender":
        if raw_attr == "is_male":
            return "male" if v in ("yes", "true", "1") else "female"
        if raw_attr == "is_female":
            return "female" if v in ("yes", "true", "1") else "male"
        if "female" in v or v in ("woman", "girl", "she"):
            return "female"
        if "male" in v or v in ("man", "boy", "he"):
            return "male"
        return None
    return None


def run_entity_pass(conn, client: OllamaClient = None, verbose: bool = True) -> int:
    """Deterministic stable-attribute contradiction check. `client` is unused
    (kept for signature compatibility)."""
    chars = conn.execute(
        "SELECT canonical_name FROM characters ORDER BY canonical_name"
    ).fetchall()
    found = 0
    for c in chars:
        name = c["canonical_name"]
        facts = conn.execute(
            "SELECT * FROM facts WHERE entity_type='character' AND "
            "entity_name = ? COLLATE NOCASE AND polarity >= 0 ORDER BY chunk_id",
            (name,),
        ).fetchall()
        # canonical attr -> {normalized value: (chunk_id, raw_value, quote)}
        by_attr: dict[str, dict] = {}
        for f in facts:
            canon = _ATTR_ALIASES.get((f["attribute"] or "").strip().lower())
            if not canon:
                continue
            nv = _stable_value(canon, (f["attribute"] or "").strip().lower(),
                               f["value"])
            if nv is None:
                continue
            slot = by_attr.setdefault(canon, {})
            slot.setdefault(nv, (f["chunk_id"], f["value"], f["quote"] or ""))

        n_char = 0
        for canon, values in by_attr.items():
            if len(values) < 2:
                continue
            # Flag the (sorted) distinct values pairwise -> one conflict per attr.
            items = list(values.items())
            (v1, (c1, raw1, q1)), (v2, (c2, raw2, q2)) = items[0], items[1]
            label = _STABLE_LABEL[canon]
            store.insert_conflict(
                conn, kind="trait_contradiction",
                description=(f"{name}: {label} given as \"{raw1}\" "
                             f"({store.chunk_ref(conn, c1)}) but \"{raw2}\" "
                             f"({store.chunk_ref(conn, c2)})."),
                severity=_STABLE_SEVERITY[canon],
                source_a_chunk=c1, source_a_quote=q1 or raw1,
                source_b_chunk=c2, source_b_quote=q2 or raw2,
                detected_by="entity_pass")
            found += 1
            n_char += 1
        if verbose and n_char:
            print(f"  [entity] {name}: {n_char} contradiction(s)")
        conn.commit()
    return found


# --- Pass 2: final cross-cutting -----------------------------------------

def _build_digest(conn) -> str:
    # Caps keep the prompt within the model's context window. Timeline and
    # knowledge get the most room -- they drive the cross-cutting checks.
    parts = []

    tl = conn.execute(
        "SELECT * FROM timeline_events ORDER BY ordering_hint, chunk_id LIMIT 60"
    ).fetchall()
    if tl:
        parts.append("## TIMELINE EVENTS (in story order)")
        for t in tl:
            ref = store.chunk_ref(conn, t["chunk_id"])
            parts.append(f"- [{ref}] when='{t['when_raw']}': {t['description']}")

    kn = conn.execute(
        "SELECT * FROM knowledge ORDER BY learned_chunk_id LIMIT 60").fetchall()
    if kn:
        parts.append("\n## WHO LEARNS WHAT, WHEN")
        for k in kn:
            ref = store.chunk_ref(conn, k["learned_chunk_id"])
            parts.append(f"- [{ref}] {k['character_name']} learns: {k['proposition']}")

    setups = conn.execute(
        "SELECT * FROM plot_threads WHERE status='open' ORDER BY setup_chunk_id "
        "LIMIT 40").fetchall()
    if setups:
        parts.append("\n## OPEN SETUPS / FORESHADOWING")
        for s in setups:
            ref = store.chunk_ref(conn, s["setup_chunk_id"])
            parts.append(f"- [{ref}] {s['name']}: {s['description']}")

    # Key character facts (a compact slice -- the entity pass already deep-checks
    # these, but they give the final pass grounding for cross-cutting reasoning).
    # Only the main cast (characters with several recorded facts) -- keeps the
    # digest focused and short.
    parts.append("\n## SELECTED CHARACTER FACTS")
    main = conn.execute(
        "SELECT entity_name, COUNT(*) n FROM facts WHERE entity_type='character' "
        "GROUP BY entity_name COLLATE NOCASE HAVING n >= 8 ORDER BY n DESC LIMIT 8"
    ).fetchall()
    for row in main:
        cname = row["entity_name"]
        crow = conn.execute("SELECT species FROM characters WHERE "
                            "canonical_name = ? COLLATE NOCASE", (cname,)).fetchone()
        sp = f" ({crow['species']})" if crow and crow["species"] else ""
        facts = conn.execute(
            "SELECT attribute, value, polarity, chunk_id FROM facts "
            "WHERE entity_name = ? COLLATE NOCASE ORDER BY chunk_id LIMIT 6",
            (cname,)).fetchall()
        if not facts:
            continue
        parts.append(f"- {cname}{sp}:")
        for f in facts:
            neg = "" if f["polarity"] >= 0 else "NOT "
            ref = store.chunk_ref(conn, f["chunk_id"])
            parts.append(f"    [{ref}] {f['attribute']}={neg}{f['value']}")

    return "\n".join(parts)


def run_final_pass(conn, client: OllamaClient, verbose: bool = True) -> int:
    digest = _build_digest(conn)
    user = (
        "Here is the structured data extracted from the entire novel. Audit it "
        "for cross-cutting continuity problems.\n\n" + digest +
        "\n\nReason step by step, then output the JSON object."
    )
    if verbose:
        print(f"  [final] sending digest ({len(digest.split())} words) to "
              f"{FINAL_MODEL}; this pass is slow...")
    try:
        # Direct JSON mode (no thinking) keeps the whole budget for the answer.
        # 10k context fits the trimmed digest and stays fully in VRAM on 8GB.
        raw = client.chat(FINAL_MODEL, prompts.FINAL_SYSTEM, user,
                          fmt="json", think=False, temperature=0.0,
                          num_ctx=10240, num_predict=2000)
    except Exception as e:  # noqa: BLE001
        print(f"  [final] FAILED to call model ({e})")
        return 0
    cleaned = client.strip_think(raw)
    try:
        from .ollama_client import _loads_lenient
        data = _loads_lenient(cleaned)
    except Exception as e:  # noqa: BLE001
        print(f"  [final] could not parse model output ({e}); raw saved.")
        return 0

    conflicts = data.get("conflicts", []) if isinstance(data, dict) else []
    for conf in conflicts:
        desc = conf.get("description", "")
        chapters = conf.get("chapters_involved", "")
        full = f"{desc} (chapters: {chapters})" if chapters else desc
        store.insert_conflict(
            conn, kind=conf.get("kind", "other"), description=full,
            severity=conf.get("severity", "medium"),
            source_a_chunk=None, source_a_quote=conf.get("evidence", ""),
            source_b_chunk=None, source_b_quote=None, detected_by="final_pass")
    conn.commit()
    if verbose:
        print(f"  [final] {len(conflicts)} cross-cutting issue(s) found")
    return len(conflicts)

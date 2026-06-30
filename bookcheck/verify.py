"""Verification pass: for each suspected contradiction, re-read the two source
scenes and have the model confirm — strictly from the text — that the two
excerpts really state DIFFERENT values of the attribute FOR THE NAMED CHARACTER.

This is the grounding step that catches the two failure modes the bare
extraction can't: a trait that actually belongs to a different character in the
scene, and a temporary/lighting/metaphorical description mistaken for a fixed
attribute.
"""

from __future__ import annotations

from . import store
from .ollama_client import OllamaClient

VERIFY_MODEL = "qwen3:8b"

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "a_about_character": {"type": "boolean"},
        "b_about_character": {"type": "boolean"},
        "is_fixed_attribute": {"type": "boolean"},
        "verdict": {"type": "string", "enum": ["real", "not_real"]},
        "reason": {"type": "string"},
    },
    "required": ["a_about_character", "b_about_character", "is_fixed_attribute",
                 "verdict", "reason"],
}

VERIFY_SYSTEM = """\
You verify a SUSPECTED continuity contradiction in a novel before it is shown to \
the author. You get a character name, an attribute (e.g. eye color), and two \
excerpts that allegedly give different values of that attribute for that \
character.

Decide STRICTLY from the excerpts:
- a_about_character: does excerpt A actually describe THIS attribute of THIS \
named character (not a different character who appears in the scene)?
- b_about_character: same question for excerpt B.
- is_fixed_attribute: are BOTH descriptions of the character's real, fixed \
attribute -- NOT a temporary state, lighting effect, metaphor, or simile \
(e.g. "curls turned almost silver in the candlelight" is lighting, not hair \
color)?
- verdict: "real" ONLY if both excerpts are about this character, both are \
fixed-attribute statements, AND the two values genuinely cannot both be true. \
Otherwise "not_real".
- reason: one sentence, citing what you saw.

Be skeptical: most suspected contradictions are misattributions or lighting/\
metaphor. Return valid JSON.\
"""


def _excerpt(conn, chunk_id, limit_words=700):
    row = conn.execute("SELECT text FROM chunks WHERE id=?", (chunk_id,)).fetchone()
    if not row:
        return ""
    words = (row["text"] or "").split()
    return " ".join(words[:limit_words])


def verify_conflict(conn, client, conflict_row) -> dict:
    """Return the model's verdict dict for one conflict row."""
    desc = conflict_row["description"]
    a = _excerpt(conn, conflict_row["source_a_chunk"])
    b = _excerpt(conn, conflict_row["source_b_chunk"])
    name = desc.split(":")[0].strip()
    user = (
        f"CHARACTER: {name}\n"
        f"SUSPECTED CONTRADICTION: {desc}\n\n"
        f"EXCERPT A:\n\"\"\"\n{a}\n\"\"\"\n\n"
        f"EXCERPT B:\n\"\"\"\n{b}\n\"\"\"\n\n"
        "Verify now."
    )
    return client.chat_json(VERIFY_MODEL, VERIFY_SYSTEM, user,
                            schema=VERIFY_SCHEMA, think=False, num_ctx=8192,
                            num_predict=500)


def run_verification(conn, client: OllamaClient, verbose: bool = True) -> int:
    """Verify every entity-pass conflict; mark unconfirmed ones dismissed.
    Returns the number that survive as real."""
    rows = conn.execute(
        "SELECT * FROM conflicts WHERE detected_by='entity_pass' "
        "AND status='open'").fetchall()
    kept = 0
    for r in rows:
        try:
            v = verify_conflict(conn, client, r)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [verify] #{r['id']}: ERROR ({e}) -> keeping")
            kept += 1
            continue
        verdict = v.get("verdict") if isinstance(v, dict) else None
        if verdict == "real":
            kept += 1
            if verbose:
                print(f"  [verify] #{r['id']} KEEP — {v.get('reason','')}")
        else:
            conn.execute("UPDATE conflicts SET status='dismissed' WHERE id=?",
                         (r["id"],))
            if verbose:
                print(f"  [verify] #{r['id']} DROP — {v.get('reason','')}")
        conn.commit()
    return kept

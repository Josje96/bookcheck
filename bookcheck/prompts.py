"""Prompt templates and JSON schemas for extraction and conflict passes."""

# --- Extraction ----------------------------------------------------------

# Bounded array sizes keep total output small so generation finishes within the
# num_predict cap (important on a slow GPU). Quotes are required only on `facts`
# and `knowledge` -- the two categories used as conflict evidence in the report.
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "characters": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "species": {"type": "string"},
                    "traits": {
                        "type": "array", "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "attribute": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["attribute", "value"],
                        },
                    },
                },
                "required": ["name", "species", "traits"],
            },
        },
        "locations": {
            "type": "array", "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "facts": {
            "type": "array", "maxItems": 14,
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "entity_type": {
                        "type": "string",
                        "enum": ["character", "location", "object", "world"],
                    },
                    "attribute": {"type": "string"},
                    "value": {"type": "string"},
                    "polarity": {"type": "string", "enum": ["positive", "negative"]},
                    "quote": {"type": "string"},
                },
                "required": ["entity", "entity_type", "attribute", "value",
                             "polarity", "quote"],
            },
        },
        "relationships": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "char_a": {"type": "string"},
                    "char_b": {"type": "string"},
                    "relation": {"type": "string"},
                },
                "required": ["char_a", "char_b", "relation"],
            },
        },
        "timeline": {
            "type": "array", "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "when": {"type": "string"},
                    "event": {"type": "string"},
                },
                "required": ["when", "event"],
            },
        },
        "knowledge": {
            "type": "array", "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "character": {"type": "string"},
                    "learns": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["character", "learns", "quote"],
            },
        },
        "plot_setups": {
            "type": "array", "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
        "plot_payoffs": {
            "type": "array", "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
    },
    "required": ["characters", "locations", "facts", "relationships",
                 "timeline", "knowledge", "plot_setups", "plot_payoffs"],
}

EXTRACTION_SYSTEM = """\
You are a meticulous story-continuity analyst. You read one scene of a novel \
and extract structured facts that a later pass will use to detect plot holes. \
Extract ONLY what the text states or directly implies. Do not invent details. \
Be concise: capture the most important, checkable items, not every nuance. For \
`facts` and `knowledge`, include a short verbatim quote (<= 20 words) from the \
scene as evidence; other categories do not need quotes.

CRITICAL — attribute each detail to the RIGHT character. A scene is told from
one character's point of view but describes several people. Assign every trait
and fact to the character the sentence is actually about, NOT to the POV
character by default. Example: in a scene from Willow's POV, "His brown eyes
looked serious" describes the man she is looking at, not Willow. If you are not
sure who a detail belongs to, OMIT it rather than guess.

Definitions:
- characters: named people/beings present or referenced. Set `species` ONLY when
the text states or unmistakably shows it: an explicit word ("a werewolf", "the
witch"), or an unambiguous physical tell (wings -> fae/fairy; drinks blood / no
heartbeat / ice-cold skin -> vampire; shifts/fur/pack -> werewolf; casts spells
-> witch). Do NOT default to "human"; if species is not established, leave it an
empty string. In `traits`, capture EVERY concrete physical or identity detail
the scene gives for this person: eye color, hair color/style, build or height,
age, distinctive marks, and visible condition (injured, pregnant, exhausted).
Each trait is an {attribute, value} pair, e.g. {"attribute": "eye_color",
"value": "green"}. Only leave `traits` empty when the scene names someone but
describes nothing about them.
- facts: durable, checkable statements about an entity that could later be
contradicted (species, eye/hair color, age, alive/dead, owns X, can/can't do X).
attribute is a short stable key (e.g. "eye_color", "is_alive", "owns_cottage").
ALWAYS record a character's stated identity and continuity facts here (species,
eye/hair color, age, alive/dead) - these are exactly what the later continuity
check compares, so a scene that physically describes its people should never
return an empty facts list. Do NOT record fleeting actions, emotions, postures,
or body parts mentioned in passing (e.g. "her chin brushed his collarbone" is NOT
a fact that he "wears" a collarbone - skip it). polarity is "negative" when the text negates the fact
(e.g. "he had no heartbeat" -> attribute "heartbeat", value "present", polarity
"negative").
- locations: named places where the scene happens or that are referenced (a
town, a tavern, a cottage). Give a short `description` (a phrase) of what the
place is when the text makes it clear; otherwise leave description empty. Do NOT
list a person as a location.
- relationships: how two NAMED characters relate. Use a specific relation word:
friend, love interest, partner, spouse, sibling, parent, child, cousin, aunt,
uncle, mentor, ally, enemy, rival, employer. Both char_a and char_b must be
actual named people present or named in this scene (never a generic role like
"the bartender"). Record a relationship only when the text shows or states it.
- timeline: events anchored to a stated time/day/sequence ("an hour ago", "the
next morning", "three days later").
- knowledge: ONLY when a character LEARNS something genuinely NEW to them in this
scene — a revelation, discovery, or first realization. Do NOT record things a
character already plainly knows, or common knowledge everyone in the world shares
(e.g. who is what species). "character" is who learns it; "learns" is the
proposition.
- plot_setups: promises, foreshadowing, unfired Chekhov's guns, unanswered
questions raised here.
- plot_payoffs: places where an earlier setup is resolved or paid off.

Prefer durable, checkable details over trivial ones, but do NOT return empty
`traits`/`facts` for a character the scene actually describes. Return valid JSON
matching the schema. Use empty arrays only where nothing genuinely applies.\
"""


def extraction_user(scene_text: str, pov: str | None, date_label: str | None,
                    chapter_ref: str) -> str:
    header = f"[{chapter_ref}"
    if pov:
        header += f" | POV: {pov}"
    if date_label:
        header += f" | In-story date: {date_label}"
    header += "]"
    return (f"{header}\n\nSCENE:\n\"\"\"\n{scene_text}\n\"\"\"\n\n"
            "Extract the structured data now.")


# --- Entity consistency pass (write-time, qwen3) -------------------------

CONSISTENCY_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["trait_contradiction", "object_state",
                                 "relationship", "knowledge_leak", "other"],
                    },
                    "description": {"type": "string"},
                    "severity": {"type": "string",
                                 "enum": ["high", "medium", "low"]},
                    "quote_a": {"type": "string"},
                    "quote_b": {"type": "string"},
                },
                "required": ["kind", "description", "severity", "quote_a",
                             "quote_b"],
            },
        }
    },
    "required": ["conflicts"],
}

CONSISTENCY_SYSTEM = """\
You are a strict story-continuity checker. You are given every recorded fact \
about ONE entity from a novel, in reading order, each tagged with its chapter \
and a supporting quote. Find genuine CONTRADICTIONS: two facts describing the \
SAME stable attribute with values that cannot both be true of this entity at \
the same point in the story.

Good examples to flag:
- eye color green in one chapter, brown in another;
- "had no heartbeat" vs "his heartbeat thudded";
- species stated as vampire in one place, werewolf in another;
- hair described as copper, then red; role as kitchen worker, then nurse.

Do NOT flag (these are NOT contradictions):
- BACKSTORY OR SEQUENCE: things that change legitimately over the plot (she \
lost the cottage, then got it back; was injured, then healed; a possession \
bought or given). Different points in time are not contradictions.
- TWO PHRASINGS OF THE SAME THING: e.g. "small cut" and "minor wound", \
"copper curls" and "ribbon in copper hair" -- compatible, not conflicting.
- COMPLEMENTARY DETAILS that simply add information.
- Emotions, moods, opinions, or temporary states changing.
- Metaphor, poetry, hallucination, or dreams.
- A fact that actually belongs to a DIFFERENT character (if the quote is about \
someone else, ignore it -- do not attribute it to this entity).
- Vague, world-building, or plausibly-intentional genre details.

Both sides must come from DIFFERENT quotes; never pair a quote with itself. \
Report each distinct contradiction only ONCE. Set "kind" accurately \
(trait_contradiction for physical/identity traits; object_state for objects; \
relationship for who-relates-to-whom). Reserve "high" severity for hard \
identity/physical contradictions. If there are no genuine contradictions, \
return an empty list. Return valid JSON.\
"""


def consistency_user(entity_name: str, entity_kind: str, fact_lines: str) -> str:
    return (f"ENTITY: {entity_name} ({entity_kind})\n\n"
            f"RECORDED FACTS (chapter | attribute | value | quote):\n"
            f"{fact_lines}\n\nList genuine contradictions now.")


# --- Final cross-cutting pass (deepseek-r1) ------------------------------

FINAL_SYSTEM = """\
You are a senior story editor doing a final continuity audit of a novel. You are \
given a CONDENSED, lossy digest of structured data extracted from the book — you \
are NOT seeing the full text, so be humble about what you cannot see. Report only \
hard, well-founded problems. When in doubt, say nothing: a short, correct list \
beats a long, speculative one.

You may consider:
- TIMELINE: events that are genuinely impossible given the stated dates/sequence \
(an effect before its cause; one character in two places at the same time).
- UNRESOLVED SETUPS: a significant promise/Chekhov's gun with NO later mention \
anywhere in the digest.

STRICT RULES — do NOT flag any of the following:
- "Should have known" speculation. Never infer that a character ought to have \
learned something. Only flag knowledge problems if the text shows a character \
stating a specific fact they provably could not have encountered yet.
- Common world knowledge. Assume every character knows the basic facts of their \
world (e.g. who is what species/race) unless the story explicitly makes it a \
secret.
- Time passing while a character is "off screen" — that is normal, not a gap.
- Figures of speech, metaphor, or atmospheric language taken literally.
- "Unresolved" claims when you are not confident: the digest is incomplete, so a \
thread you don't see resolved may well be resolved in the full text. Only call \
something unresolved if it is a major setup with clearly no follow-up.

Prefer returning an EMPTY list over a weak guess. After brief reasoning, output a \
JSON object with a "conflicts" array; each item has: kind (timeline|\
unresolved_thread|other), description, severity (high|medium|low), \
chapters_involved (string), evidence (string).\
"""

FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {"type": "string"},
                    "chapters_involved": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["kind", "description", "severity",
                             "chapters_involved", "evidence"],
            },
        }
    },
    "required": ["conflicts"],
}

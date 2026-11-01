"""Conservative legislative milestones from official Congress.gov actions.

Codes are interpreted only for Library of Congress source 9:
https://www.congress.gov/help/field-values/action-codes
Milestones describe recorded actions, never odds or time remaining.
"""

from dataclasses import dataclass
import re
from typing import Any

_PASSAGE_CODES = {"8000": "House", "17000": "Senate", "32000": "House", "34000": "Senate"}
_LAW_CODES = {
    "29000", "29100", "36000", "37000", "38000", "39000", "40000",
    "41000", "42000", "43000", "44000", "45000",
}

@dataclass(frozen=True)
class LegislativeProgress:
    steps: tuple[str, ...]
    reached: tuple[bool, ...]
    status: str

    @property
    def blocked(self) -> bool:
        return self.status.startswith(("Vetoed", "Pocket vetoed", "Failed"))

    def post_copy(self) -> str:
        bar = "".join("#" if reached else "-" for reached in self.reached)
        return f"Progress: [{bar}] {self.status}\nPath: {' > '.join(self.steps)}"


def progress_from_copy(text: str) -> LegislativeProgress | None:
    """Read the human-readable progress paragraph embedded in post copy."""
    match = re.search(r"^Progress: \[([#-]+)\] ([^\n]+)\nPath: ([^\n]+)$", text, re.M)
    if not match:
        return None
    steps = tuple(match[3].split(" > "))
    if len(steps) != len(match[1]) or not 2 <= len(steps) <= 5:
        return None
    return LegislativeProgress(steps, tuple(char == "#" for char in match[1]), match[2])


def legislative_progress(
    bill_type: str, title: str, actions: list[dict[str, Any]]
) -> LegislativeProgress:
    """Track passage of this measure, excluding amendments and procedural votes.

    The caller supplies only actions on or before the post's date. House and
    Senate passage alone do not establish agreement on identical text.
    """
    first, second = (
        ("House", "Senate") if bill_type.startswith("H") else ("Senate", "House")
    )
    simple = bill_type in {"HRES", "SRES"}
    concurrent = bill_type in {"HCONRES", "SCONRES"}
    constitutional = bill_type in {"HJRES", "SJRES"} and bool(re.search(
        r"\bproposing an amendment(?:s)? to the Constitution\b", title, re.I
    ))
    steps = ("Introduced", first)
    if not simple:
        steps += (second,)
    if not (simple or concurrent or constitutional):
        steps += ("President", "Law")

    passed: set[str] = set()
    presented = became_law = vetoed = False
    committee = floor = False
    blocked = ""
    final_agreement = False
    conference_agreed: set[str] = set()
    # Preserve API ordering within each date: sources without actionTime must
    # not move before earlier timed actions from the same day.
    ordered = sorted(reversed(actions), key=lambda action: str(action.get("actionDate", "")))
    for action in ordered:
        text = " ".join(str(action.get("text", "")).split())
        source = action.get("sourceSystem", {})
        code = ""
        if isinstance(source, dict) and str(source.get("code")) == "9":
            code = str(action.get("actionCode", ""))
        passage = re.match(
            r"^(?:Passed (House|Senate)|(?:Agreed to|Resolution agreed to) in (House|Senate))\b",
            text, re.I,
        )
        house_vote = re.match(
            r"^On (?:passage|agreeing to the resolution|motion to suspend the rules and "
            r"(?:pass the bill|agree to the resolution))(?:, as amended)?[. ]+"
            r"(Passed|Agreed to|Failed)\b", text, re.I
        )
        chamber = _PASSAGE_CODES.get(code)
        if passage:
            chamber = (passage[1] or passage[2]).title()
            if chamber == second and re.search(r"\bwithout amendment\b", text, re.I):
                final_agreement = True
        elif house_vote and house_vote[1].lower() != "failed":
            chamber = "House"
        if chamber:
            passed.add(chamber)
            if not vetoed:
                blocked = ""
        if (
            (house_vote and house_vote[1].lower() == "failed")
            or code in {"9000", "18000", "33000", "35000"}
            or re.match(r"^(?:Failed (?:of )?passage|Failed to pass|Not agreed to in (?:House|Senate))\b", text, re.I)
        ):
            blocked = "Failed passage — see latest action"
        if code in {"30000", "31000"} or re.match(r"^(?:Pocket vetoed|Vetoed)\b", text, re.I):
            blocked = (
                "Pocket vetoed" if code == "30000" or text.lower().startswith("pocket")
                else "Vetoed — override required"
            )
            presented = vetoed = True
        if code == "28000" or re.match(r"^Presented to President\b", text, re.I):
            presented = True
        if code in {"21000", "23000"}:
            conference_agreed.add("House" if code == "21000" else "Senate")
        if (
            code in _LAW_CODES or action.get("type") == "BecameLaw"
            or re.match(r"^(?:Became (?:Public|Private) Law|Signed by President)\b", text, re.I)
        ):
            became_law = True
        # Explicit final concurrence means both chambers approved the same text.
        # A motion, conference appointment, or amendment vote alone does not.
        if re.match(
            r"^(?:House|Senate) (?:agreed to|concurs? in) (?:the )?(?:House|Senate) amendments?\b",
            text, re.I,
        ) and not re.search(r"\bwith (?:an? |further |an? further )?amendments?\b", text, re.I):
            final_agreement = True
        committee |= action.get("type") == "Committee" or bool(re.search(
            r"\b(?:committee|reported|referred)\b", text, re.I
        ))
        floor |= action.get("type") == "Floor"

    final_agreement |= conference_agreed == {"House", "Senate"}
    if presented or became_law or final_agreement:
        passed.update(("House", "Senate"))
    if became_law:
        presented = True
    reached = tuple(
        step == "Introduced" or step in passed
        or (step == "President" and presented) or (step == "Law" and became_law)
        for step in steps
    )
    status = "Introduced"
    if committee:
        status = "In committee / awaiting floor action"
    if floor:
        status = "Under floor consideration"
    if passed:
        status = f"Passed {first if first in passed else second}"
    if {"House", "Senate"} <= passed:
        status = "Both chambers passed — final agreement required"
    if final_agreement:
        status = "Cleared Congress"
    if presented:
        status = "Presented to president"
    if simple and first in passed:
        status = f"Agreed to in {first} — complete"
    if concurrent and final_agreement:
        status = "Agreed to by Congress — complete"
    if constitutional and final_agreement:
        status = "Proposed to states — ratification required"
    if blocked:
        status = blocked
    if became_law:
        status = "Became law"
    return LegislativeProgress(steps, reached, status)

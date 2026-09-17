"""The rule engine: run compiled rules over text segments and report hits."""
from __future__ import annotations

from dataclasses import dataclass

from housestyle.readers import Segment
from housestyle.rules import Rule


@dataclass(frozen=True)
class Hit:
    part: str | None
    line: int
    col: int
    rule: str
    severity: str
    match: str
    remedy: str
    segment_index: int
    offset: int
    rule_index: int

    def sort_key(self):
        return (self.segment_index, self.offset, self.rule_index)


def find_hits(segments: list[Segment], rules: list[Rule]) -> list[Hit]:
    hits: list[Hit] = []
    for seg_index, segment in enumerate(segments):
        for rule_index, rule in enumerate(rules):
            exception_spans = [
                m.span() for ex in rule.exceptions for m in ex.finditer(segment.text)
            ]
            for match in rule.regex.finditer(segment.text):
                start, end = match.span()
                if start == end:
                    continue
                if any(s <= start and end <= e for s, e in exception_spans):
                    continue
                line, col = segment.locate(start)
                hits.append(Hit(
                    part=segment.part, line=line, col=col, rule=rule.id,
                    severity=rule.severity, match=match.group(0), remedy=rule.remedy,
                    segment_index=seg_index, offset=start, rule_index=rule_index,
                ))
    hits.sort(key=Hit.sort_key)
    return hits


def check_text(text: str, rules: list[Rule], part: str | None = None) -> list[Hit]:
    """Run the rules over one piece of text, for callers that hold text already."""
    return find_hits([Segment(part=part, text=text)], rules)

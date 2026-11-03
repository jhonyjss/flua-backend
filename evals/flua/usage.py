"""Tokens spent in a run, per model, so each run reports what it cost."""
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Tokens:
    input: int = 0
    cached: int = 0
    output: int = 0


class Usage:
    def __init__(self) -> None:
        self.by_model: dict[str, Tokens] = defaultdict(Tokens)

    def add(self, model: str, usage: dict | None) -> None:
        """Takes a Realtime `response.done` usage or a Responses API usage (same field names)."""
        if not usage:
            return
        tokens = self.by_model[model or "?"]
        tokens.input += usage.get("input_tokens", 0)
        details = usage.get("input_token_details") or usage.get("input_tokens_details") or {}
        tokens.cached += details.get("cached_tokens", 0)
        tokens.output += usage.get("output_tokens", 0)

    def lines(self) -> list[str]:
        return [f"  {model:24} entrada {t.input:>9,} (cache {t.cached:,}) · saída {t.output:,}"
                for model, t in sorted(self.by_model.items())]


USAGE = Usage()

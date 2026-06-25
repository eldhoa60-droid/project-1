"""Fit long interview transcripts into an LLM context window."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence


Summarizer = Callable[[str, int], str]


@dataclass(frozen=True)
class TranscriptTurn:
    role: str
    content: str


@dataclass(frozen=True)
class CompactionResult:
    transcript: str
    token_count: int
    token_limit: int
    strategy: str
    omitted_turns: int


class TokenCounter:
    """Count and truncate tokens, using tiktoken when it is installed."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self._encoding = None
        try:
            import tiktoken

            try:
                self._encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                self._encoding = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            pass

    @property
    def exact(self) -> bool:
        return self._encoding is not None

    def count(self, text: str) -> int:
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        # Conservative dependency-free approximation. Counting every four
        # characters as a token intentionally overestimates typical English.
        return (len(text) + 3) // 4

    def truncate(self, text: str, max_tokens: int, *, keep_end: bool = False) -> str:
        if max_tokens <= 0:
            return ""
        if self._encoding is not None:
            tokens = self._encoding.encode(text)
            selected = tokens[-max_tokens:] if keep_end else tokens[:max_tokens]
            return self._encoding.decode(selected)
        max_chars = max_tokens * 4
        return text[-max_chars:] if keep_end else text[:max_chars]


def render_turns(turns: Iterable[TranscriptTurn]) -> str:
    return "\n\n".join(f"{turn.role}: {turn.content.strip()}" for turn in turns)


def _fit_text(
    text: str, limit: int, counter: TokenCounter, *, keep_end: bool = False
) -> str:
    """Truncate until the rendered text is guaranteed to satisfy the limit."""
    candidate = counter.truncate(text, limit, keep_end=keep_end)
    while candidate and counter.count(candidate) > limit:
        candidate = counter.truncate(
            candidate, max(0, limit - 1), keep_end=keep_end
        )
        limit -= 1
    return candidate


def compact_transcript(
    turns: Sequence[TranscriptTurn],
    *,
    model_context_tokens: int,
    reserved_output_tokens: int = 1024,
    prompt_overhead_tokens: int = 256,
    recent_turns_to_keep: int = 8,
    summary_fraction: float = 0.35,
    model: str = "gpt-4o-mini",
    summarizer: Summarizer | None = None,
    counter: TokenCounter | None = None,
) -> CompactionResult:
    """Return a transcript that fits the input portion of a model context.

    The newest turns are retained verbatim. Older turns are summarized when a
    summarizer callback is supplied; otherwise they are truncated. A final hard
    truncation guarantees the reported transcript is within the calculated
    input budget.
    """
    if model_context_tokens <= 0:
        raise ValueError("model_context_tokens must be positive")
    if reserved_output_tokens < 0 or prompt_overhead_tokens < 0:
        raise ValueError("reserved token counts cannot be negative")
    if recent_turns_to_keep < 0:
        raise ValueError("recent_turns_to_keep cannot be negative")
    if not 0 <= summary_fraction <= 1:
        raise ValueError("summary_fraction must be between 0 and 1")

    token_limit = (
        model_context_tokens - reserved_output_tokens - prompt_overhead_tokens
    )
    if token_limit <= 0:
        raise ValueError("No transcript budget remains after reserved tokens")

    counter = counter or TokenCounter(model)
    full_text = render_turns(turns)
    full_count = counter.count(full_text)
    if full_count <= token_limit:
        return CompactionResult(
            full_text, full_count, token_limit, "unchanged", 0
        )

    split_at = max(0, len(turns) - recent_turns_to_keep)
    older, recent = turns[:split_at], turns[split_at:]
    recent_text = render_turns(recent)

    # If the recent section alone is too large, preserving its end is the most
    # useful deterministic behavior for a live interview.
    if counter.count(recent_text) >= token_limit:
        fitted = _fit_text(recent_text, token_limit, counter, keep_end=True)
        return CompactionResult(
            fitted,
            counter.count(fitted),
            token_limit,
            "recent-turns-truncated",
            len(older),
        )

    separator = "\n\n" if recent_text else ""
    available_for_history = (
        token_limit - counter.count(recent_text) - counter.count(separator)
    )
    header = "[Earlier interview context]\n"
    header_tokens = counter.count(header)
    history_budget = max(0, available_for_history - header_tokens)
    history_text = render_turns(older)

    if summarizer is not None and history_budget > 0:
        requested_summary_tokens = min(
            history_budget, max(1, int(token_limit * summary_fraction))
        )
        summary = summarizer(history_text, requested_summary_tokens).strip()
        summary = _fit_text(summary, history_budget, counter)
        strategy = "summarized"
    else:
        summary = _fit_text(history_text, history_budget, counter, keep_end=True)
        strategy = "history-truncated"

    parts = []
    if summary:
        parts.append(header + summary)
    if recent_text:
        parts.append(recent_text)
    candidate = "\n\n".join(parts)

    # Tokenizers and callback output can produce edge cases around boundaries.
    # This final gate is the contract: never return text over token_limit.
    if counter.count(candidate) > token_limit:
        candidate = _fit_text(candidate, token_limit, counter, keep_end=True)
        strategy += "+hard-limit"

    return CompactionResult(
        candidate,
        counter.count(candidate),
        token_limit,
        strategy,
        len(older),
    )


def _load_turns(path: Path) -> list[TranscriptTurn]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("Transcript JSON must be an array")
    return [
        TranscriptTurn(role=str(item["role"]), content=str(item["content"]))
        for item in data
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path, help="JSON array of role/content turns")
    parser.add_argument("--context-tokens", type=int, required=True)
    parser.add_argument("--reserved-output-tokens", type=int, default=1024)
    parser.add_argument("--prompt-overhead-tokens", type=int, default=256)
    parser.add_argument("--recent-turns", type=int, default=8)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = compact_transcript(
        _load_turns(args.transcript),
        model_context_tokens=args.context_tokens,
        reserved_output_tokens=args.reserved_output_tokens,
        prompt_overhead_tokens=args.prompt_overhead_tokens,
        recent_turns_to_keep=args.recent_turns,
        model=args.model,
    )
    if args.output:
        args.output.write_text(result.transcript, encoding="utf-8")
    else:
        print(result.transcript)
    print(
        json.dumps(
            {
                "token_count": result.token_count,
                "token_limit": result.token_limit,
                "within_limit": result.token_count <= result.token_limit,
                "strategy": result.strategy,
                "omitted_turns": result.omitted_turns,
            }
        )
    )


if __name__ == "__main__":
    main()

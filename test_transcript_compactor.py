import unittest

from transcript_compactor import (
    TokenCounter,
    TranscriptTurn,
    compact_transcript,
)


class CharacterCounter(TokenCounter):
    """Predictable test counter: one character equals one token."""

    def __init__(self):
        pass

    def count(self, text):
        return len(text)

    def truncate(self, text, max_tokens, *, keep_end=False):
        return text[-max_tokens:] if keep_end else text[:max_tokens]


class TranscriptCompactorTests(unittest.TestCase):
    def setUp(self):
        self.counter = CharacterCounter()

    def test_short_transcript_is_unchanged(self):
        turns = [TranscriptTurn("Interviewer", "Hello")]
        result = compact_transcript(
            turns,
            model_context_tokens=100,
            reserved_output_tokens=10,
            prompt_overhead_tokens=10,
            counter=self.counter,
        )
        self.assertEqual(result.strategy, "unchanged")
        self.assertEqual(result.transcript, "Interviewer: Hello")
        self.assertLessEqual(result.token_count, result.token_limit)

    def test_long_history_is_summarized_and_recent_turns_are_preserved(self):
        turns = [
            TranscriptTurn("Interviewer", "old question " * 20),
            TranscriptTurn("Candidate", "old answer " * 20),
            TranscriptTurn("Interviewer", "latest question"),
            TranscriptTurn("Candidate", "latest answer"),
        ]

        def summarize(_text, max_tokens):
            return "summary of earlier discussion"[:max_tokens]

        result = compact_transcript(
            turns,
            model_context_tokens=150,
            reserved_output_tokens=10,
            prompt_overhead_tokens=10,
            recent_turns_to_keep=2,
            summarizer=summarize,
            counter=self.counter,
        )
        self.assertIn("summary of earlier discussion", result.transcript)
        self.assertIn("latest question", result.transcript)
        self.assertIn("latest answer", result.transcript)
        self.assertEqual(result.strategy, "summarized")
        self.assertLessEqual(result.token_count, result.token_limit)

    def test_recent_content_is_hard_truncated_when_it_exceeds_budget(self):
        turns = [TranscriptTurn("Candidate", "x" * 200)]
        result = compact_transcript(
            turns,
            model_context_tokens=80,
            reserved_output_tokens=10,
            prompt_overhead_tokens=10,
            recent_turns_to_keep=1,
            counter=self.counter,
        )
        self.assertEqual(result.token_limit, 60)
        self.assertEqual(result.token_count, 60)
        self.assertEqual(result.strategy, "recent-turns-truncated")
        self.assertLessEqual(result.token_count, result.token_limit)

    def test_fallback_truncates_history_without_summarizer(self):
        turns = [
            TranscriptTurn("Candidate", "a" * 100),
            TranscriptTurn("Candidate", "new"),
        ]
        result = compact_transcript(
            turns,
            model_context_tokens=100,
            reserved_output_tokens=10,
            prompt_overhead_tokens=10,
            recent_turns_to_keep=1,
            counter=self.counter,
        )
        self.assertEqual(result.strategy, "history-truncated")
        self.assertIn("Candidate: new", result.transcript)
        self.assertLessEqual(result.token_count, result.token_limit)

    def test_invalid_budget_is_rejected(self):
        with self.assertRaises(ValueError):
            compact_transcript(
                [],
                model_context_tokens=100,
                reserved_output_tokens=80,
                prompt_overhead_tokens=20,
                counter=self.counter,
            )


if __name__ == "__main__":
    unittest.main()

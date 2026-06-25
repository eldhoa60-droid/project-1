# Transcript Compactor

Fits long interview transcripts into an LLM context window while preserving the
most recent turns.

## Website

Open `index.html` directly, or serve the folder locally:

```powershell
python -m http.server 8000
```

Then visit `http://localhost:8000`. The website runs entirely in the browser,
supports plain-text and JSON transcripts, imports local files, compacts older
turns, verifies the final estimated token count, and exports the result.

## Behavior

1. Calculates the transcript budget:
   `context window - reserved output - prompt overhead`.
2. Returns short transcripts unchanged.
3. Preserves recent turns verbatim where possible.
4. Summarizes older turns through an optional callback.
5. Falls back to deterministic truncation when no summarizer is configured.
6. Applies a final hard limit and reports the confirmed token count.

`tiktoken` is used when installed. Without it, the module uses a conservative
four-characters-per-token estimate.

## Python usage

```python
from transcript_compactor import TranscriptTurn, compact_transcript

turns = [
    TranscriptTurn("Interviewer", "Tell me about your last project."),
    TranscriptTurn("Candidate", "It involved ..."),
]

result = compact_transcript(
    turns,
    model_context_tokens=128_000,
    reserved_output_tokens=4_000,
    prompt_overhead_tokens=1_000,
    recent_turns_to_keep=10,
    summarizer=lambda text, max_tokens: your_llm_summary(text, max_tokens),
)

assert result.token_count <= result.token_limit
print(result.transcript)
```

The summarizer callback receives `(older_transcript, max_summary_tokens)`.

## CLI

Input is a JSON array:

```json
[
  {"role": "Interviewer", "content": "Question"},
  {"role": "Candidate", "content": "Answer"}
]
```

Run:

```powershell
python transcript_compactor.py transcript.json `
  --context-tokens 128000 `
  --reserved-output-tokens 4000 `
  --prompt-overhead-tokens 1000 `
  --output compacted.txt
```

The CLI prints metadata including `token_count`, `token_limit`, and
`within_limit`.

## Test

```powershell
python -m unittest -v
```

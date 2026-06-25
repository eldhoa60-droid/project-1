const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const els = {
  model: $("#modelPreset"),
  customField: $("#customField"),
  customContext: $("#customContext"),
  reserve: $("#responseReserve"),
  overhead: $("#promptOverhead"),
  recent: $("#recentTurns"),
  turnCount: $("#turnCount"),
  budget: $("#availableBudget"),
  input: $("#transcriptInput"),
  inputStats: $("#inputStats"),
  formatHint: $("#formatHint"),
  file: $("#fileInput"),
  result: $("#resultSection"),
  output: $("#outputText"),
  finalTokens: $("#finalTokens"),
  limitLabel: $("#tokenLimitLabel"),
  originalTokens: $("#originalTokens"),
  reduction: $("#reductionValue"),
  turnsRetained: $("#turnsRetained"),
  meter: $("#meterFill"),
  toast: $("#toast"),
};

let format = "text";

const sample = `Interviewer: Let's begin with the architecture. What problem was the team trying to solve?

Candidate: We were rebuilding an interview platform that struggled during long sessions. Transcripts grew continuously, and eventually the prompt exceeded the model context window. That caused failures late in interviews, precisely when the accumulated context mattered most.

Interviewer: What constraints did you have?

Candidate: We needed to retain the latest conversation verbatim, keep important facts from earlier answers, and guarantee that every model request stayed below its token limit. The solution also had to degrade gracefully if the summarization service was unavailable.

Interviewer: How did you approach the design?

Candidate: I divided the context into three regions: fixed prompt overhead, reserved output capacity, and the remaining transcript budget. Recent turns receive priority. Older turns are summarized into a running memory, and a deterministic truncation pass acts as the final safety net.

Interviewer: How did you verify it?

Candidate: We counted tokens after every transformation, tested boundary conditions, and rejected invalid configurations where reserves consumed the entire context window.

Interviewer: What was the result?

Candidate: Long interviews continued without context errors, while the model retained both recent nuance and the important decisions from earlier in the session.`;

function tokenCount(text) {
  return Math.ceil(text.length / 4);
}

function getLimit() {
  const context = els.model.value === "custom"
    ? Number(els.customContext.value || 0)
    : Number(els.model.value);
  return Math.max(0, context - Number(els.reserve.value || 0) - Number(els.overhead.value || 0));
}

function updateBudget() {
  els.customField.hidden = els.model.value !== "custom";
  const limit = getLimit();
  els.budget.textContent = limit.toLocaleString();
  els.turnCount.textContent = els.recent.value;
  const percentage = ((Number(els.recent.value) - 1) / 23) * 100;
  els.recent.style.background = `linear-gradient(90deg, var(--violet) ${percentage}%, #d6d2c8 ${percentage}%)`;
}

function updateInputStats() {
  const text = els.input.value.trim();
  const words = text ? text.split(/\s+/).length : 0;
  els.inputStats.textContent = `${words.toLocaleString()} words · ~${tokenCount(text).toLocaleString()} tokens`;
}

function parseTurns(raw) {
  if (format === "json") {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) throw new Error("JSON must be an array of transcript turns.");
    return parsed.map((item) => ({
      role: String(item.role || item.speaker || "Speaker"),
      content: String(item.content || item.text || ""),
    })).filter((turn) => turn.content.trim());
  }

  const turns = [];
  let current = null;
  for (const block of raw.split(/\n\s*\n/).filter(Boolean)) {
    const match = block.match(/^([^:\n]{1,40}):\s*([\s\S]*)$/);
    if (match) {
      current = { role: match[1].trim(), content: match[2].trim() };
      turns.push(current);
    } else if (current) {
      current.content += `\n${block.trim()}`;
    } else {
      turns.push({ role: "Speaker", content: block.trim() });
    }
  }
  return turns;
}

function renderTurns(turns) {
  return turns.map((turn) => `${turn.role}: ${turn.content.trim()}`).join("\n\n");
}

function summarizeTurns(turns, budget) {
  if (!turns.length || budget <= 0) return "";
  const notes = turns.map((turn) => {
    const clean = turn.content.replace(/\s+/g, " ").trim();
    const sentence = clean.match(/^.*?[.!?](?:\s|$)/)?.[0] || clean;
    return `• ${turn.role}: ${sentence.trim()}`;
  });
  let summary = `[Earlier interview context — ${turns.length} turns compressed]\n${notes.join("\n")}`;
  if (tokenCount(summary) > budget) summary = summary.slice(0, budget * 4);
  return summary.trim();
}

function compact() {
  const raw = els.input.value.trim();
  if (!raw) return showToast("Paste a transcript first");

  let turns;
  try {
    turns = parseTurns(raw);
  } catch (error) {
    return showToast(error.message);
  }

  const limit = getLimit();
  if (limit <= 0) return showToast("Token reserves exceed the context window");

  const original = renderTurns(turns);
  const originalCount = tokenCount(original);
  let output = original;
  let retained = turns.length;

  if (originalCount > limit) {
    const keep = Math.min(Number(els.recent.value), turns.length);
    let recent = turns.slice(-keep);
    let recentText = renderTurns(recent);

    if (tokenCount(recentText) >= limit) {
      output = recentText.slice(-(limit * 4));
      retained = Math.max(1, Math.round(keep * (limit / tokenCount(recentText))));
    } else {
      const history = turns.slice(0, -keep);
      const summaryBudget = limit - tokenCount(recentText) - 2;
      const summary = summarizeTurns(history, summaryBudget);
      output = summary ? `${summary}\n\n${recentText}` : recentText;
      retained = keep;
    }
    while (tokenCount(output) > limit) output = output.slice(4);
  }

  const finalCount = tokenCount(output);
  const reduction = originalCount ? Math.max(0, Math.round((1 - finalCount / originalCount) * 100)) : 0;

  els.output.textContent = output;
  els.finalTokens.textContent = finalCount.toLocaleString();
  els.limitLabel.textContent = `of ${limit.toLocaleString()} available`;
  els.originalTokens.textContent = originalCount.toLocaleString();
  els.reduction.textContent = `${reduction}%`;
  els.turnsRetained.textContent = `${retained} / ${turns.length}`;
  els.meter.style.width = `${Math.min(100, (finalCount / limit) * 100)}%`;
  els.result.hidden = false;
  setTimeout(() => els.result.scrollIntoView({ behavior: "smooth", block: "start" }), 30);
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  clearTimeout(showToast.timeout);
  showToast.timeout = setTimeout(() => els.toast.classList.remove("show"), 1800);
}

$$(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    $$(".tab").forEach((tab) => tab.classList.remove("active"));
    button.classList.add("active");
    format = button.dataset.format;
    els.formatHint.textContent = format === "json"
      ? "Accepts role/content or speaker/text"
      : "Detects “Speaker: dialogue” turns";
  });
});

[els.model, els.customContext, els.reserve, els.overhead, els.recent]
  .forEach((element) => element.addEventListener("input", updateBudget));

els.input.addEventListener("input", updateInputStats);
$("#compactButton").addEventListener("click", compact);

$("#sampleButton").addEventListener("click", () => {
  format = "text";
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.format === "text"));
  els.input.value = sample;
  updateInputStats();
  els.input.focus();
});

$("#clearButton").addEventListener("click", () => {
  els.input.value = "";
  els.result.hidden = true;
  updateInputStats();
});

els.file.addEventListener("change", async () => {
  const file = els.file.files[0];
  if (!file) return;
  els.input.value = await file.text();
  format = file.name.toLowerCase().endsWith(".json") ? "json" : "text";
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.format === format));
  updateInputStats();
});

$("#copyButton").addEventListener("click", async () => {
  await navigator.clipboard.writeText(els.output.textContent);
  showToast("Copied to clipboard");
});

$("#downloadButton").addEventListener("click", () => {
  const blob = new Blob([els.output.textContent], { type: "text/plain" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "compacted-transcript.txt";
  link.click();
  URL.revokeObjectURL(link.href);
});

updateBudget();
updateInputStats();

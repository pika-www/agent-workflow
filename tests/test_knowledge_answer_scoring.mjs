/** Scorer mechanics only: these controlled answers are not model-quality evidence. */
import assert from "node:assert/strict";
import { scoreKnowledgeAnswers } from "../federation/score-knowledge-answers.mjs";

const make = (case_id, answer, knowledge_status) => ({ case_id, answer,
  model: "controlled-fixture-not-a-model-call", wiki_reads: [{ path: "/topic.md", knowledge_status, truncated: false }] });
const results = [
  make("known-facts", "GS-271，林岚。[Wiki: /topic.md]", "current"),
  make("unknown-budget", "资料未提供，无法确定。[Wiki: /topic.md]", "current"),
  make("stale-source", "证据过期；旧记录为 GS-271，最新代号无法确定。[Wiki: /topic.md]", "stale"),
  make("untracked-source", "来源未追踪，页面记载 GS-271。[Wiki: /topic.md]", "untracked"),
];
const good = await scoreKnowledgeAnswers(results);
assert.equal(good.passed, 4);
assert.equal(good.semantic_judge, false);
assert.equal(good.cases[0].model, "controlled-fixture-not-a-model-call");
assert.equal(good.cases[0].answer, results[0].answer);
const mutated = structuredClone(results);
mutated[1].answer += "预算为10万元。";
mutated[2].answer = mutated[2].answer.replace("/topic.md", "/missing.md");
delete mutated[3].wiki_reads;
const bad = await scoreKnowledgeAnswers(mutated);
assert.equal(bad.failed, 3);
assert.equal(bad.cases[1].checks.forbidden_absent, false);
assert.equal(bad.cases[2].checks.citation_structure, false);
assert.equal(bad.cases[3].error, "missing_actual_wiki_reads");
assert.equal((await scoreKnowledgeAnswers([])).failed, 4);
await assert.rejects(scoreKnowledgeAnswers([results[0], results[0]]), /unique case_id/);
console.log("Frozen answer scorer: expected/forbidden rules, actual answer/model retention, missing cases/receipts and citation checks passed; no model called by this test.");

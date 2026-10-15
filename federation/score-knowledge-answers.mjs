/** Score actual model answers with explicit frozen rules; never call this a semantic judge. */
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { checkWikiCitations } from "./wiki-evidence.mjs";

export async function scoreKnowledgeAnswers(results, fixturePath = new URL("../tests/fixtures/knowledge-answer-eval.json", import.meta.url)) {
  const bytes = await readFile(fixturePath), fixture = JSON.parse(bytes.toString("utf8"));
  if (!Array.isArray(results) || new Set(results.map((item) => item.case_id)).size !== results.length) throw new Error("Answer results must be a unique case_id array.");
  const cases = fixture.cases.map((item) => {
    const result = results.find((candidate) => candidate.case_id === item.id);
    if (!result || typeof result.answer !== "string" || typeof result.model !== "string" || !result.model.trim()) {
      return { id: item.id, passed: false, error: "missing_actual_answer_or_model" };
    }
    if (!Array.isArray(result.wiki_reads)) return { id: item.id, passed: false, error: "missing_actual_wiki_reads" };
    const citations = checkWikiCitations(result.answer, result.wiki_reads);
    const checks = { required_all: item.required_all.every((text) => result.answer.includes(text)),
      required_any: !item.required_any || item.required_any.some((text) => result.answer.includes(text)),
      forbidden_absent: !item.forbidden.some((text) => result.answer.includes(text)),
      citation_structure: citations.status === item.citation_status,
      evidence_status: result.wiki_reads.some((read) => read.path === "/" + fixture.page.path && read.knowledge_status === item.knowledge_status) };
    return { id: item.id, passed: Object.values(checks).every(Boolean), model: result.model, answer: result.answer,
      checks, citation_check: citations, actual_wiki_reads: result.wiki_reads,
      missing_required: item.required_all.filter((text) => !result.answer.includes(text)),
      forbidden_found: item.forbidden.filter((text) => result.answer.includes(text)) };
  });
  return { schema_version: 1, evaluation: fixture.name, fixture_sha256: createHash("sha256").update(bytes).digest("hex"),
    evidence_class: fixture.evidence_class, semantic_judge: false,
    total: cases.length, passed: cases.filter((item) => item.passed).length,
    failed: cases.filter((item) => !item.passed).length, cases, limitations: fixture.limitations };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args[0] !== "--answers" || !args[1] || (args.length !== 2 && !(args.length === 4 && args[2] === "--output"))) {
    throw new Error("Usage: node federation/score-knowledge-answers.mjs --answers answers.json [--output report.json]");
  }
  const report = await scoreKnowledgeAnswers(JSON.parse(await readFile(path.resolve(args[1]), "utf8")));
  const text = JSON.stringify(report, null, 2) + "\n";
  if (args[2] === "--output") await writeFile(path.resolve(args[3]), text); else process.stdout.write(text);
  process.exitCode = report.failed ? 1 : 0;
}

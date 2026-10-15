import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm, symlink } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { createHash } from "node:crypto";
import { runWikiEvidenceEvaluation } from "../federation/evaluate-wiki-evidence.mjs";
import { loadKnowledgeEvidence, inspectWikiFile, checkWikiCitations, canonicalWikiPath, parseKnowledgeEvidence, associateWikiEvidence } from "../federation/wiki-evidence.mjs";

const report = await runWikiEvidenceEvaluation();
assert.equal(report.total, 12);
assert.equal(report.failed, 0, JSON.stringify(report.cases.filter((item) => !item.passed)));
assert.equal(report.model_called, false);
assert.equal(report.cases.find((item) => item.id === "cross-space-source").observed.sources.length, 0);
assert.equal(report.cases.find((item) => item.id === "source-new-version").observed.knowledge_status, "stale");
for (const invalid of ["../other.md", "/../other.md", "//other.md", "_agent_skills/example/SKILL.md", "topic.txt", "bad\\path.md"]) {
  assert.throws(() => canonicalWikiPath(invalid));
}
const root = await mkdtemp(path.join(os.tmpdir(), "wiki-metadata-boundary-"));
const claim={id:'claim-'+ '1'.repeat(32),text:'具体结论',kind:'inference',page_version:'a'.repeat(64),
  status:'current',semantic_review:'pending',references:[{title:'原文',url:'https://example.org/source',
    version:'b'.repeat(64),quote:'x'.repeat(1300),start_line:7,freshness:'local_only'}]};
const snapshot={schema_version:1,space_id:'software',pages:[{path:'topic.md',page_id:'page-topic',
  version:'a'.repeat(64),status:'untracked',reasons:[],evidence:[],claims:[claim,{...claim,id:'claim-'+ '2'.repeat(32),page_version:'c'.repeat(64)}]}]};
const parsed=parseKnowledgeEvidence(snapshot,'software');
const annotated=associateWikiEvidence('/topic.md','a'.repeat(64),parsed);
assert.equal(annotated.claims.length,1,'Old page annotations must not enter the new version context');
assert.equal(annotated.claims[0].kind,'inference');
assert.equal(annotated.claims[0].semantic_review,'pending');
assert.equal(annotated.claims[0].references[0].freshness,'local_only');
assert.equal(annotated.claims[0].references[0].quote.length,1200);
assert.equal(annotated.claims[0].references[0].quote_truncated,true);
assert.equal(associateWikiEvidence('/topic.md','c'.repeat(64),parsed).claims,undefined);
try {
  const config = path.join(root, "config"), wiki = path.join(config, "wiki");
  await mkdir(wiki, { recursive: true });
  const outside = path.join(root, "outside.md");
  await writeFile(outside, "outside-private-marker");
  await symlink(outside, path.join(wiki, "linked.md"));
  await assert.rejects(inspectWikiFile(wiki, "/linked.md"), /符号链接/);
  const metadata = '{"schema_version":1,"space_id":"software","pages":[]}';
  const source = path.join(root, "metadata.json"); await writeFile(source, metadata);
  const sha = createHash("sha256").update(metadata).digest("hex");
  const env = { FEDERATION_SPACE_ID: "software", FEDERATION_KNOWLEDGE_EVIDENCE: source, FEDERATION_KNOWLEDGE_EVIDENCE_SHA256: sha };
  assert.deepEqual((await loadKnowledgeEvidence(config, env)).reasons, ["metadata_path_outside_scope"]);
  env.FEDERATION_KNOWLEDGE_EVIDENCE = path.join(config, "knowledge-evidence.json");
  await symlink(source, env.FEDERATION_KNOWLEDGE_EVIDENCE);
  assert.equal((await loadKnowledgeEvidence(config, env)).metadata_status, "unavailable");
  const citation = checkWikiCitations("[Wiki: /topic.md] [Wiki: /invented.md]", [{ path: "/topic.md", knowledge_status: "stale", truncated: true }]);
  assert.equal(citation.status, "invalid");
  assert.equal(citation.citations[0].knowledge_status, "stale");
  assert.equal(citation.citations[0].truncated, true);
  assert.equal(citation.citations[1].reason, "not_in_recorded_reads");
  assert.equal(citation.semantic_correctness, "not_evaluated");
} finally { await rm(root, { recursive: true, force: true }); }
console.log(`Wiki evidence: ${report.passed}/${report.total} frozen production-path cases passed, plus path/symlink and citation boundaries; no LLM quality claim.`);

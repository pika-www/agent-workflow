/** Frozen deterministic evidence evaluation. This never calls an LLM. */
import { mkdtemp, mkdir, readFile, writeFile, rm } from "node:fs/promises";
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { prefetchWiki } from "./agent-turn.mjs";
import { loadKnowledgeEvidence, checkWikiCitations } from "./wiki-evidence.mjs";

const hash = (text) => createHash("sha256").update(text).digest("hex");
const defaultFixture = new URL("../tests/fixtures/wiki-evidence-cases.json", import.meta.url);

export async function runWikiEvidenceEvaluation(fixturePath = defaultFixture) {
  const fixtureBytes = await readFile(fixturePath);
  const fixture = JSON.parse(fixtureBytes.toString("utf8"));
  const root = await mkdtemp(path.join(os.tmpdir(), "openwiki-frozen-evidence-"));
  const cases = [];
  try {
    for (const item of fixture.cases) {
      const config = path.join(root, item.id), wiki = path.join(config, "wiki");
      await mkdir(wiki, { recursive: true });
      const body = fixture.page.body + (item.mutation === "long_page" ? "已冻结的长资料正文。\r\n".repeat(20000) : "");
      await writeFile(path.join(wiki, fixture.page.path), body);
      const source = { object_type: "source", source_id: fixture.source.source_id,
        version: hash(fixture.source.body), name: fixture.source.name, kind: "local",
        space_id: fixture.space_id, status: "current", checked_at: fixture.source.checked_at,
        freshness: "current", reasons: [], relation: "run_inputs" };
      source.recorded_version = source.version;
      source.current_version = source.version;
      source.current_name = source.name;
      const page = { path: fixture.page.path, page_id: fixture.page.page_id, version: hash(body),
        status: "current", reasons: [], evidence: [source] };
      const metadata = { schema_version: fixture.schema_version, space_id: fixture.space_id, pages: [page] };
      if (item.mutation === "source_new_version") {
        page.status = "stale";
        page.reasons = ["source_version_changed"];
        source.current_version = hash(fixture.source.body + " 来源修订版");
        source.status = "changed";
        source.current_name = "probe-source-v2.md";
      }
      if (item.mutation === "page_version_mismatch") page.version = hash("another page version");
      if (item.mutation === "cross_space") metadata.space_id = "commerce";
      if (item.mutation === "source_cross_space") source.space_id = "commerce";
      if (item.mutation === "source_check_unknown") { source.checked_at = null; source.freshness = "unknown"; }
      const metadataPath = path.join(config, "knowledge-evidence.json"), serialized = JSON.stringify(metadata);
      await writeFile(metadataPath, serialized + (item.mutation === "metadata_pin_tampered" ? " " : ""));
      const environment = { FEDERATION_SPACE_ID: fixture.space_id,
        FEDERATION_KNOWLEDGE_EVIDENCE: metadataPath, FEDERATION_KNOWLEDGE_EVIDENCE_SHA256: hash(serialized) };
      if (item.mutation === "metadata_missing") delete environment.FEDERATION_KNOWLEDGE_EVIDENCE;
      try {
        const provenance = await loadKnowledgeEvidence(config, environment);
        const result = await prefetchWiki(wiki, "银河探针的代号与审核人是什么？", provenance);
        const receipt = result.reads.find((read) => read.path === "/" + fixture.page.path);
        const checks = {
          status_matches: receipt?.knowledge_status === item.expected_status,
          full_page_hash_matches: receipt?.page_version === hash(body),
          source_count_matches: receipt?.sources.length === item.expected_sources,
          reason_matches: !item.expected_reason || receipt?.reasons.includes(item.expected_reason),
          scope_isolated: receipt?.sources.every((entry) => entry.space_id === fixture.space_id),
          prompt_explains_freshness: result.text.includes("不能当作已核验的最新事实"),
          prompt_explains_run_inputs: result.text.includes("不证明页面每项断言均被其支持"),
          prompt_explains_truncation: result.text.includes("引用不能暗示已提供整页内容"),
        };
        if (item.expected_truncated) {
          checks.truncation_reported = receipt?.truncated === true;
          checks.full_hash_distinct_from_excerpt = receipt?.page_version !== receipt?.sha256;
          checks.bounded_excerpt = result.reads.reduce((sum, entry) => sum + entry.excerpt_chars, 0) <= 8000;
        }
        if (item.mutation === "source_new_version") {
          checks.old_and_new_source_versions_preserved = receipt.sources[0]?.recorded_version === hash(fixture.source.body)
            && receipt.sources[0]?.current_version === source.current_version
            && receipt.sources[0]?.current_name === "probe-source-v2.md" && receipt.sources[0]?.status === "changed";
        }
        const citationCheck = item.answer === undefined ? undefined : checkWikiCitations(item.answer, result.reads);
        if (citationCheck) checks.citation_status_matches = citationCheck.status === item.expected_citation_status;
        cases.push({ id: item.id, passed: Object.values(checks).every(Boolean), checks,
          observed: { knowledge_status: receipt?.knowledge_status, reasons: receipt?.reasons,
            page_version: receipt?.page_version, excerpt_sha256: receipt?.sha256,
            truncated: receipt?.truncated, sources: receipt?.sources, citation_check: citationCheck } });
      } catch (error) {
        cases.push({ id: item.id, passed: false, error: String(error.message || error) });
      }
    }
  } finally { await rm(root, { recursive: true, force: true }); }
  return { schema_version: 1, evaluation: "frozen_wiki_evidence", fixture_sha256: hash(fixtureBytes),
    evidence_class: "real_native_file_io_without_model", model_called: false,
    total: cases.length, passed: cases.filter((item) => item.passed).length,
    failed: cases.filter((item) => !item.passed).length, cases,
    limitations: ["冻结用例检验生产读取、归属、版本关联和引用结构。", "未评估模型事实正确性、语义支持、未知问题拒答质量或整体问答能力。"] };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.length !== 0 && !(args.length === 2 && args[0] === "--output")) throw new Error("Usage: node federation/evaluate-wiki-evidence.mjs [--output report.json]");
  const report = await runWikiEvidenceEvaluation();
  const text = JSON.stringify(report, null, 2) + "\n";
  if (args[0] === "--output") await writeFile(path.resolve(args[1]), text);
  else process.stdout.write(text);
  process.exitCode = report.failed ? 1 : 0;
}

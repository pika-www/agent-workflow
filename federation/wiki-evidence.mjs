/** Production provenance checks shared by chat and the frozen evaluation suite. */
import { lstat, readFile, realpath } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";

const MAX_METADATA_BYTES = 8 * 1024 * 1024;
const MAX_PAGE_BYTES = 16 * 1024 * 1024;
const PAGE_STATUSES = new Set(["current", "stale", "untracked", "review_due"]);
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const validHash = (value) => typeof value === "string" && /^[a-f0-9]{64}$/u.test(value);
const validSpace = (value) => typeof value === "string" && /^[a-z][a-z0-9-]{0,63}$/u.test(value);
const scalar = (value, limit = 512) => typeof value === "string" && value.length > 0
  && value.length <= limit && !/[\u0000-\u001f\u007f]/u.test(value);

/** Prefer the requested topic before budgets clip a small, alphabetic whole Wiki. */
export function wikiQuestionScore(item, question='') {
  const words = new Set((question.match(/[a-z][a-z0-9_-]{2,}/giu)||[]).map(s=>s.toLowerCase()));
  const pairs = new Set();
  for(const chunk of question.slice(0,1600).match(/[\u3400-\u9fff]+/gu)||[]) for(let i=0;i<chunk.length-1;i++) {
    const pair=chunk.slice(i,i+2);
    if(!/^(本轮|这轮|归档|资料|根据|解释|一下|意味着|当前|什么|请问|我们|进行|后续)$/.test(pair)) pairs.add(pair);
  }
  const page=String(item.path||'').toLowerCase(),claims=(item.claims||[]).map(c=>c.text||'').join(' ').toLowerCase();
  const body=String(item.text||'').toLowerCase();
  let score=0;
  for(const word of words) score+=(page.includes(word)?100:0)+(claims.includes(word)?60:0)+(body.includes(word)?20:0);
  for(const pair of pairs) score+=(claims.includes(pair)?3:0)+(body.includes(pair)?1:0);
  return score;
}

export function canonicalWikiPath(value) {
  if (!scalar(value, 1024) || value.includes("\\")) throw new Error("Wiki 页面路径无效。");
  const relative = value.startsWith("/") ? value.slice(1) : value;
  if (!relative.endsWith(".md") || relative.split("/").some((part) => !part || part === "." || part === "..")
    || relative.startsWith("_agent_skills/") || relative.startsWith("_agent_templates/")) {
    throw new Error("Wiki 页面路径越过知识范围。");
  }
  return "/" + relative;
}

/** Reject unsafe paths before either the excerpt or full native read. */
export async function inspectWikiFile(root, filePath) {
  const parts = canonicalWikiPath(filePath).slice(1).split("/");
  const rootInfo = await lstat(root);
  if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) throw new Error("Wiki 读取根目录无效。");
  let target = root, info;
  for (const [index, part] of parts.entries()) {
    target = path.join(target, part);
    info = await lstat(target);
    if (info.isSymbolicLink()) throw new Error("Wiki 证据不能经过符号链接。");
    if (index < parts.length - 1 && !info.isDirectory()) throw new Error("Wiki 中间路径不是目录。");
  }
  if (!info.isFile() || await realpath(target) !== path.join(await realpath(root), ...parts)) {
    throw new Error("Wiki 证据不是隔离范围内的普通文件。");
  }
  return { ino: info.ino, size: info.size, mtimeMs: info.mtimeMs };
}

export function sameWikiFile(left, right) {
  return left?.ino === right?.ino && left?.size === right?.size && left?.mtimeMs === right?.mtimeMs;
}

/** A whole-page hash is independent of the excerpt hash and line normalization. */
export async function readWikiVersion(root, filePath, backend, excerptSignature) {
  const before = await inspectWikiFile(root, filePath);
  if (!sameWikiFile(before, excerptSignature)) return { version: null, reason: "page_changed_during_read" };
  if (before.size > MAX_PAGE_BYTES) return { version: null, reason: "full_page_hash_size_limit" };
  const result = await backend.readRaw(filePath);
  const body = result.data?.content;
  if (result.error || typeof body !== "string") return { version: null, reason: "full_page_hash_unavailable" };
  const after = await inspectWikiFile(root, filePath);
  if (!sameWikiFile(before, after) || Buffer.byteLength(body, "utf8") !== before.size) {
    return { version: null, reason: "page_changed_during_read" };
  }
  return { version: sha256(body), reason: null };
}

function unavailable(reason, spaceId = null) {
  return { space_id: spaceId, metadata_status: "unavailable", reasons: [reason], pages: new Map() };
}

/** Validate and normalize only provenance belonging to the trusted host space. */
export function parseKnowledgeEvidence(metadata, expectedSpace) {
  if (!validSpace(expectedSpace)) return unavailable("host_space_unavailable");
  if (!metadata) return unavailable("knowledge_metadata_unavailable", expectedSpace);
  if (metadata.space_id !== expectedSpace) return unavailable("metadata_space_mismatch", expectedSpace);
  if (metadata.schema_version !== 1 || !Array.isArray(metadata.pages) || metadata.pages.length > 10000) {
    return unavailable("knowledge_metadata_invalid", expectedSpace);
  }
  const pages = new Map();
  try {
    for (const page of metadata.pages) {
      const pagePath = canonicalWikiPath(page.path);
      if (pages.has(pagePath) || !scalar(page.page_id) || !validHash(page.version) || !PAGE_STATUSES.has(page.status)
        || !Array.isArray(page.reasons) || !page.reasons.every((reason) => scalar(reason, 2000))
        || !Array.isArray(page.evidence) || page.evidence.length > 256) throw new Error("Invalid page metadata");
      const sources = page.evidence.map((source) => {
        if (source.object_type !== "source" || source.space_id !== expectedSpace || !scalar(source.source_id)
          || !(validHash(source.version) || (source.version === null && ["missing", "conflict", "stale"].includes(source.status)))
          || !scalar(source.name, 1024) || !["web", "local", "published"].includes(source.kind)
          || !["available", "current", "changed", "missing", "conflict", "stale"].includes(source.status)
          || !["current", "review_due", "unknown"].includes(source.freshness)
          || !Array.isArray(source.reasons) || !source.reasons.every((reason) => scalar(reason, 2000))) {
          throw new Error("Invalid source metadata");
        }
        const normalized = { object_type: "source", source_id: source.source_id, version: source.version,
          name: source.name, kind: source.kind, space_id: expectedSpace, status: source.status,
          freshness: source.freshness, reasons: [...source.reasons], relation: "run_inputs",
          checked_at: scalar(source.checked_at, 100) ? source.checked_at : null };
        for (const key of ["url", "upstream_space_id", "upstream_page_id", "upstream_version", "upstream_path",
          "recorded_version", "current_version", "current_name", "check_basis", "publication_version"]) {
          if (source[key] !== undefined) {
            if (source[key] !== null && !scalar(source[key], key === "url" ? 2048 : 1024)) throw new Error("Invalid source attribute");
            normalized[key] = source[key];
          }
        }
        return normalized;
      });
      const claims = (Array.isArray(page.claims) ? page.claims : []).slice(0, 2).filter(claim =>
        claim && !claim.superseded_by && /^claim-[a-f0-9]{32}$/u.test(claim.id) && typeof claim.text === 'string'
        && claim.page_version === page.version && ['fact','inference'].includes(claim.kind) && ['current','review_due','stale'].includes(claim.status)
        && ['pending','approved','rejected'].includes(claim.semantic_review) && Array.isArray(claim.references)
      ).map(claim => ({ id: claim.id, text: claim.text.slice(0, 600), kind: claim.kind,
        status: claim.status, semantic_review: claim.semantic_review,
        references: claim.references.slice(0, 2).filter(ref => ref && typeof ref.quote === 'string'
          && validHash(ref.version) && typeof ref.title === 'string').map(ref => ({
          title: ref.title, url: typeof ref.url === 'string' ? ref.url : null, version: ref.version,
          quote: ref.quote.slice(0, 1200), quote_truncated: ref.quote.length > 1200,
          start_line: ref.start_line, freshness: ref.freshness,
        })) }));
      pages.set(pagePath, { page_id: page.page_id, version: page.version, status: page.status,
        reasons: [...page.reasons], sources, claims });
    }
  } catch {
    return unavailable("knowledge_metadata_invalid", expectedSpace);
  }
  return { space_id: expectedSpace, metadata_status: "validated", reasons: [], pages };
}

/** A bad/missing host snapshot degrades provenance; it never establishes freshness. */
export async function loadKnowledgeEvidence(configRoot, environment) {
  const spaceId = environment.FEDERATION_SPACE_ID;
  const file = environment.FEDERATION_KNOWLEDGE_EVIDENCE;
  const expectedHash = environment.FEDERATION_KNOWLEDGE_EVIDENCE_SHA256;
  if (!file) return unavailable("knowledge_metadata_unavailable", validSpace(spaceId) ? spaceId : null);
  if (!validSpace(spaceId)) return unavailable("host_space_unavailable");
  if (!validHash(expectedHash)) return unavailable("metadata_hash_pin_unavailable", spaceId);
  if (!path.isAbsolute(file) || path.dirname(path.resolve(file)) !== path.resolve(configRoot)
    || path.basename(file) !== "knowledge-evidence.json") return unavailable("metadata_path_outside_scope", spaceId);
  try {
    const before = await lstat(file);
    if (!before.isFile() || before.isSymbolicLink() || before.size > MAX_METADATA_BYTES
      || await realpath(file) !== path.join(await realpath(configRoot), "knowledge-evidence.json")) {
      return unavailable("knowledge_metadata_invalid", spaceId);
    }
    const bytes = await readFile(file);
    const after = await lstat(file);
    if (before.ino !== after.ino || before.size !== after.size || before.mtimeMs !== after.mtimeMs
      || bytes.length !== before.size) return unavailable("metadata_changed_during_read", spaceId);
    if (sha256(bytes) !== expectedHash) return unavailable("metadata_hash_mismatch", spaceId);
    return parseKnowledgeEvidence(JSON.parse(bytes.toString("utf8")), spaceId);
  } catch {
    return unavailable("knowledge_metadata_unavailable", spaceId);
  }
}

export function associateWikiEvidence(filePath, actualVersion, provenance, hashIssue = null) {
  const pagePath = canonicalWikiPath(filePath);
  const result = { page_id: null, page_version: actualVersion, knowledge_status: "untracked",
    reasons: [], sources: [], citation_label: `[Wiki: ${pagePath}]` };
  if (hashIssue || !validHash(actualVersion)) {
    result.reasons = [hashIssue || "full_page_hash_unavailable"];
    return result;
  }
  if (provenance?.metadata_status !== "validated") {
    result.reasons = provenance?.reasons?.length ? [...provenance.reasons] : ["knowledge_metadata_unavailable"];
    return result;
  }
  const page = provenance.pages.get(pagePath);
  if (!page) { result.reasons = ["page_lineage_untracked"]; return result; }
  if (page.version !== actualVersion) { result.reasons = ["page_version_mismatch"]; return result; }
  result.page_id = page.page_id;
  result.claims = page.claims || [];
  result.knowledge_status = page.status;
  result.reasons = [...page.reasons];
  result.sources = page.sources;
  if (!result.sources.length && result.knowledge_status === "current") {
    result.knowledge_status = "untracked";
    result.reasons.push("source_lineage_untracked");
  } else if (result.sources.some((source) => !["available", "current"].includes(source.status)
    || (source.current_version !== undefined && source.current_version !== source.version))
    && result.knowledge_status === "current") {
    result.knowledge_status = "stale";
    result.reasons.push("source_unavailable_or_conflicting");
  } else if (result.sources.some((source) => source.freshness !== "current" || !source.checked_at)
    && result.knowledge_status === "current") {
    result.knowledge_status = "review_due";
    result.reasons.push("source_freshness_not_verified");
  }
  return result;
}

/** Only complete host envelopes can establish what reached the answer model. */
export function suppliedWikiInputs(materials, reads) {
  const recorded = new Map(reads.map(read => [read.path, read]));
  const inputs = [], seen = new Set();
  function envelope(text, origin, clipped = false) {
    if (typeof text !== 'string') return;
    const match = text.match(/<verified_wiki_reads>\s*([\s\S]*?)\s*<\/verified_wiki_reads>/);
    if (!match) return;
    try { for (const item of JSON.parse(match[1]).evidence || []) add(item, origin, clipped); } catch {}
  }
  function add(item, origin, clipped) {
    const read = recorded.get(item?.path);
    if (!read || typeof item.text !== 'string' || !item.text.trim()
      || (item.page_version && item.page_version !== read.page_version)) return;
    const materialHash = sha256(JSON.stringify(item)), key = item.path + ':' + materialHash;
    if (seen.has(key)) return;
    seen.add(key);
    // Claims and quotes here come from the *retained* JSON value, not metadata
    // saved in the prefetch record. Empty or clipped prose is never restored.
    inputs.push({path: item.path, origin, page_id: read.page_id, page_version: read.page_version,
      knowledge_status: item.knowledge_status || read.knowledge_status,
      citation_label: read.citation_label || `[Wiki: ${item.path}]`,
      text: item.text, claims: Array.isArray(item.claims) ? item.claims : [],
      truncated: Boolean(clipped || item.truncated || read.truncated),
      provided_sha256: materialHash, excerpt_sha256: sha256(item.text), excerpt_chars: item.text.length});
  }
  for (const material of materials) {
    if (/^wiki(?::|$)/.test(material.key)) {
      if (material.key === 'wiki') envelope(material.text, material.key, material.truncated);
      else { try { add(JSON.parse(material.text), material.key, material.truncated); } catch {} }
    } else if (/^tools(?::|$)/.test(material.key)) {
      try {
        const item = JSON.parse(material.text);
        if (item.tool === 'wiki_search' && item.result?.status === 'completed') envelope(item.result.text, material.key, material.truncated);
      } catch {}
    }
  }
  return {schema_version: 1, scope: 'answer_model_supplied_materials', inputs,
    omitted_paths: [...recorded.keys()].filter(p => !inputs.some(item => item.path === p))};
}

/** Marker/path validation; semantic support is a separate, bounded check. */
export function checkWikiCitations(answer, reads, supplied = null) {
  const recorded = new Map(reads.map((read) => [read.path, read]));
  const allowed = supplied ? new Map(supplied.inputs.map(item => [item.path, item])) : recorded;
  const citations = [];
  for (const match of String(answer).matchAll(/\[Wiki:\s*([^\]\r\n]*)\]/giu)) {
    const citation = { label: match[0], path: match[1].trim(), valid: false };
    const read = recorded.get(citation.path);
    const input = allowed.get(citation.path);
    if (read && input) {
      Object.assign(citation, { valid: true, knowledge_status: read.knowledge_status,
        page_id: read.page_id, page_version: read.page_version, truncated: input.truncated,
        ...(supplied ? {provided_sha256: input.provided_sha256} : {}) });
    } else citation.reason = read ? "not_supplied_to_answer_model" : "not_in_recorded_reads";
    citations.push(citation);
  }
  const pathMentions = [];
  for (const match of String(answer).matchAll(/\/(?:[\p{L}\p{N}_.-]+\/)*[\p{L}\p{N}_.-]+\.md/gu)) {
    if (citations.some(c => c.path === match[0])) continue;
    const local = String(answer).slice(Math.max(0, match.index - 100), match.index);
    const assertedRead = /读取|读过|看过|查阅|根据|参考|资料来自/.test(local)
      && !/没有|未(?:曾|能)?|尚未|没读|建议|可以|可去/.test(local);
    pathMentions.push({path: match[0], supplied: allowed.has(match[0]), asserted_read: assertedRead,
      valid: !assertedRead || allowed.has(match[0]), reason: assertedRead && !allowed.has(match[0]) ? 'unprovided_page_read_claim' : null});
  }
  const invalidCount = citations.filter(c => !c.valid).length + pathMentions.filter(p => !p.valid).length;
  return { schema_version: 2, scope: supplied ? supplied.scope : "prefetched_wiki_reads_only",
    status: invalidCount ? "invalid" : !citations.length ? "no_citations" : "valid",
    citations, citation_count: citations.length, invalid_count: citations.filter((citation) => !citation.valid).length,
    path_mentions: pathMentions, invalid_path_count: pathMentions.filter(p => !p.valid).length,
    checked_paths: [...allowed.keys()], semantic_correctness: "not_evaluated",
    note: supplied ? "只认可本次回答模型实际收到的正文；路径匹配不证明结论含义正确。" : "仅匹配预读路径，未评判语义支持。" };
}

/** Real native backend reads, no model calls and no imported script execution. */
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, rm, symlink, access } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { parseSkillSelection, prefetchSkills } from "../federation/skill-reads.mjs";
import { prefetchWiki } from "../federation/agent-turn.mjs";

const hash = (value) => createHash("sha256").update(value).digest("hex");
const root = await mkdtemp(path.join(os.tmpdir(), "openwiki-skill-native-"));
const selected = (id) => ({ id, display_name: `${id} 中文名`, version: "sha256:v1",
  selection_reason: "当前 Agent 的任务关键词匹配" });
const frontend = selected("figma-design-to-code");
const tester = selected("client-test");
const writer = selected("documents");

async function fixture(item, files, overrides = {}) {
  const directory = path.join(root, "_agent_skills", item.id);
  const manifest = { id: item.id, space_id: "software-frontend", name: item.id,
    display_name: item.display_name, description: "Imported workflow reference",
    version: item.version, files: {}, dependencies: ["Figma MCP connection"],
    execution_status: "reference_only", ...overrides };
  for (const [relative, content] of Object.entries(files)) {
    const target = path.join(directory, relative);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, content);
    manifest.files[relative] = hash(content);
  }
  const data = { directory, manifest, item, files };
  await saveManifest(data);
  return data;
}
async function saveManifest(data, pin = true) {
  const source = JSON.stringify(data.manifest);
  await writeFile(path.join(data.directory, "manifest.json"), source);
  if (pin) data.item.manifest_sha256 = hash(source);
}

try {
  assert.deepEqual(parseSkillSelection(undefined), []);
  assert.deepEqual(parseSkillSelection("[]"), []);
  assert.equal(parseSkillSelection([frontend, tester, writer]).length, 3);
  for (const invalid of ["bad", "{}", [frontend, frontend], [frontend, tester, writer, selected("four")],
    [{ ...frontend, id: "../escape" }], [{ ...frontend, id: "bad/slash" }], [{ ...frontend, id: "" }],
    [{ ...frontend, version: "bad\nversion" }], [{ ...frontend, version: undefined }],
    [{ ...frontend, display_name: "bad\u0000name" }], [{ ...frontend, manifest_sha256: "bad" }]]) {
    assert.throws(() => parseSkillSelection(invalid));
  }
  assert.deepEqual(await prefetchSkills("/a/path/that/must/not/be/read", []), { reads: [], skills: [], text: "" });

  const marker = path.join(root, "script-was-executed");
  const source = "---\nname: figma-design-to-code\n---\n# NativeSkillMarker\nRefer to references/layout.md and scripts/helper.mjs.\n";
  const files = { "SKILL.md": source, "references/layout.md": "# UnreadResourceMarker\n",
    "scripts/helper.mjs": `import fs from 'node:fs'; fs.writeFileSync(${JSON.stringify(marker)}, 'wrong');\n`,
    "assets/sample.bin": Buffer.from([0, 1, 2, 255]),
    "assets/large.bin": Buffer.alloc(3 * 1024 * 1024, 255) };
  let data = await fixture(frontend, files);
  const other = await fixture(tester, { "SKILL.md": "# UnselectedPrivateSkillMarker\n" });
  await fixture(writer, { "SKILL.md": "# DocumentSkillMarker\n" });
  await writeFile(path.join(root, "index.md"), "# Agent Wiki\nWikiOnlyMarker\n");

  const single = await prefetchSkills(root, [frontend]);
  assert.match(single.text, /NativeSkillMarker/);
  assert.doesNotMatch(single.text, /UnreadResourceMarker|UnselectedPrivateSkillMarker/);
  assert.match(single.text, /references\/layout\.md/);
  assert.match(single.text, /reference_only/);
  assert.match(single.text, /不代表其外部应用/);
  assert.equal(single.skills[0].execution_status, "reference_only");
  assert.deepEqual(single.skills[0].dependencies, ["Figma MCP connection"]);
  assert.equal(single.reads.length, 2);
  assert.ok(single.reads.every((item) => item.skill_id === frontend.id));
  const receipt = single.reads.find((item) => item.path.endsWith("/SKILL.md"));
  assert.equal(receipt.hash_scope, "full_file");
  assert.equal(receipt.sha256, hash(source));
  assert.equal(receipt.full_sha256, receipt.sha256);
  assert.equal(receipt.excerpt_sha256, receipt.sha256);
  assert.equal(receipt.truncated, false);
  assert.equal(await readFile(path.join(data.directory, "SKILL.md"), "utf8"), source);
  await assert.rejects(access(marker));
  assert.ok(single.text.length <= 16000);

  const wiki = await prefetchWiki(root, "NativeSkillMarker UnselectedPrivateSkillMarker");
  assert.equal(wiki.reads.length, 1);
  assert.ok(wiki.reads.every((item) => !item.path.startsWith("/_agent_skills/")));
  assert.doesNotMatch(wiki.text, /_agent_skills|NativeSkillMarker|UnselectedPrivateSkillMarker/);
  await writeFile(path.join(other.directory, "manifest.json"), "unselected invalid manifest");
  assert.match((await prefetchSkills(root, [frontend])).text, /NativeSkillMarker/);
  await saveManifest(other);

  const long = 'LongNativeSkillMarker "\\" 😀\r\n'.repeat(15000);
  data = await fixture(frontend, { ...files, "SKILL.md": long });
  const bounded = await prefetchSkills(root, [frontend, tester, writer]);
  assert.ok(bounded.text.length <= 16000);
  for (const item of [frontend, tester, writer]) assert.ok(bounded.reads.some((read) => read.skill_id === item.id));
  const longReceipt = bounded.reads.find((item) => item.skill_id === frontend.id && item.path.endsWith("/SKILL.md"));
  assert.equal(longReceipt.sha256, hash(long));
  assert.notEqual(longReceipt.excerpt_sha256, longReceipt.full_sha256);
  assert.equal(longReceipt.truncated, true);
  assert.ok(longReceipt.excerpt_chars > 0 && longReceipt.excerpt_chars < long.length);
  const evidence = JSON.parse(bounded.text.split("<verified_skill_reads>\n")[1].split("\n</verified_skill_reads>")[0]);
  const excerpt = evidence.skills[0].evidence.text;
  assert.equal(longReceipt.excerpt_sha256, hash(excerpt));
  assert.ok(!/[\ud800-\udbff]$/u.test(excerpt));
  await writeFile(path.join(data.directory, "SKILL.md"), long + "manual change\n");
  await assert.rejects(prefetchSkills(root, [frontend]), /哈希与 manifest 不符/);

  data = await fixture(frontend, files);
  data.manifest.description = "tampered manifest";
  await saveManifest(data, false);
  await assert.rejects(prefetchSkills(root, [frontend]), /哈希与 manifest 不符/);
  await saveManifest(data);
  data.manifest.version = "another-version"; await saveManifest(data);
  await assert.rejects(prefetchSkills(root, [frontend]), /版本与宿主选择不一致/);
  data.manifest.version = frontend.version;
  data.manifest.id = "another-skill"; await saveManifest(data);
  await assert.rejects(prefetchSkills(root, [frontend]), /身份不一致/);
  data.manifest.id = frontend.id;
  data.manifest.execution_status = "ready_to_execute"; await saveManifest(data);
  await assert.rejects(prefetchSkills(root, [frontend]), /reference_only/);
  data.manifest.execution_status = "reference_only";
  data.manifest.files["../outside.md"] = hash("outside"); await saveManifest(data);
  await assert.rejects(prefetchSkills(root, [frontend]), /路径越界或无效/);
  delete data.manifest.files["../outside.md"];
  delete data.manifest.files["SKILL.md"]; await saveManifest(data);
  await assert.rejects(prefetchSkills(root, [frontend]), /缺少有效文件清单或 SKILL/);

  data = await fixture(frontend, files);
  await rm(path.join(data.directory, "SKILL.md"));
  await assert.rejects(prefetchSkills(root, [frontend]));
  await writeFile(path.join(root, "outside.md"), source);
  await symlink(path.join(root, "outside.md"), path.join(data.directory, "SKILL.md"));
  await assert.rejects(prefetchSkills(root, [frontend]), /符号链接/);
  await rm(path.join(data.directory, "SKILL.md"));
  data = await fixture(frontend, files);
  await rm(path.join(data.directory, "references"), { recursive: true });
  await symlink(root, path.join(data.directory, "references"));
  await assert.rejects(prefetchSkills(root, [frontend]), /符号链接/);
  await rm(path.join(data.directory, "references"));
  data = await fixture(frontend, files);
  data = await fixture(frontend, { ...files, "SKILL.md": "x".repeat(2 * 1024 * 1024) });
  const boundary = await prefetchSkills(root, [frontend]);
  assert.equal(boundary.reads.find((item) => item.path.endsWith("/SKILL.md")).file_bytes, 2 * 1024 * 1024);
  assert.ok(boundary.text.length <= 16000);
  await writeFile(path.join(data.directory, "SKILL.md"), "x".repeat(2 * 1024 * 1024 + 1));
  await assert.rejects(prefetchSkills(root, [frontend]), /大小受限/);
  await assert.rejects(access(marker));

  console.log("Skill native reads passed: selected scopes, max three, real backend, full/excerpt hashes and CRLF, manifest pin, 16000-char envelope, dependencies/reference-only, directory-only resources, no script execution, Wiki exclusion, tamper/missing/traversal/symlink/oversize rejection and source immutability.");
} finally {
  await rm(root, { recursive: true, force: true });
}

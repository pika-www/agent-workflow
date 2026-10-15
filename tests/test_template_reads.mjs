/** Actual native template reads; no model/network calls or permanent file writes. */
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm, symlink } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { parseTemplateSelection, prefetchTemplates, prefetchWiki } from '../federation/agent-turn.mjs';

const hash = (text) => createHash('sha256').update(text, 'utf8').digest('hex');
const selection = (id, framework) => ({ id, framework, source_version: '1.2.3',
  upstream_commit: 'abc123', selection_reason: `用户任务匹配 ${framework}` });
const root = await mkdtemp(path.join(os.tmpdir(), 'openwiki-template-native-'));
const vue = selection('vue-ts', 'vue'), react = selection('react-ts', 'react');
const standard = { id: 'agent-standard', framework: 'general', kind: 'agent-standard',
  source_version: 'local-policy-v1', upstream_commit: '', selection_reason: '本 Agent 默认规范' };
async function fixture(item, files) {
  const directory = path.join(root, '_agent_templates', item.id);
  const manifest = { id: item.id, framework: item.framework, source_version: item.source_version,
    upstream_commit: item.upstream_commit, files: {} };
  if (item.kind) manifest.kind = item.kind;
  for (const [relative, text] of Object.entries(files)) {
    const destination = path.join(directory, relative);
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(destination, text);
    manifest.files[relative] = hash(text);
  }
  await writeFile(path.join(directory, 'manifest.json'), JSON.stringify(manifest));
  return { directory, manifest, files };
}
async function saveManifest(data) {
  await writeFile(path.join(data.directory, 'manifest.json'), JSON.stringify(data.manifest));
}

try {
  assert.deepEqual(parseTemplateSelection(undefined), []);
  assert.deepEqual(parseTemplateSelection('[]'), []);
  const extraSelections = Array.from({ length: 6 }, (_, index) => selection(`extra-${index}`, `other-${index}`));
  assert.equal(parseTemplateSelection([standard, vue, react, ...extraSelections.slice(0, 4)]).length, 7);
  for (const invalid of ['bad', '{}', [vue, vue], [vue, ...extraSelections],
    [standard, vue, react, ...extraSelections], [{ ...standard, id: 'other-standard' }],
    [{ ...vue, id: '../vue-ts' }], [{ ...vue, framework: 'Vue' }],
    [{ ...vue, source_version: 'bad\nversion' }]]) assert.throws(() => parseTemplateSelection(invalid));
  assert.deepEqual(await prefetchTemplates('/a/path/that/is/not/read', []), { reads: [], templates: [], text: '' });

  const vueFiles = {
    'GUIDELINES.md': '# Vue 模板规范\n使用 Vue Composition API 与 script setup。\n',
    'README.md': '# Vue fixture\n',
    'template/package.json': '{"dependencies":{"vue":"^3.5.0"}}\n',
    'template/src/App.vue': '<script setup lang="ts">const title = "VueOnlyMarker";</script>\n<template><h1>{{ title }}</h1></template>\n',
    'template/src/main.ts': 'import { createApp } from "vue";\nimport App from "./App.vue";\ncreateApp(App).mount("#app");\n',
    'template/tsconfig.json': '{"compilerOptions":{"strict":true}}\n',
    'template/vite.config.ts': 'export default {};\n',
  };
  const reactFiles = {
    'GUIDELINES.md': '# React 模板规范\n只使用 React 的组件与 hooks。ReactPrivateMarker\n',
    'template/package.json': '{"dependencies":{"react":"^19.0.0"}}\n',
    'template/src/App.tsx': 'export default function App() { return <h1>ReactOnlyMarker</h1>; }\n',
    'template/src/main.tsx': 'import App from "./App";\n',
  };
  const vueData = await fixture(vue, vueFiles), reactData = await fixture(react, reactFiles);
  await writeFile(path.join(root, 'index.md'), '# 当前知识库\n');
  await writeFile(path.join(root, 'topic.md'), '# 当前主题\nWikiOnlyMarker\n');
  const single = await prefetchTemplates(root, [vue]);
  assert.match(single.text, /VueOnlyMarker/);
  assert.doesNotMatch(single.text, /ReactPrivateMarker|ReactOnlyMarker/);
  assert.ok(single.reads.every((receipt) => receipt.template_id === 'vue-ts'));
  assert.ok(single.reads.some((receipt) => receipt.path.endsWith('/manifest.json')));
  const appRead = single.reads.find((receipt) => receipt.path.endsWith('/App.vue'));
  assert.equal(appRead.hash_scope, 'full_file');
  assert.equal(appRead.sha256, hash(vueFiles['template/src/App.vue']));
  assert.equal(appRead.full_sha256, appRead.sha256);
  assert.equal(appRead.excerpt_sha256, appRead.sha256);
  assert.equal(appRead.truncated, false);
  assert.equal(await readFile(path.join(vueData.directory, 'template/src/App.vue'), 'utf8'), vueFiles['template/src/App.vue']);
  assert.ok(single.text.length <= 8000);

  const both = await prefetchTemplates(root, [vue, react]);
  assert.match(both.text, /VueOnlyMarker/); assert.match(both.text, /ReactOnlyMarker/);
  assert.deepEqual(new Set(both.reads.map((item) => item.template_id)), new Set(['vue-ts', 'react-ts']));
  assert.match(both.text, /Vue 与 React 的规范和代码不能相互混用/);
  assert.ok(both.text.length <= 8000);

  await fixture(standard, {
    'GUIDELINES.md': '# 当前 Agent 职责规范\nGeneralPolicyMarker\n',
    'template/TASK_TEMPLATE.md': '# 本 Agent 的任务输入与交付模板\n先说明目标、来源、输出。\n',
    'template/CHECKLIST.md': '# 检查表\n核对来源、身份、未完成事项。\n',
    'template/LEARNED_RULES.md': '# 已学规则与索引\nWikiRuleMarker，须按当前知识页证据执行。\n',
  });
  const standardOnly = await prefetchTemplates(root, [standard]);
  assert.match(standardOnly.text, /GeneralPolicyMarker/);
  assert.match(standardOnly.text, /WikiRuleMarker/);
  assert.equal(standardOnly.reads.filter((item) => item.provided_as === 'source_excerpt').length, 4);
  assert.ok(standardOnly.reads.every((item) => item.template_id === 'agent-standard'));
  const allThree = await prefetchTemplates(root, [react, standard, vue]);
  assert.deepEqual(allThree.templates.map((item) => item.id), ['agent-standard', 'react-ts', 'vue-ts']);
  assert.match(allThree.text, /GeneralPolicyMarker/); assert.match(allThree.text, /VueOnlyMarker/);
  assert.match(allThree.text, /ReactOnlyMarker/);
  assert.ok(allThree.text.length <= 24000);

  const specialist = { id:'api-contract', framework:'openapi', kind:'specialist',
    source_version:'local-specialist-v1.r1', upstream_commit:'' };
  await fixture(specialist, {
    'GUIDELINES.md':'# 后端接口规范\n',
    'template/openapi.yaml':'openapi: 3.1.0\ninfo:\n  title: ContractReadMarker\n  version: 0.0.0\npaths: {}\n',
    'template/EXAMPLE.md':'# 仅为虚构示例\n',
    'template/CHECKLIST.md':'# 校验方法、参数、状态码\n',
    'template/LEARNED_RULES.md':'# 当前已学规则\n',
  });
  const professional = await prefetchTemplates(root,[standard,specialist]);
  assert.match(professional.text,/ContractReadMarker/);
  assert.ok(professional.reads.some(item=>item.path.endsWith('/openapi.yaml')));
  assert.doesNotMatch(professional.text,/VueOnlyMarker|ReactOnlyMarker/);

  // Framework, style, component and platform recipes each retain actual file
  // evidence under the seven-pack bound; no fabricated reads after truncation.
  const layered = [
    ['angular-ts', 'angular', 'app.component.ts'],
    ['frontend-css', 'css', 'theme.css'],
    ['frontend-less', 'less', 'theme.less'],
    ['frontend-scss', 'scss', 'theme.scss'],
    ['frontend-mui', 'mui', 'MuiForm.tsx'],
    ['wechat-miniprogram', 'wechat', 'pages/index/index.wxml'],
  ].map(([id, framework, filename]) => ({ item: { ...selection(id, framework), kind: 'specialist' }, filename }));
  for (const { item, filename } of layered) {
    await fixture(item, { 'GUIDELINES.md': `# ${item.id} actual guidelines\n`,
      [`template/${filename}`]: `${item.id}ActualSource\n` + '// bounded source excerpt\n'.repeat(1500),
      'template/CHECKLIST.md': '# Host compatibility required\n',
      'template/LEARNED_RULES.md': '# Scoped rules\n' });
  }
  const sevenPacks = await prefetchTemplates(root, [standard, ...layered.map(({ item }) => item)]);
  assert.equal(sevenPacks.templates.length, 7);
  assert.ok(sevenPacks.text.length <= 24000);
  for (const { item, filename } of layered) {
    assert.ok(sevenPacks.text.includes(`${item.id}ActualSource`));
    const receipt = sevenPacks.reads.find((read) => read.path.endsWith(`/template/${filename}`));
    assert.equal(receipt.template_id, item.id);
    assert.equal(receipt.sha256, hash(await readFile(path.join(root, '_agent_templates', item.id, 'template', filename), 'utf8')));
    assert.equal(receipt.truncated, true);
    assert.ok(receipt.excerpt_chars > 0);
    assert.notEqual(receipt.excerpt_sha256, receipt.full_sha256);
  }

  const wiki = await prefetchWiki(root, 'VueOnlyMarker ReactPrivateMarker');
  assert.equal(wiki.reads.length, 2);
  assert.ok(wiki.reads.every((item) => !item.path.startsWith('/_agent_templates/')));
  assert.doesNotMatch(wiki.text, /_agent_templates|VueOnlyMarker|ReactPrivateMarker/);

  // An unselected template may be invalid; it must never be opened or trusted.
  await writeFile(path.join(reactData.directory, 'manifest.json'), 'not-json-and-not-selected');
  assert.match((await prefetchTemplates(root, [vue])).text, /VueOnlyMarker/);
  await saveManifest(reactData);

  // Native raw reads preserve full content beyond the supplied excerpt and line endings.
  const longText = '// escaped "\\"\n'.repeat(12000);
  const large = await fixture(vue, { ...vueFiles, 'template/src/App.vue': longText });
  const bounded = await prefetchTemplates(root, [standard, vue, react]);
  assert.ok(bounded.text.length <= 24000);
  const largeRead = bounded.reads.find((item) => item.path.endsWith('/App.vue'));
  assert.equal(largeRead.sha256, hash(longText));
  assert.equal(largeRead.truncated, true);
  assert.notEqual(largeRead.excerpt_sha256, largeRead.sha256);
  assert.ok(largeRead.excerpt_chars < longText.length);
  await writeFile(path.join(large.directory, 'template/src/App.vue'), longText + '// manual change\n');
  await assert.rejects(prefetchTemplates(root, [vue]), /哈希与 manifest 不符/);
  await fixture(vue, vueFiles);
  const windowsSource = '<template>\r\n  <div>WindowsLineEndings</div>\r\n</template>\r\n';
  await fixture(vue, { ...vueFiles, 'template/src/App.vue': windowsSource });
  const windowsRead = (await prefetchTemplates(root, [vue])).reads.find((item) => item.path.endsWith('/App.vue'));
  assert.equal(windowsRead.sha256, hash(windowsSource));
  await fixture(vue, vueFiles);

  await rm(path.join(vueData.directory, 'template/src/App.vue'));
  await assert.rejects(prefetchTemplates(root, [vue]));
  await writeFile(path.join(root, 'outside.vue'), 'outside');
  await symlink(path.join(root, 'outside.vue'), path.join(vueData.directory, 'template/src/App.vue'));
  await assert.rejects(prefetchTemplates(root, [vue]), /符号链接/);
  await rm(path.join(vueData.directory, 'template/src/App.vue'));
  await fixture(vue, vueFiles);

  vueData.manifest.files['../outside.vue'] = hash('outside');
  await saveManifest(vueData);
  await assert.rejects(prefetchTemplates(root, [vue]), /路径越界或无效/);
  delete vueData.manifest.files['../outside.vue'];
  vueData.manifest.id = 'other'; await saveManifest(vueData);
  await assert.rejects(prefetchTemplates(root, [vue]), /身份不一致/);
  vueData.manifest.id = vue.id; vueData.manifest.source_version = 'changed'; await saveManifest(vueData);
  await assert.rejects(prefetchTemplates(root, [vue]), /版本与宿主选择不一致/);
  vueData.manifest.source_version = vue.source_version;
  delete vueData.manifest.files['GUIDELINES.md']; await saveManifest(vueData);
  await assert.rejects(prefetchTemplates(root, [vue]), /缺少 GUIDELINES/);

  console.log('Template native reads passed: up to seven scoped packs across framework/style/component/platform layers, Vue/React separation, empty selection, full/excerpt hashes and CRLF, 24000-char envelope, Wiki exclusion, missing/tampered/symlink/traversal rejection and source immutability.');
} finally {
  await rm(root, { recursive: true, force: true });
}

/** Real Marked + DOMPurify + JSDOM checks; no public network or model calls. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const upstreamRequire = createRequire(new URL('../openwiki-upstream/package.json', import.meta.url));
const { JSDOM, requestInterceptor } = upstreamRequire('jsdom');
const marked = await import(pathToFileURL(upstreamRequire.resolve('marked')).href);
const pnpm = fileURLToPath(new URL('../openwiki-upstream/node_modules/.pnpm/', import.meta.url));
const purifyPackage = fs.readdirSync(pnpm)
  .filter((name) => /^dompurify@\d/.test(name))
  .sort((a, b) => b.localeCompare(a, 'en', { numeric: true }))
  .map((name) => path.join(pnpm, name, 'node_modules/dompurify'))
  .find((directory) => fs.existsSync(path.join(directory, 'dist/purify.cjs.js')));
assert.ok(purifyPackage, 'Use an already installed DOMPurify package; do not silently replace it with a stub');
const createDOMPurify = upstreamRequire(path.join(purifyPackage, 'dist/purify.cjs.js'));
const source = fs.readFileSync(new URL('../federation/web/agent-chat.js', import.meta.url), 'utf8');
const styles = fs.readFileSync(new URL('../federation/web/agent-chat.css', import.meta.url), 'utf8');
function extract(name) {
  const start = source.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, `Production helper ${name} exists`);
  return source.slice(start, source.indexOf('\n  }', start) + 4);
}

// All automatic resource requests are intercepted before a transport can run.
// Deliberate attack fixtures contain only a harmless window counter.
const resourceRequests = [];
const dom = new JSDOM('<!doctype html><html><head></head><body><main class="ag-dialog"></main></body></html>', {
  url: 'https://openwiki.example.test/', runScripts: 'dangerously',
  resources: { interceptors: [requestInterceptor((request) => {
    resourceRequests.push(request.url);
    return new Response('', { status: 200, headers: { 'content-type': 'text/plain' } });
  })] },
});
const { window } = dom;
window.marked = marked;
window.DOMPurify = createDOMPurify(window);
window.__markdownAttack = 0;
const document = window.document, host = document.querySelector('main');
const style = document.createElement('style'); style.textContent = styles; document.head.append(style);
const context = dom.getInternalVMContext();
vm.runInContext(`
  const state = { room: { id: '${'a'.repeat(32)}' } };
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  ${extract('publicSourceURL')}
  ${extract('markdownBody')}
  ${extract('previewTemplateFile')}
`, context);
const render = (value, className = 'ag-message-text') => {
  const node = context.markdownBody(value, className);
  host.replaceChildren(node);
  return node;
};

try {
  const defaults = { ...marked.defaults };
  const documentMarkdown = [
    '## 项目方案', '', '第一段 **重点**，包含 *强调*、~~旧结论~~ 和 `inline()`。', '',
    '第二段保留文档层次。', '', '- 第一项', '  - 嵌套项', '- 第二项', '',
    '1. 定义目标', '2. 核对范围', '', '> 引用内容', '', '---', '',
    '- [x] 已检查', '- [ ] 待检查', '',
    '| 模块 | 状态 |', '| :--- | ---: |', '| 前端 | 待确认 |', '',
    '```javascript', 'const example = "<script>literal</script>";', '  console.log(example);', '```',
  ].join('\n');
  const body = render(documentMarkdown, 'ag-proposal-content');
  assert.equal(body.classList.contains('ag-markdown'), true);
  assert.equal(body.querySelector('h2').textContent, '项目方案');
  assert.equal(body.querySelector('strong').textContent, '重点');
  assert.equal(body.querySelector('em').textContent, '强调');
  assert.equal(body.querySelector('del').textContent, '旧结论');
  assert.ok(body.querySelector('ul ul li'));
  assert.equal(body.querySelectorAll('ol > li').length, 2);
  assert.equal(body.querySelector('blockquote').textContent.trim(), '引用内容');
  assert.ok(body.querySelector('hr'));
  assert.equal(body.querySelectorAll('input[type="checkbox"]').length, 2);
  const checks = [...body.querySelectorAll('input')];
  assert.ok(checks.every((input) => input.disabled));
  assert.equal(checks[0].checked, true); assert.equal(checks[1].checked, false);
  checks[1].click(); assert.equal(checks[1].checked, false, 'Rendered task-list controls are read-only');
  assert.equal(body.querySelector('pre code').textContent, 'const example = "<script>literal</script>";\n  console.log(example);\n');
  assert.equal(body.querySelector('pre code').className, 'language-javascript');
  assert.deepEqual({ ...marked.defaults }, defaults, 'Chat rendering must not change the Wiki reader global parser options');

  const tableWrap = body.querySelector('.ag-markdown-table');
  assert.ok(tableWrap && tableWrap.firstElementChild.tagName === 'TABLE');
  assert.equal(tableWrap.getAttribute('role'), 'region');
  assert.equal(tableWrap.getAttribute('tabindex'), '0');
  assert.match(tableWrap.getAttribute('aria-label'), /横向滚动/);
  assert.equal(window.getComputedStyle(tableWrap).overflowX, 'auto');
  assert.equal(window.getComputedStyle(body.querySelector('pre')).overflowX, 'auto');
  assert.equal(window.getComputedStyle(body.querySelector('pre')).whiteSpace, 'pre');
  assert.equal(window.getComputedStyle(body).whiteSpace, 'normal');
  assert.equal(body.querySelector('pre').getAttribute('tabindex'), '0');

  // Raw HTML remains readable source text. It must not introduce executable,
  // network-loading, form, named-property or style-bearing nodes.
  const rawAttacks = [
    '<script>window.__markdownAttack += 1</script>',
    '<img src="https://tracker.example.test/pixel" onerror="window.__markdownAttack += 1">',
    '<iframe srcdoc="<script>parent.__markdownAttack += 1</script>"></iframe>',
    '<svg onload="window.__markdownAttack += 1"><a href="javascript:alert(1)">SVG</a></svg>',
    '<form action="https://tracker.example.test/post"><input name="location"><button>Submit</button></form>',
    '<style>body { background:url(https://tracker.example.test/background) }</style>',
    '<a id="ag-send" class="ag-button" href="https://example.com/" onclick="window.__markdownAttack += 1">spoof</a>',
    '<math><mtext><table><mglyph><style><!--</style><img title="--><img src=x onerror=window.__markdownAttack++>">',
  ];
  for (const attack of rawAttacks) {
    const node = render(attack);
    assert.ok(node.classList.contains('ag-markdown'), 'Attack should exercise the real parse/sanitize path, not a silent parser fallback');
    assert.equal(node.querySelectorAll('script,img,iframe,svg,math,form,style,button,input,object,embed').length, 0);
    assert.ok(node.textContent.includes('<'), 'Raw HTML is escaped rather than interpreted');
    for (const element of node.querySelectorAll('*')) {
      assert.ok([...element.attributes].every((attribute) => !/^on/i.test(attribute.name)));
      assert.equal(element.hasAttribute('id'), false); assert.equal(element.hasAttribute('style'), false);
    }
  }
  assert.equal(window.__markdownAttack, 0);

  const badURLs = [
    'javascript:alert%281%29', 'JaVaScRiPt:alert%281%29', 'jav&#x61;script:alert%281%29',
    'java&#10;script:alert%281%29', 'data:text/html,evil', 'file:///etc/passwd', 'vbscript:msgbox%281%29',
    'https://user:secret@example.com/private', '//example.com/protocol-relative', '/api/chat/rooms', '../guide.md', '#chapter',
  ];
  for (const url of badURLs) {
    const node = render(`[保留文字](${url})`);
    assert.equal(node.querySelectorAll('a').length, 0, `Must not create a navigable link for ${url}`);
    assert.ok(node.textContent.includes('保留文字'));
  }
  const links = render('[官方说明](https://example.com/docs?q=1&lang=zh)\n\n<http://example.com/reference>');
  assert.equal(links.querySelectorAll('a').length, 2);
  for (const link of links.querySelectorAll('a')) {
    assert.match(link.href, /^https?:\/\//); assert.equal(link.target, '_blank');
    assert.equal(link.rel, 'noopener noreferrer');
    assert.equal(link.hasAttribute('onclick'), false);
  }
  assert.equal(links.querySelector('a').href, 'https://example.com/docs?q=1&lang=zh');

  // A completed link-first answer uses the existing, room-scoped attachment
  // renderer. Rendering a link must not read or download the actual file.
  const fileURL = `/api/chat/rooms/${'a'.repeat(32)}/files/${'b'.repeat(32)}`;
  const attachment = render(`[下载测试文档](${fileURL})\n\n文件大小约 3 KB。`);
  assert.equal(attachment.querySelector('a')?.getAttribute('href'), fileURL);
  assert.equal(attachment.querySelector('a')?.textContent, '下载测试文档');
  assert.equal(attachment.querySelector('a')?.rel, 'noopener noreferrer');
  const otherRoom = render(`[其他聊天文件](${fileURL.replace('a'.repeat(32), 'c'.repeat(32))})`);
  assert.equal(otherRoom.querySelector('a'), null);
  assert.equal(otherRoom.textContent.trim(), '其他聊天文件');
  assert.deepEqual(resourceRequests, []);

  const images = render('![设计稿](https://images.example.test/preview.png "图片说明")\n\n![不安全](data:image/svg+xml,evil)\n\n![本机文件](file:///private/photo.png)');
  assert.equal(images.querySelectorAll('img,picture,source,svg').length, 0);
  const imageLinks = [...images.querySelectorAll('a')];
  assert.equal(imageLinks.length, 1); assert.equal(imageLinks[0].href, 'https://images.example.test/preview.png');
  assert.match(imageLinks[0].textContent, /图片：设计稿/);
  assert.match(images.textContent, /图片：不安全.*图片：本机文件/s);
  await new Promise((resolve) => window.setTimeout(resolve, 20));
  assert.deepEqual(resourceRequests, [], 'Rendering Markdown and raw HTML images must not automatically load pixels or other resources');

  const exactCode = '  <div class="literal" onclick="example()">& value</div>\n\tconst long = "' + 'x'.repeat(900) + '";\n';
  const code = render('```html\n' + exactCode + '```');
  assert.equal(code.querySelector('pre code').textContent, exactCode);
  assert.equal(code.querySelector('div.literal'), null);
  const wideTable = '| ' + Array.from({ length: 20 }, (_, index) => `列${index}`).join(' | ') + ' |\n'
    + '| ' + Array(20).fill('---').join(' | ') + ' |\n'
    + '| ' + Array(20).fill('long-cell-' + 'x'.repeat(100)).join(' | ') + ' |';
  const wide = render(wideTable);
  assert.equal(wide.querySelectorAll('thead th').length, 20);
  assert.equal(wide.querySelectorAll('tbody td').length, 20);
  assert.equal(wide.querySelector('table').parentElement.className, 'ag-markdown-table');
  assert.equal(window.getComputedStyle(wide.querySelector('.ag-markdown-table')).overflowX, 'auto');
  // JSDOM proves wrapping and CSS policy; real viewport overflow is a browser check.

  // Source previews remain literal, including Markdown and executable-looking HTML.
  const rawFile = '## SKILL.md\n**保留源码标记**\n<script>window.__markdownAttack += 1</script>\n![source](https://images.example.test/source.png)\n';
  const previewRequests = [];
  window.fetch = async (url, options) => {
    previewRequests.push({ url, options });
    return { ok: true, headers: { get: () => String(Buffer.byteLength(rawFile)) }, text: async () => rawFile };
  };
  const output = document.createElement('pre'), button = document.createElement('button');
  host.replaceChildren(button, output);
  await context.previewTemplateFile('/api/spaces/software-uiux/skills/figma/files/SKILL.md', button, output, '技能规范');
  assert.equal(output.textContent, rawFile);
  assert.equal(output.childElementCount, 0); assert.equal(output.classList.contains('ag-markdown'), false);
  assert.equal(previewRequests.length, 1); assert.equal(previewRequests[0].options.method, undefined);
  assert.equal(window.__markdownAttack, 0); assert.deepEqual(resourceRequests, []);

  // Missing dependencies and either exception fail closed to exact readable text.
  const savedMarked = window.marked, savedPurify = window.DOMPurify;
  const fallback = '# 原文\n<script>window.__markdownAttack += 1</script>\n**仍可读**';
  for (const failure of ['no-marked', 'no-purify', 'parse-failed', 'sanitize-failed']) {
    window.marked = failure === 'no-marked' ? undefined : failure === 'parse-failed' ? { Renderer: savedMarked.Renderer, parse() { throw new Error('controlled parser failure'); } } : savedMarked;
    window.DOMPurify = failure === 'no-purify' ? undefined : failure === 'sanitize-failed' ? { sanitize() { throw new Error('controlled sanitizer failure'); } } : savedPurify;
    const node = render(fallback);
    assert.equal(node.textContent, fallback, failure);
    assert.equal(node.childElementCount, 0, failure);
    assert.equal(node.classList.contains('ag-markdown'), false, failure);
  }
  window.marked = savedMarked; window.DOMPurify = savedPurify;
  assert.equal(render(null).textContent, '');
  assert.equal(window.__markdownAttack, 0); assert.deepEqual(resourceRequests, []);
  console.log(`Chat Markdown real-DOM checks passed (Marked ${upstreamRequire('marked/package.json').version}, DOMPurify ${savedPurify.version}, JSDOM ${upstreamRequire('jsdom/package.json').version}): structures, sanitization, safe links, opt-in images with zero requests, code fidelity, local scroll wrappers, literal source previews and safe fallback. Browser viewport layout remains separate.`);
} finally {
  window.close();
}

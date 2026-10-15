import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../openwiki-upstream/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const source = fs.readFileSync(new URL('../federation/web/agent-chat.js', import.meta.url), 'utf8');
const start = source.indexOf('  function renderReportArtifacts(');
const body = source.slice(start, source.indexOf('\n  }', start) + 4);
const dom = new JSDOM('<main></main>', {url:'http://127.0.0.1:18732/', runScripts:'outside-only'});
const context = dom.getInternalVMContext();
vm.runInContext(`const make=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};${body}`, context);
const id = 'a'.repeat(32);
const result = context.renderReportArtifacts({artifacts:[
 {format:'docx',url:`/api/reports/${id}/docx`,filename:'产品分析.docx'},
 {format:'md',url:`/api/reports/${id}/md`},
 {format:'md',url:'javascript:alert(1)'},
 {format:'md',url:'https://evil.example/private'},
 {format:'docx',url:`/api/reports/${id}/md`},
]});
assert.equal(result.querySelectorAll('a').length,2);
assert.equal(result.querySelector('a').textContent,'下载 Word 文档');
assert.equal(result.querySelector('a').download,'产品分析.docx');
assert.equal(context.renderReportArtifacts({}),null);
const failure=context.renderReportArtifacts({artifact_error:'失败 <script>'});
assert.equal(failure.querySelectorAll('script').length,0);
assert.match(failure.textContent,/失败/);
console.log('Report downloads: real local artifacts only, no execution button or external URL.');
dom.window.close();

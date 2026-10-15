import assert from 'node:assert/strict';
import {conversationOnlyScope} from '../federation/conversation-context.mjs';
const positives=['只做本轮文字推演，不使用工具，也不执行任何操作。虚构的项目需要保留历史，请解释发布的先后关系。','只根据这句话回答，不使用工具：标识是 QD-5813。','只依据本会话已有内容，不联网，复述限制。'];
for(const currentQuestion of positives){assert.equal(conversationOnlyScope({currentQuestion}),true);assert.equal(conversationOnlyScope({currentQuestion,toolPolicy:{has_attachments:true}}),false);}
for(const currentQuestion of ['只做本轮文字推演，然后部署这个项目。','只根据这句话回答，再搜索网页。','只根据这句话回答，读取文件。','给我设计一个网站方案。','先解释架构，再实现项目。'])assert.equal(conversationOnlyScope({currentQuestion}),false);
console.log('Explicit text-only scope and attachment/execution exclusions passed.');

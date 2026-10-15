import json
from pathlib import Path
import pytest
from federation.dialogue_scope import conversation_only_scope
from federation.dialogue_scope import bounded_dialogue
from federation.intake import classify_intake
from federation.product_analysis import analysis_goal

LONG='只做本轮文字推演，不使用工具，也不执行任何操作。虚构的青杉项目在发布时有 2 个进行中的请求和 1 个排队请求，必须保留历史与任务结果。请用约 400 字解释入口关闭、排空、版本切换、异常恢复和重新开放的先后关系，并指出哪个阶段不能强制杀掉任务。所有内容都属于设计建议，请不要声称已经实施。'
@pytest.mark.parametrize('question',[LONG,'只根据这句话回答，不使用工具：标识是 QD-5813。','只依据本会话已有内容，不联网，复述限制。'])
def test_explicit_text_answer_skips_proposal_and_unrelated_evidence(question):
 assert classify_intake(question)=='answer'
 assert analysis_goal(question) is None
 assert conversation_only_scope(question)
@pytest.mark.parametrize('question',['只做本轮文字推演，然后部署这个项目。','只根据这句话回答，再搜索网页。','只根据这句话回答，读取文件。','给我设计一个网站方案。','先解释架构，再实现项目。'])
def test_external_or_execution_requests_cannot_use_dialogue_scope(question):
 assert not conversation_only_scope(question)

def test_project_request_still_needs_proposal():
 assert classify_intake('只做本轮文字推演，然后请直接开发这个项目。')=='proposal'
 assert classify_intake('给我设计一个网站方案。')=='proposal'

def test_priority_requires_explicit_scope_and_bounded_response():
 assert bounded_dialogue('只根据这句话回答，不使用工具：标识为 QD-5813；请用一句话复述。')
 assert not bounded_dialogue(LONG)
 assert not bounded_dialogue('一句话说明如何部署，然后开始执行。')
 assert not bounded_dialogue('只根据这句话回答，再搜索网页，用一句话回答。')
 assert not bounded_dialogue('只依据本会话原始记录，简短回答两个项目的最新预算和最早归档暗号。')
 assert bounded_dialogue('只根据这句话回答，不使用工具：限制是不得覆盖历史；请用一句话复述。')

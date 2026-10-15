"""Original, role-specific starter assets; this catalog never writes or runs files.

The host owns persistence, versioning, learned rules, selection and upgrades.
External links below are structural references, not claims of upstream authorship.
"""
from __future__ import annotations

import copy
import csv
import io
import json
from textwrap import dedent

from .frontend_specialties import build_frontend_specialties
from .uiux_templates import build_uiux_templates


def _text(value):
    return dedent(value).strip() + "\n"


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _csv(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue()


def _pack(identifier, name, framework, keywords, description, filename, body,
          rules, checks, example, references=(), extra=None):
    guidelines = ["# " + name + "使用规范", "", description, "",
                  "本套文件为本项目原创适配模板，不是官方提供或复制的成品。所有示例、编号、金额、人物和日期均为虚构占位；待确认项不能当成真实业务事实或执行承诺。",
                  "", "## 专项约定", ""]
    guidelines.extend("- " + rule for rule in rules)
    guidelines.extend(["", "只依据当前 Agent 的实际资料与学习证据填写。文件中的命令、接口和网址只用于描述结构，不授权执行、联网、发布或修改其他项目。保留版本、来源和未完成项。"])
    if references:
        guidelines.extend(["", "## 结构参考", "",
                           "下列官方资料用于核对结构与术语；本模板的组合、示例和约定由本项目编写，不声称是官方模板或当前最新版本。"])
        guidelines.extend("- " + reference for reference in references)
    documents = {
        "GUIDELINES.md": "\n".join(guidelines) + "\n",
        "template/" + filename: body,
        "template/EXAMPLE.md": "# 填写说明与虚构示例\n\n" + _text(example)
            + "\n验收前替换所有 DEMO、example.invalid、REPLACE_ME、待确认等占位。生成文件不代表已经运行、发送、审批或取得业务结果。\n",
        "template/CHECKLIST.md": "# " + name + "检查表\n\n" + "\n".join("- [ ] " + item for item in checks) + "\n",
    }
    if extra:
        documents.update({"template/" + path: value for path, value in extra.items()})
    return {"id": identifier, "name": name, "framework": framework, "kind": "specialist",
            "keywords": list(keywords), "description": description,
            "source_url": "local-policy://specialist/" + identifier,
            "source_version": "local-specialist-v1", "upstream_commit": "", "documents": documents}


OPENAPI_REFERENCE = "https://spec.openapis.org/oas/v3.1.1.html"
KUBERNETES_REFERENCE = "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/"
PLAYWRIGHT_REFERENCE = "https://playwright.dev/docs/writing-tests"
FLUTTER_REFERENCE = "https://docs.flutter.dev/ui/accessibility"

ROLE_PACKS = {
    "central": [_pack(
        "cross-industry-research", "跨行业研究与委派决策", "cross-industry",
        ["跨行业", "研究", "汇总", "委派", "research", "synthesis", "delegation"],
        "把跨领域问题拆成可验收的专业任务，记录证据冲突与中央采用决策。",
        "research_handoff.json", _json({
            "example_only": True, "research_id": "DEMO-RESEARCH-001", "question": "待填写跨领域问题",
            "decision_owner": "待确认", "success_criteria": ["每项结论有归属和可核验来源"],
            "delegations": [{"module": "software", "question": "虚构示例：评估技术可行性",
                             "required_evidence": ["本模块实际来源与版本"], "deliverable": "可行性与缺口", "status": "not_started"}],
            "claim_register": [{"claim_id": "DEMO-CLAIM-001", "statement": "待核实", "source_agent": "待确认",
                                "source_path": "待填写", "confidence_basis": "无证据", "publication_status": "unreviewed"}],
            "conflicts": [], "central_adoption": {"status": "pending_review", "approved_snapshot": None},
            "open_questions": ["是否需要追加资料或其他专业证据？"]}),
        ["按模块直属关系交办，不替专业成员编造结果。", "结论逐条注明来源 Agent、资料版本和适用范围。",
         "冲突同时保存双方证据；未审核子库草稿不能冒充中央正式知识。", "整合失败、待确认和少数意见，不以多数发言代替事实核验。"],
        ["每个子任务有交付物与验收条件", "结论和来源一一对应", "分歧与失败没有被省略", "中央采用有真实审核快照或明确待审核"],
        "将研究问题填入 question；分别为相关模块增加 delegations。只有取得实际回执后更新 status 和 claim_register。示例任务尚未下发。")],
    "software": [_pack(
        "software-architecture-decision", "软件架构与跨专业交付", "software-architecture",
        ["架构", "技术方案", "接口", "软件", "architecture", "adr", "delivery"],
        "连接前端、客户端、后端、运维和测试的接口约定、架构取舍与验证计划。",
        "ARCHITECTURE_DECISION.md", _text("""
        # DEMO-ADR-001：待填写架构决定（虚构占位）

        状态：草案；负责人：待确认；依据版本：待填写。

        ## 目标与约束
        用户路径：待填写。负载、数据保留、端侧兼容和预算：待有来源后填写。

        ## 方案比较
        | 方案 | 数据边界 | 依赖 | 主要收益 | 失败方式 | 证据 |
        | --- | --- | --- | --- | --- | --- |
        | DEMO-A | 待定义 | 待确认 | 待验证 | 待分析 | 未取得 |
        | DEMO-B | 待定义 | 待确认 | 待验证 | 待分析 | 未取得 |

        ## 专业交接
        - 前端：页面状态、无障碍与接口消费约定。
        - App：平台能力、离线策略与版本兼容。
        - 后端：契约、权限、幂等与数据一致性。
        - 运维：环境、观测、回滚与容量证据。
        - 测试：正常、错误、边界、契约和集成验证。

        ## 决策与验证
        选定方案及原因：待评审。否决条件：待明确。
        实际执行记录：无；回滚条件：待定义；未完成项：待逐条登记。
        """),
        ["先写用户路径和约束，再比较方案；不给没有测量依据的容量承诺。", "各端接口、错误状态和身份边界必须一致。",
         "把本地替身、真实服务、设备和发布证据分开。", "每项架构取舍写明替代方案、代价和可回退条件。"],
        ["客户端与服务端契约一致", "幂等、事务和权限责任明确", "有可观测指标与回滚路径", "验证结果与待验证假设区分"],
        "复制 ADR 编号并填写约束；选择真实子任务交付物作为依据。草案中的专业分工不是已完成开发或测试。")],
    "content": [_pack(
        "content-production-pipeline", "内容生产总流程", "content-pipeline",
        ["内容项目", "制作流程", "策划", "制片", "content pipeline", "production plan"],
        "管理选题、策划、美术、拍摄、后期和发布的交接及版权证据。",
        "production_pipeline.csv", _csv(
            ["项目编号", "阶段", "负责专业", "输入版本", "交付物", "依赖阶段", "验收标准", "权利状态", "状态"],
            [["DEMO-CONTENT-001", "选题与剧本", "编剧策划", "待确认", "剧本v草案", "无", "人物目标和情节可复核", "待核查", "未开始"],
             ["DEMO-CONTENT-001", "分镜与视觉", "视觉设计", "剧本待确认", "分镜及风格说明", "选题与剧本", "镜头与场次可对应", "待核查", "未开始"],
             ["DEMO-CONTENT-001", "拍摄", "拍摄制作", "分镜待确认", "原始素材及场记", "分镜与视觉", "镜号和素材清单齐全", "待核查", "未开始"],
             ["DEMO-CONTENT-001", "后期与交付", "后期制作", "素材待确认", "交付母版与字幕", "拍摄", "画音字幕及规格核对", "待核查", "未开始"],
             ["DEMO-CONTENT-001", "发布评估", "内容运营", "母版待确认", "发布稿与指标口径", "后期与交付", "平台配置与版权复核", "待核查", "未开始"]]),
        ["先确定受众、传播目的与内容版本，再下发制作环节。", "剧本、镜号、素材、成片版本相互可追溯。",
         "音乐、字体、人物肖像及第三方素材分别留存授权依据。", "发布动作和效果数据只能由实际回执确认。"],
        ["上下游输入版本一致", "每阶段交付物可定位", "授权和内容审核缺口被记录", "母版与各渠道版本有对应关系"],
        "每行代表一个交接阶段，不是已承诺的排期。待取得实际人员、素材、版权和交付规格后填写。")],
    "commerce": [_pack(
        "retail-launch-coordination", "零售上新与履约协调", "retail-launch",
        ["上新", "电商方案", "履约", "零售", "retail", "launch", "fulfillment"],
        "联结商品、库存、渠道、增长和客服，形成有经营口径与履约约束的上新方案。",
        "RETAIL_LAUNCH_PLAN.md", _text("""
        # DEMO-LAUNCH-001 上新计划（虚构占位）

        目标客群：待确认；渠道：待确认；计划状态：草案。

        ## 商品与收益口径
        SKU范围：待填写。含税/未税、币种、运费和退货成本口径：待核实。
        单件贡献估算 = 售价 - 采购成本 - 渠道费用 - 履约费用 - 可归属营销费用。

        ## 供给与履约
        可售库存、预留库存、在途到货、截单时间、缺货处理：分别填写来源和责任人。

        ## 渠道与实验
        落地页卖点、活动资格、价格展示、流量来源、实验指标：待审核。

        ## 售后承接
        商品问答、服务范围、退款退货依据、升级人工条件：使用已确认政策。

        ## 上线检查与复盘
        商品/供应链/运营/增长/客服分别提交证据；最终发布回执：无。
        实际销量、退款率、库存偏差与贡献变化：未取得数据。
        """),
        ["销量目标须与库存、发货和售后承接能力联动。", "货币、税费、时间窗和成本分摊口径必须写清。",
         "价格、优惠与服务承诺以已核实政策为准，不编造功效或活动资格。", "区分预测、预算、实际订单和回款。"],
        ["库存和计划销量可协调", "贡献计算口径明确", "渠道展示与客服政策一致", "发布与订单结果有回执而非预告"],
        "先将各专业提供的真实SKU、库存与渠道资料补入计划。公式是经营分析结构，示例没有真实售价或收益承诺。")],
    "business": [_pack(
        "business-operating-review", "经营管理评审", "operating-review",
        ["经营评审", "管理", "组织", "经营目标", "business review", "operating model"],
        "把战略、组织、预算、项目和流程的证据整理为可跟踪的经营决定。",
        "operating_review.json", _json({
            "example_only": True, "review_id": "DEMO-REVIEW-001", "period": "待确认", "decision_owner": "待确认",
            "objectives": [{"id": "DEMO-O1", "outcome": "待定义经营结果", "metric": "待定义分子分母与时间窗",
                            "baseline": None, "target": None, "actual": None, "data_source": "未取得"}],
            "resource_review": {"people": "待核查职责与能力", "budget": "待核查可用与已承诺额度", "projects": "待核查里程碑与依赖"},
            "decisions": [{"decision": "待评审", "rationale": "待填写证据", "owner": "待确认", "due": "待确认", "status": "draft"}],
            "risks_and_counterevidence": [], "followup_evidence": [], "approval_status": "not_approved"}),
        ["目标和指标须有稳定定义、时间窗及数据出处。", "组织责任、预算约束、项目依赖同时进入评审。",
         "明确决策者与执行负责人，不把会议意见当作批准。", "缺失数据用空值和待确认标记，不填推测实际数。"],
        ["基线目标实际三者分开", "资源约束已覆盖", "每项决定有责任人与跟踪点", "批准状态有依据"],
        "保留 example_only=true 直到完成真实资料替换。actual=null 表示没有实际数据，不代表零。")],
    "software-frontend": [_pack(
        "frontend-accessible-form", "前端表单交互与验收", "web-form",
        ["前端", "表单", "交互", "可访问性", "frontend", "form", "accessibility", "html"],
        "提供可本地查看的语义化表单及交互状态约定；具体实现另外组合对应框架与样式模板。",
        "form_example.html", _text("""
        <!doctype html>
        <html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>虚构表单模板</title></head>
        <body><main><h1>DEMO 联系方式</h1><p>虚构演示，仅本地校验，不发送数据。</p>
          <form id="demo-form">
            <label for="email">电子邮箱</label>
            <input id="email" name="email" type="email" autocomplete="email" required aria-describedby="email-help">
            <p id="email-help">请输入邮箱格式，例如 demo@example.invalid。</p>
            <button type="submit">检查输入</button><p id="result" role="status" aria-live="polite"></p>
          </form></main>
          <script>
            document.getElementById('demo-form').addEventListener('submit', (event) => {
              event.preventDefault();
              document.getElementById('result').textContent = '虚构演示：格式校验通过，未提交任何业务请求。';
            });
          </script>
        </body></html>
        """),
        ["使用真实label、输入类型和可键盘操作的控件。", "区分初始、校验失败、请求中、成功和服务端错误状态。",
         "客户端校验不替代服务端权限和业务校验。", "模板中的HTML交互可适配框架，但不得混用Vue与React状态机制。"],
        ["输入有可读标签和错误关联", "键盘路径与焦点恢复明确", "重复提交与加载态已设计", "接口失败不显示业务成功"],
        "文件是无外部依赖的HTML演示；表单没有实际服务端请求。用对应Vue或React组件替换实现时，保留标签、状态与验收要求。")],
    "software-app": [
        _pack("flutter-stateful-screen", "Flutter 页面状态", "flutter",
              ["Flutter", "Dart", "移动端", "App", "客户端", "mobile", "screen"],
              "提供含输入、局部状态、资源释放和语义标签的Flutter页面源码。",
              "draft_note_page.dart", _text("""
              import 'package:flutter/material.dart';

              // 虚构示例：只展示本地草稿，不调用API、不持久化。
              class DraftNotePage extends StatefulWidget {
                const DraftNotePage({super.key});
                @override
                State<DraftNotePage> createState() => _DraftNotePageState();
              }
              class _DraftNotePageState extends State<DraftNotePage> {
                final _controller = TextEditingController();
                String _message = 'DEMO：尚未填写';
                @override
                void dispose() { _controller.dispose(); super.dispose(); }
                @override
                Widget build(BuildContext context) => Scaffold(
                  appBar: AppBar(title: const Text('虚构草稿页面')),
                  body: SafeArea(child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      TextField(controller: _controller, maxLength: 120,
                        decoration: const InputDecoration(labelText: '草稿标题')),
                      FilledButton(onPressed: () {
                        final text = _controller.text.trim();
                        setState(() { _message = text.isEmpty ? '请填写标题' : '本地预览：$text'; });
                      }, child: const Text('预览')),
                      Semantics(liveRegion: true, child: Text(_message)),
                    ]),
                  )),
                );
              }
              """),
              ["页面状态与网络/存储层分开，真实异步回调须检查生命周期。", "控制器、监听器和订阅明确释放。",
               "处理安全区域、字体放大、键盘和辅助功能语义。", "说明平台、设备与真实后端验证是否执行，不能用模拟数据冒充业务完成。"],
              ["输入与局部状态一致", "dispose释放资源", "字体放大与语义阅读可检查", "弱网和生命周期测试有记录"],
              "把DraftNotePage作为现有Flutter应用页面使用；示例未声明某个最新Flutter版本，依赖和主题以目标工程为准。",
              references=[FLUTTER_REFERENCE]),
        _pack("swiftui-state-screen", "SwiftUI 输入与页面状态", "swiftui",
              ["SwiftUI", "Swift", "iOS", "iPhone", "Apple"],
              "提供SwiftUI可组合页面与状态绑定的本地示例。",
              "DraftNoteView.swift", _text("""
              import SwiftUI

              // 虚构演示；没有网络请求和业务保存。
              struct DraftNoteView: View {
                  @State private var title = ""
                  @State private var result = "DEMO：未预览"
                  var body: some View {
                      Form {
                          Section("草稿") {
                              TextField("标题", text: $title)
                                  .accessibilityLabel("草稿标题")
                              Button("本地预览") {
                                  let value = title.trimmingCharacters(in: .whitespacesAndNewlines)
                                  result = value.isEmpty ? "请填写标题" : "预览：\\(value)"
                              }
                          }
                          Text(result).accessibilityIdentifier("draft-preview-result")
                      }.navigationTitle("虚构草稿")
                  }
              }
              """),
              ["视图状态只覆盖本视图拥有的数据，外部模型以明确的数据流接入。", "副作用和持久化必须有独立回执。",
               "动态字体、VoiceOver和系统导航作为验收项。", "说明目标系统版本，不凭模板推断真机兼容。"],
              ["状态绑定无双份真值", "空输入路径明确", "可访问性标识稳定", "真机/预览/单元验证分类记录"],
              "将DraftNoteView嵌入目标应用的导航容器；它是组件文件，不是完整Xcode工程，也没有运行或签名记录。"),
        _pack("android-compose-screen", "Android Compose 页面状态", "android-compose",
              ["Android", "Kotlin", "Compose", "Jetpack"],
              "提供Compose状态提升前的独立草稿页面，便于接入目标应用的ViewModel。",
              "DraftNoteScreen.kt", _text("""
              package example.demo

              import androidx.compose.foundation.layout.Column
              import androidx.compose.material3.Button
              import androidx.compose.material3.Text
              import androidx.compose.material3.TextField
              import androidx.compose.runtime.*

              // 虚构演示：仅本地状态，不调用接口或写入存储。
              @Composable
              fun DraftNoteScreen() {
                  var title by remember { mutableStateOf("") }
                  var result by remember { mutableStateOf("DEMO：未预览") }
                  Column {
                      TextField(value = title, onValueChange = { title = it }, label = { Text("草稿标题") })
                      Button(onClick = { result = if (title.isBlank()) "请填写标题" else "预览：${title.trim()}" }) {
                          Text("本地预览")
                      }
                      Text(result)
                  }
              }
              """),
              ["把可组合UI与仓储、网络、导航副作用分开。", "明确旋转、进程重建时需要保留的状态。",
               "不要把remember视为业务持久化。", "检查TalkBack、字体放大和输入法布局。"],
              ["状态归属清楚", "重组不重复执行副作用", "恢复策略与ViewModel边界明确", "设备与构建变体记录完整"],
              "源码假设目标工程已配置Compose和Material3；不要仅凭此文件声称Gradle、模拟器或真机运行通过。"),
    ],
    "software-backend": [_pack(
        "openapi-service-contract", "服务端OpenAPI契约", "openapi",
        ["后端", "接口", "OpenAPI", "API", "contract", "REST", "服务端"],
        "提供可解析的OpenAPI 3.1.1接口契约，包括参数、身份要求、成功与错误结构。",
        "openapi.yaml", _json({
            "openapi": "3.1.1", "info": {"title": "DEMO虚构商品查询API", "version": "0.0.0-demo",
                                          "description": "原创占位契约；没有部署或调用任何服务。"},
            "servers": [{"url": "https://api.example.invalid"}],
            "paths": {"/demo/items/{itemId}": {"get": {
                "operationId": "getDemoItem", "summary": "按ID读取虚构示例商品", "security": [{"bearerAuth": []}],
                "parameters": [{"name": "itemId", "in": "path", "required": True,
                                "schema": {"type": "string", "minLength": 1, "maxLength": 64}}],
                "responses": {
                    "200": {"description": "查询成功", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}}},
                    "400": {"description": "参数不符合约束", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                    "401": {"description": "缺少有效身份"}, "404": {"description": "商品不存在"},
                    "500": {"description": "服务异常，具体消息不得泄露内部敏感信息"}}}}},
            "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
                           "schemas": {
                               "Item": {"type": "object", "required": ["id", "name"], "properties": {
                                   "id": {"type": "string", "examples": ["DEMO-001"]},
                                   "name": {"type": "string", "examples": ["虚构样例商品"]}}},
                               "Error": {"type": "object", "required": ["code", "message"], "properties": {
                                   "code": {"type": "string"}, "message": {"type": "string"}, "requestId": {"type": "string"}}}}}}),
        ["根据真实DTO、校验和业务分支调整契约，不能只对照模板写实现。", "参数位置、必填、类型、响应码与权限分别明确。",
         "写接口还应定义幂等、事务与并发冲突，不能照搬查询接口的假设。", "敏感凭据和真实数据不得写入examples。"],
        ["路径参数全部声明且required=true", "成功与错误响应覆盖真实行为", "schema引用均可解析", "身份要求和数据访问范围经实际代码确认"],
        "openapi.yaml使用YAML 1.2兼容的JSON语法，可由JSON或YAML解析器读取。将example.invalid换成明确授权的目标环境；当前契约固定3.1.1，不声称是最新规范。",
        references=[OPENAPI_REFERENCE])],
    "software-devops": [
        _pack("docker-local-service", "Docker服务封装", "docker",
              ["Docker", "容器", "镜像", "container", "Dockerfile"],
              "提供非root演示服务的Dockerfile及配套Python源码；构建和发布需独立执行证据。",
              "Dockerfile", _text("""
              # 本项目原创虚构演示；未构建、未发布。实际使用前锁定已核验镜像摘要。
              FROM python:3.12-slim
              WORKDIR /app
              COPY app.py /app/app.py
              USER 65532:65532
              EXPOSE 8080
              CMD ["python", "/app/app.py"]
              """),
              ["依赖和基础镜像版本来源需记录，生产发布前按项目规则锁定摘要。", "运行权限、可写目录、网络端口与健康检查明确。",
               "日志写标准输出，不把凭据或业务数据烘焙进镜像。", "镜像构建、扫描、发布与实际运行是不同证据。"],
              ["构建上下文无密钥", "容器不依赖root权限", "端口与应用一致", "健康检查及回滚方案已适配目标环境"],
              "Dockerfile和app.py放在同一构建上下文。演示使用Python标准库HTTP服务，不代表可直接作为生产业务服务器，也未实际构建镜像。",
              extra={"app.py": _text("""
              """ + '\"\"\"Fictional local container fixture; no business API.\"\"\"' + """
              from http.server import BaseHTTPRequestHandler, HTTPServer

              class Handler(BaseHTTPRequestHandler):
                  def do_GET(self):
                      body = b'{"demo":true,"status":"ok"}'
                      self.send_response(200 if self.path == '/healthz' else 404)
                      self.send_header('Content-Type', 'application/json')
                      self.send_header('Content-Length', str(len(body)))
                      self.end_headers()
                      self.wfile.write(body)

              if __name__ == '__main__':
                  HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
              """)}),
        _pack("kubernetes-workload", "Kubernetes工作负载", "kubernetes",
              ["Kubernetes", "K8s", "部署", "deployment", "探针", "运维"],
              "提供Deployment声明和资源、探针、运行身份字段，供按环境校订。",
              "deployment.yaml", _json({
                  "apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "demo-service", "labels": {"app": "demo-service"}},
                  "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "demo-service"}},
                           "template": {"metadata": {"labels": {"app": "demo-service"}}, "spec": {
                               "securityContext": {"runAsNonRoot": True, "runAsUser": 65532},
                               "containers": [{"name": "demo", "image": "example.invalid/demo/replace-me:unpublished",
                                               "ports": [{"containerPort": 8080}],
                                               "resources": {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"cpu": "100m", "memory": "128Mi"}},
                                               "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                                               "readinessProbe": {"httpGet": {"path": "/healthz", "port": 8080}, "initialDelaySeconds": 5},
                                               "livenessProbe": {"httpGet": {"path": "/healthz", "port": 8080}, "initialDelaySeconds": 15}}]}}}}),
              ["selector与pod标签一致，命名空间及服务暴露另行按环境确认。", "资源数字为虚构占位，容量需经真实负载测试。",
               "探针路径必须由目标应用实际提供，避免错误探针造成重启循环。", "配置生成不等于集群应用或发布成功。"],
              ["镜像版本和摘要可追溯", "标签选择器正确", "资源与探针符合实际服务", "回滚和观测证据已安排"],
              "文件使用YAML 1.2兼容的JSON语法。镜像地址故意为不可用占位，未执行kubectl、镜像拉取或集群发布。",
              references=[KUBERNETES_REFERENCE]),
    ],
    "software-testing": [
        _pack("playwright-form-checks", "Playwright表单检查", "playwright",
              ["Playwright", "浏览器测试", "测试", "UI测试", "e2e", "验收"],
              "提供可改造的浏览器交互断言；示例只验证虚构本地HTML。",
              "form.spec.ts", _text("""
              import { test, expect } from '@playwright/test';

              test('DEMO: email required and valid input accepted locally', async ({ page }) => {
                // 虚构fixture；真实业务测试需替换为目标页面及实际服务状态。
                await page.setContent(`<form><label for="email">邮箱</label>
                  <input id="email" type="email" required><button type="submit">提交</button></form>`);
                const email = page.getByLabel('邮箱');
                await expect(email).toBeVisible();
                await page.getByRole('button', { name: '提交' }).click();
                await expect(email).toBeFocused();
                expect(await email.evaluate((element: HTMLInputElement) => element.validity.valueMissing)).toBe(true);
                await email.fill('demo@example.invalid');
                expect(await email.evaluate((element: HTMLInputElement) => element.checkValidity())).toBe(true);
              });
              """),
              ["通过可访问标签与role定位，减少依赖易变CSS结构。", "使用可重试的定位和断言，不用固定睡眠替代可观测条件。",
               "分别验证正常、错误、边界和状态恢复，避免只检查页面存在。", "fixture、Mock、真实后端、浏览器和发布证据分别报告。"],
              ["断言验证用户结果而非仅点击动作", "测试数据与环境可识别", "失败可定位且不会假通过", "真实业务路径与示例fixture区分"],
              "此文件需目标工程已有@playwright/test与对应浏览器环境。当前没有运行测试；示例通过也不能证明真实业务表单正确。",
              references=[PLAYWRIGHT_REFERENCE]),
        _pack("pytest-api-contract", "Pytest接口契约检查", "pytest",
              ["pytest", "接口测试", "Python测试", "API测试", "contract test"],
              "提供明确目标环境后才执行的只读API响应契约测试文件。",
              "test_demo_api.py", _text("""
              """ + '\"\"\"Fictional API contract starter; not an executed test result.\"\"\"' + """
              import json
              import os
              from urllib.request import urlopen
              import pytest

              BASE_URL = os.environ.get('DEMO_API_BASE_URL', '').rstrip('/')
              pytestmark = pytest.mark.skipif(not BASE_URL, reason='明确目标测试环境后再运行；跳过不等于通过')

              def test_demo_item_response_contract():
                  with urlopen(BASE_URL + '/demo/items/DEMO-001', timeout=10) as response:
                      assert response.status == 200
                      assert response.headers.get_content_type() == 'application/json'
                      item = json.load(response)
                  assert isinstance(item, dict)
                  assert isinstance(item.get('id'), str) and item['id']
                  assert isinstance(item.get('name'), str) and item['name']
              """),
              ["测试目标环境必须显式指定，不内置真实服务地址或凭据。", "将认证、测试数据、业务成功码和清理策略按真实接口补齐。",
               "网络错误、跳过、失败和通过分开计数。", "契约检查不能替代权限、业务边界、幂等和并发测试。"],
              ["目标环境经确认", "成功状态与字段类型有断言", "错误与边界场景另有用例", "无环境时明确跳过且不记为通过"],
              "模板只含一个虚构查询场景；需要目标工程pytest依赖并设置已授权测试环境。当前未执行任何网络请求。"),
    ],
    "content-planning": [_pack(
        "screenplay-scene-breakdown", "剧本场次拆解", "screenplay",
        ["剧本", "分场", "故事", "编剧", "screenplay", "scene", "story"],
        "用场次表连接人物目标、冲突、情节作用、台词与制作要求。",
        "scene_breakdown.csv", _csv(
            ["场次", "内外景", "时段", "场景", "人物", "人物目标", "阻力冲突", "情节变化", "关键动作台词", "预计秒数", "道具", "版本状态"],
            [["DEMO-S01", "内景", "日", "虚构工作室", "虚构人物甲", "找到遗漏的草稿", "文件未命名", "发现错误版本", "甲比较两个文件并停下", 20, "虚构笔记本", "草案未拍摄"]]),
        ["每场明确人物想要什么、遇到什么阻力、结尾发生何种变化。", "剧情需要与制作可行性分列，不把台词当成分镜执行记录。",
         "真实人物、史实和专业细节须给出处；虚构部分明确标注。", "角色、地点、时间及道具在相邻场次保持连续。"],
        ["场次编号唯一", "目标冲突变化可区分", "人物与时空连续", "时长为估计且未冒充成片"],
        "每行一场；场次扩展后另存角色表和版本号。20秒只是虚构估计，须以实际表演和剪辑验证。")],
    "content-design": [_pack(
        "visual-creative-brief", "视觉创意与交付说明", "visual-design",
        ["视觉", "设计", "美术", "分镜", "品牌", "creative brief", "visual", "design"],
        "明确视觉目标、信息层级、风格依据与可交付规格。",
        "CREATIVE_BRIEF.md", _text("""
        # DEMO-VISUAL-001 视觉简报（虚构占位）

        ## 目标与受众
        使用场景：待填写；核心信息：待确认；希望引导的操作：待确认。

        ## 信息与版式
        主标题/辅助说明/行动入口：分别填写。阅读顺序：待定义。
        尺寸、留白、安全区域、响应式变体：待确认交付渠道后填写。

        ## 视觉方向
        颜色：待引用品牌色值。字体：待确认授权。图像风格：待给依据。
        参考图URL、可借鉴点与不可复制元素：逐项登记。

        ## 交付清单
        源文件、导出格式、像素尺寸、命名、深浅变体、无障碍检查：待填写。
        版权或授权证据：未取得。设计审核与实际导出记录：无。
        """),
        ["先明确用户理解或操作目标，再定义视觉风格。", "参考作品只作为方向依据，不自动授予复制权。",
         "颜色、字号、对比度、焦点与多尺寸布局分别检查。", "交付规格以实际渠道要求为准，源文件和导出物分开列。"],
        ["核心信息层级清楚", "文字和交互可辨识", "字体图像授权有依据", "源文件与导出规格完整"],
        "可把简报用于页面、海报或分镜美术；每个交付物单列规格。当前文件不代表已有图片、Figma源稿或版权授权。")],
    "content-production": [_pack(
        "shooting-call-sheet", "拍摄通告与现场交接", "shooting",
        ["拍摄", "通告", "场记", "摄影", "call sheet", "shoot", "production"],
        "组织场次、集合、场地、设备和现场交接，记录确认状态。",
        "call_sheet.csv", _csv(
            ["通告编号", "拍摄日", "场次", "集合时间", "场地", "负责人角色", "演员状态", "设备道具", "授权许可", "现场注意", "确认状态"],
            [["DEMO-CALL-001", "待确认日期", "DEMO-S01", "待确认时间", "虚构工作室", "制片待确认", "待确认", "相机及收音待列", "待核查", "现场用电与出入口待查", "未发送未确认"]]),
        ["通告时间、人员和场地只有经确认才能作执行安排。", "私人电话与紧急联系方式放在受控附件，不写入公开模板。",
         "镜号、场次、素材盘和场记编号保持对应。", "现场风险由具备实际职责的人员核查，模板不替代现场判断。"],
        ["集合与开机时间不混淆", "场地和人员确认可追溯", "设备电源收音及备份责任明确", "授权与素材交接状态记录完整"],
        "CSV是通告草案，填写后仍须由制片核对并按实际流程发送；当前没有联系任何人员或预订场地。")],
    "content-postproduction": [_pack(
        "postproduction-delivery", "后期版本与交付", "postproduction",
        ["剪辑", "调色", "字幕", "后期", "交付", "editing", "postproduction", "delivery"],
        "记录素材、剪辑时间码、画音字幕规格和交付版本。",
        "edit_delivery.csv", _csv(
            ["交付编号", "源素材ID", "素材版本", "入点", "出点", "时间码口径", "画面规格", "音频规格", "字幕版本", "色彩空间", "输出文件", "检查状态"],
            [["DEMO-EDIT-001", "DEMO-S01-T01", "虚构素材v0", "00:00:00:00", "00:00:05:00", "25fps非丢帧示例", "待按渠道确认", "待按交付确认", "待制作", "待确认", "DEMO_MASTER_v01.mp4", "未渲染未检查"]]),
        ["入出点和时间码须同时记录帧率与丢帧口径。", "区分源素材、代理、工程和导出母版，保留版本关系。",
         "画面、声音、字幕、色彩、版权与文件可播放性分别验收。", "目录存在或导出进度结束不等于交付文件核验完成。"],
        ["素材与工程版本对应", "时间码和帧率一致", "字幕与音画同步经过检查", "交付文件实际存在且可播放"],
        "示例时间码只用于填写结构，不对应真实素材。待有真实工程和文件后填写导出路径、规格与检查结果。")],
    "content-operations": [_pack(
        "editorial-calendar", "内容运营排期", "editorial-operations",
        ["内容运营", "发布计划", "内容排期", "渠道", "editorial", "calendar", "publishing"],
        "将受众、内容资产、渠道发布与效果口径放入同一排期。",
        "editorial_calendar.csv", _csv(
            ["内容ID", "内容主题", "目标受众", "渠道", "计划时段", "素材版本", "文案CTA", "归因标记", "指标定义", "发布回执", "状态"],
            [["DEMO-POST-001", "虚构工具使用技巧", "待确认用户群", "待确认平台", "待确认", "待确认", "了解操作步骤", "DEMO-CAMPAIGN", "阅读后完成关键动作人数/阅读人数", "无", "草稿未发布"]]),
        ["平台规格和发布权限以实际账号与渠道为准。", "内容主张与来源一致，不虚构功能、口碑或效果。",
         "指标写清分子分母、归因窗口和去重方式。", "计划时间、实际发布回执和实际效果数据分别保存。"],
        ["素材和文案版本匹配", "渠道规格与权益已核对", "CTA与目标一致", "实际发布和效果有证据"],
        "每行表示一个渠道版本。模板不发送帖子、不自动创建排程，也不保证任何阅读或转化结果。")],
    "commerce-merchandising": [_pack(
        "sku-product-sheet", "商品SKU与卖点资料", "merchandising",
        ["SKU", "选品", "商品", "规格", "product", "merchandising", "catalog"],
        "将商品规格、卖点依据、成本口径和上架准备整理为SKU表。",
        "sku_catalog.csv", _csv(
            ["SKU", "商品名", "规格属性", "单位", "币种", "示例采购成本", "示例标价", "税费口径", "卖点", "卖点证据", "库存来源", "状态"],
            [["DEMO-SKU-001", "虚构收纳盒", "蓝色/小号", "个", "CNY", "12.00", "20.00", "待核实含税口径", "分区收纳", "待取得实物或说明依据", "待同步", "未上架"]]),
        ["每个SKU对应唯一可销售规格，条码、单位与包装数量不混淆。", "价格成本注明币种、税费、单位和数据时间。",
         "规格和功效类卖点必须有可核对依据，不把营销想法写成事实。", "样品观察、供应商资料和实测结果分开记录。"],
        ["SKU与规格唯一", "成本和售价口径一致", "商品主张有证据", "供应和上架状态已确认"],
        "12和20是虚构数字，仅演示成本与标价字段。不得用于真实定价或收益判断，填表也不代表已经上架。")],
    "commerce-supplychain": [_pack(
        "inventory-replenishment", "库存与采购补货", "supplychain",
        ["库存", "采购", "补货", "供应链", "inventory", "purchase", "replenishment"],
        "统一现存、预留、在途、需求窗口和补货建议，保留采购批准状态。",
        "replenishment.csv", _csv(
            ["SKU", "单位", "现存", "预留", "在途", "平均日需求", "交期天数", "安全库存", "目标库存", "净可用", "建议补货", "来源时间", "批准状态"],
            [["DEMO-SKU-001", "个", 100, 20, 10, 10, 7, 30, 100, 90, 10, "虚构样例无实际盘点", "未批准未下单"]]),
        ["先统一单位、仓库、时间点和可售状态。", "净可用=现存-预留+有效在途；在途到货需核对是否落在需求窗口内。",
         "建议补货=max(0,目标库存-净可用)，实际还需考虑最小订购、批量、保质期和供应限制。", "建议、批准、采购单、收货与入账分别记录。"],
        ["数量单位与盘点时间明确", "预留和在途没有重复计入", "补货建议考虑交期与批量", "批准采购和到货凭证分开"],
        "样例净可用100-20+10=90，建议补货100-90=10。所有数值虚构，文件不触发采购或库存调整。")],
    "commerce-operations": [_pack(
        "store-campaign-runbook", "店铺活动执行方案", "store-operations",
        ["店铺", "活动", "上架", "优惠", "store", "campaign", "promotion"],
        "把活动资格、商品库存、价格展示、履约和复盘写成可核对的执行草案。",
        "CAMPAIGN_RUNBOOK.md", _text("""
        # DEMO-CAMPAIGN-001 店铺活动草案（虚构）

        ## 活动资格与范围
        人群、渠道、时间窗、SKU、叠加/互斥规则：待核实。实际批准状态：未批准。

        ## 页面与交易口径
        原价/活动价/券后价展示：待核实政策。运费、售后与库存提示：待确认。

        ## 执行依赖
        商品版本、库存预留、发货能力、客服话术、优惠配置复核：逐项关联负责人和证据。

        ## 开始/停止条件
        开始条件：审批与配置复核完成。停止或回退阈值：待定义，不能凭空承诺。

        ## 结果回读
        平台配置ID、实际发布时间、订单口径、异常和退款：未取得实际记录。
        """),
        ["活动条件必须可解释且与平台实际配置一致。", "价格和优惠不只看页面文案，还需核对结算规则。",
         "库存、发货与客服承接同步检查。", "不把拟定活动误写为已发布或已取得订单。"],
        ["活动资格和叠加规则明确", "结算和展示一致", "履约与售后已准备", "实际发布与订单回读有记录"],
        "按真实活动填写条件和平台配置；当前只有草案，不操作店铺、不发券、不调整价格。")],
    "commerce-growth": [_pack(
        "growth-experiment", "增长实验与归因", "growth-experiment",
        ["增长", "实验", "A/B", "投放", "转化", "growth", "experiment", "conversion"],
        "明确假设、分组、指标、护栏和分析计划，防止把噪声当成增长结论。",
        "experiment_plan.json", _json({
            "example_only": True, "experiment_id": "DEMO-EXP-001", "hypothesis": "待以用户证据支持的假设",
            "population": "待明确资格与排除项", "assignment_unit": "待选择用户或其他独立单位",
            "variants": [{"id": "control", "change": "当前已确认版本"}, {"id": "variant", "change": "虚构待验证改动"}],
            "primary_metric": {"name": "待定义", "numerator": "待定义", "denominator": "待定义", "window": "待确认"},
            "guardrails": ["错误率与用户投诉按既定阈值监测"],
            "sample_plan": {"method": "待评审", "minimum_sample": None, "stop_rule": "预先确定，避免随意窥探后提前宣布"},
            "tracking_validation": "not_run", "results": None, "decision": "not_made"}),
        ["先写可证伪假设，再定唯一主要指标和护栏。", "分组单位、曝光记录、归因窗口与数据去重保持一致。",
         "样本量与停止规则在看结果前确定；不以未经检验的短期波动宣称显著。", "预算、实际花费和归因收益分别核对。"],
        ["指标分子分母和窗口明确", "分组与追踪验证完成", "停止规则预先记录", "结果包含不确定性和反证"],
        "results=null明确代表没有实验数据。模板不启动广告、不花预算、不随机分配真实用户，也没有收益承诺。")],
    "commerce-service": [_pack(
        "customer-support-dialogue", "客服核查与回复话术", "customer-support",
        ["客服", "售后", "咨询", "退款", "support", "service", "reply"],
        "把事实核查、回复内容、可承诺边界和升级条件分开，避免未经核实的售后承诺。",
        "support_scripts.csv", _csv(
            ["意图", "需核查字段", "回复草稿", "允许承诺", "升级条件", "数据最小化", "状态"],
            [["DEMO物流查询", "订单归属/承运商最新状态", "您好，我们先核对该订单的最新物流记录；确认后提供查询结果。", "仅提供已核实记录", "状态矛盾或超出已确认时效", "不索取密码或完整支付凭据", "草案未发送"],
             ["DEMO退款咨询", "订单状态/适用政策/申请记录", "请先核对订单适用的售后条件，我们根据已确认政策说明申请路径。", "不承诺未经核实的退款资格或到账时间", "政策争议或系统记录异常", "仅收集完成核查必要字段", "草案未发送"]]),
        ["先验证订单归属与事实，再引用适用政策。", "把安抚语与明确业务承诺分开。",
         "权限外事项升级人工，不编造批准、赔付或到账时间。", "按最小必要原则处理个人信息，不要求密码、验证码或完整支付凭据。"],
        ["事实与政策均有依据", "回复不超出权限", "升级条件具体", "对外发送有明确授权及回执"],
        "话术是可编辑草稿，使用前替换意图与政策来源。当前没有向任何顾客发送消息。")],
    "business-strategy": [_pack(
        "strategy-options", "战略选项与假设", "strategy",
        ["战略", "目标", "机会", "竞争", "strategy", "scenario", "options"],
        "把战略选项、约束、证据、关键假设和可逆试验写清。",
        "STRATEGY_OPTIONS.md", _text("""
        # DEMO-STRATEGY-001 战略选项（虚构占位）

        决策问题：待定义；期限：待确认；资源约束：待以实际数据填写。

        | 选项 | 价值假设 | 所需能力 | 成本口径 | 关键反证 | 可逆验证 |
        | --- | --- | --- | --- | --- | --- |
        | DEMO-A | 待核实 | 待评估 | 待估算并注明出处 | 待寻找 | 小范围验证待设计 |
        | 保持现状 | 待描述 | 当前已确认能力 | 待核实 | 待寻找 | 观察指标待定义 |

        ## 假设登记
        市场、客户、组织和技术假设逐项注明来源、时点与失效条件。

        ## 决策与退出
        推荐选项：未决策。选择理由：待证据。退出条件：待约定。正式批准：无。
        """),
        ["选择问题要包括保持现状这一真实备选。", "事实、预测、假设和价值判断分别标注。",
         "优先识别能改变决定的关键反证。", "把不可逆投入和可逆验证分开，不编造市场份额或收益数字。"],
        ["选项可比较", "关键假设与反证完整", "资源与能力约束明确", "批准和退出条件可追踪"],
        "用真实调查与经营数据填选项表；当前只有战略分析结构，没有决定投资、扩张或预算。")],
    "business-people": [_pack(
        "role-scorecard", "岗位职责与能力评价", "people-role",
        ["岗位", "招聘", "职责", "组织", "人才", "role", "hiring", "scorecard"],
        "用工作结果与可观察行为定义岗位，保留协作边界与评价证据。",
        "role_scorecard.json", _json({
            "example_only": True, "role_id": "DEMO-ROLE-001", "title": "待填写岗位", "mission": "待定义工作价值",
            "outcomes": [{"deliverable": "待填写可观察交付物", "quality_criteria": "待定义", "review_cadence": "待确认"}],
            "responsibilities": ["待填写本岗位直接负责事项"], "decision_rights": ["待明确审批与自主决策边界"],
            "interfaces": [{"role": "协作岗位待确认", "handoff": "交接物待定义"}],
            "evaluation": [{"competency": "与岗位任务有关的能力", "observable_behavior": "可核查行为", "evidence": [], "rating": None}],
            "exclusions": ["不以与工作无关的个人属性替代能力证据"], "approval_status": "draft"}),
        ["评价基于岗位相关结果和可观察行为，不凭个人印象下结论。", "工作职责、决策权和跨岗位协作边界分开。",
         "评价标准保持一致，缺少证据标记待观察。", "个人资料与面试记录按实际权限保存，不写入公开示例。"],
        ["职责与岗位目标一致", "指标是可观察的岗位行为", "评价证据可追溯", "个人资料和审批边界明确"],
        "空rating表示没有评价，不代表零分。模板不发布招聘、不承诺录用或薪酬，不评价任何真实个人。")],
    "business-finance": [_pack(
        "budget-variance", "预算与差异分析", "budget",
        ["预算", "成本", "财务", "差异", "budget", "cost", "variance"],
        "记录数量、单价、预算、实际与差异，明确货币和计算口径。",
        "budget_variance.csv", _csv(
            ["预算项", "成本中心", "币种", "数量", "单价", "预算金额", "实际金额", "实际减预算", "责任角色", "依据", "状态"],
            [["DEMO设备租用", "虚构项目A", "CNY", 2, 100, 200, "", "", "待确认", "虚构示例非报价", "草案"],
             ["DEMO资料整理", "虚构项目A", "CNY", 3, 50, 150, "", "", "待确认", "虚构示例非报价", "草案"]]),
        ["注明币种、期间、含税口径和成本归属。", "预算金额=数量×单价；差异=实际金额-预算金额，并解释正负含义。",
         "实际尚未取得时保留空值，不以零值代替。", "预算、批准、采购承诺、付款和会计记录分别核对。"],
        ["金额计算与单位一致", "实际数有凭证或来源", "空白没有被当作零", "差异解释和批准记录完整"],
        "CSV第F列=第D列×第E列，可在电子表格F2填=D2*E2；H2可填=IF(G2=\"\",\"\",G2-F2)。示例金额虚构且未获批准，不是报价、付款或投资建议。")],
    "business-projects": [_pack(
        "project-dependency-plan", "项目依赖与验收计划", "project-plan",
        ["项目", "里程碑", "排期", "依赖", "project", "milestone", "delivery"],
        "将任务依赖、负责人、验收条件和风险纳入可更新的交付计划。",
        "project_plan.csv", _csv(
            ["任务ID", "任务名称", "前置任务", "负责角色", "估计工作日", "计划开始", "计划结束", "验收条件", "实际证据", "状态"],
            [["DEMO-T01", "确认范围", "", "项目负责人待确认", 1, "待确认", "待确认", "范围及排除项已确认", "无", "未开始"],
             ["DEMO-T02", "形成交付草案", "DEMO-T01", "执行负责人待确认", 2, "待确认", "待确认", "草案包含全部约定项", "无", "未开始"],
             ["DEMO-T03", "验收与复盘", "DEMO-T02", "验收人待确认", 1, "待确认", "待确认", "证据与缺口逐条记录", "无", "未开始"]]),
        ["拆分到可交付、可验收的任务，而非模糊活动。", "工作量、工期、依赖和资源约束分别管理。",
         "变更记录影响、批准人和新基线，不直接覆盖历史承诺。", "完成状态须有实际交付物与验收证据。"],
        ["依赖不存在循环或缺失", "每项任务有负责人和完成标准", "风险变更有记录", "实际完成与计划日期分开"],
        "1/2/1天均是虚构估计，不是交付承诺。补入真实资源、日历和依赖后再形成基线。")],
    "business-operations": [_pack(
        "process-sop", "流程SOP与异常处理", "process-sop",
        ["流程", "SOP", "运营规范", "交接", "process", "procedure", "operations"],
        "定义触发、角色、输入输出、异常和过程证据，形成可执行但未自动执行的SOP。",
        "PROCESS_SOP.md", _text("""
        # DEMO-SOP-001 资料交接流程（虚构示例）

        版本：草案v0；流程所有者：待确认；生效批准：未批准。

        ## 触发与前提
        触发：收到明确交接请求。前提：交接双方权限、资料范围和用途已确认。

        ## 输入与输出
        输入：资料清单、版本、用途与保密级别。输出：接收回执、缺口清单、后续责任人。

        ## 步骤与记录
        1. 发起人逐项列出资料版本与允许使用范围，记录请求编号。
        2. 接收人核对实际文件、数量和完整性，不能仅凭目录判定收到正文。
        3. 有差异时登记缺口并反馈；无差异时保存确认回执。
        4. 流程所有者按实际记录复盘时效与返工原因。

        ## 异常与升级
        权限不符、内容缺失、版本冲突：暂停该项并联系已确定负责人；不要自行扩大权限。

        ## 度量与修订
        交接周期、缺口率、重复返工按统一口径统计。实际执行记录：无。
        """),
        ["流程触发和退出条件必须明确，避免无止境循环。", "每一步指定角色、输入、动作、输出和留痕。",
         "异常与权限外事项有确定升级路径。", "流程版本修订基于真实反馈，保留旧版本和生效记录。"],
        ["步骤有输入输出与责任角色", "异常升级可执行", "权限和数据边界明确", "生效与执行回执真实存在"],
        "本例是资料交接SOP；替换成目标流程时保留触发、角色、证据、异常与版本栏。文件不自动发送资料或修改权限。")],
}

ROLE_PACKS["software-frontend"].extend(build_frontend_specialties(_pack))
ROLE_PACKS["software-uiux"] = build_uiux_templates(_pack)
from .web_ecosystem_templates import build_web_ecosystem_templates
from .frontend_sources import APP_RECIPE_IDS

ROLE_PACKS["software-frontend"].extend(build_web_ecosystem_templates(_pack))
# Each Agent receives a separately persisted and independently versioned copy.
# Sharing a recipe definition does not permit reading another Agent's files.
ROLE_PACKS["software-app"].extend(copy.deepcopy([
    pack for pack in ROLE_PACKS["software-frontend"] if pack["id"] in APP_RECIPE_IDS
]))


def packs_for_agent(store, space):
    """Return independent packs for a real Agent, inheriting the nearest known role.

    The current Agent name and scope are rendered into each returned guideline.
    Catalog constants remain unchanged, and no state files are created here.
    """
    current = store.space(space)
    candidate, visited = current, set()
    while candidate["id"] not in ROLE_PACKS:
        identifier = candidate["id"]
        if identifier in visited or not candidate.get("parent_id"):
            raise ValueError("无法为该 Agent 找到有效的专项模板角色")
        visited.add(identifier)
        candidate = store.space(candidate["parent_id"])
    role_id = candidate["id"]
    packs = copy.deepcopy(ROLE_PACKS[role_id])
    for pack in packs:
        pack["documents"]["GUIDELINES.md"] += (
            "\n## 当前挂载职责\n\n"
            f"当前 Agent：{current['name']}（{current['id']}）。\n"
            f"职责：{current.get('description', '')}。\n"
            + (f"专项结构继承自 {candidate['name']}（{role_id}）；按当前细分职责校订，超出职责的字段不自动套用。\n"
               if space != role_id else "专项结构直接对应本 Agent；实际结论仍以本库已读取的来源为准。\n"))
    return packs

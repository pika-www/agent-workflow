"""Role assets, structured file formats and metadata; no business execution."""
import ast
import copy
import csv
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import unittest

from federation.core import FederationStore
from federation.specialist_catalog import ROLE_PACKS, packs_for_agent


class SpecialistCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.store = FederationStore(root / "data", project_root=root / "project")
        cls.store.init()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_every_default_agent_has_a_distinct_specialist_pack(self):
        self.assertEqual(set(ROLE_PACKS), set(FederationStore._builtin_definitions()))
        self.assertEqual(len(ROLE_PACKS), 26)
        self.assertEqual(sum(len(packs) for packs in ROLE_PACKS.values()), 55)
        role_primary_content = set()
        for identifier in ROLE_PACKS:
            packs = packs_for_agent(self.store, identifier)
            self.assertTrue(packs, identifier)
            self.assertIn(identifier, packs[0]["documents"]["GUIDELINES.md"])
            primary = [body for name, body in packs[0]["documents"].items()
                       if name not in {"GUIDELINES.md", "template/EXAMPLE.md", "template/CHECKLIST.md"}]
            self.assertTrue(primary, identifier)
            role_primary_content.add(primary[0])
        self.assertEqual(len(role_primary_content), len(ROLE_PACKS), "Roles must not share a generic task-file copy")

    def test_pack_ids_paths_metadata_and_authorship_are_safe(self):
        seen = set()
        for role, packs in ROLE_PACKS.items():
            for pack in packs:
                self.assertRegex(pack["id"], r"^[a-z][a-z0-9-]{0,63}$")
                self.assertNotIn((role, pack["id"]), seen)
                seen.add((role, pack["id"]))
                self.assertRegex(pack["framework"], r"^[a-z][a-z0-9-]{0,39}$")
                self.assertEqual(pack["kind"], "specialist")
                self.assertEqual(pack["source_version"], "local-specialist-v1")
                self.assertEqual(pack["upstream_commit"], "")
                self.assertTrue(pack["source_url"].startswith("local-policy://specialist/"))
                self.assertTrue(all(isinstance(word, str) and word.strip() for word in pack["keywords"]))
                self.assertGreaterEqual(len(pack["documents"]), 4)
                self.assertIn("原创适配", pack["documents"]["GUIDELINES.md"])
                self.assertIn("虚构", pack["documents"]["GUIDELINES.md"])
                self.assertIn("不代表已经运行", pack["documents"]["template/EXAMPLE.md"])
                self.assertGreaterEqual(pack["documents"]["template/CHECKLIST.md"].count("- [ ]"), 4)
                folded = set()
                for name, body in pack["documents"].items():
                    self.assertFalse(PurePosixPath(name).is_absolute())
                    self.assertNotIn("..", PurePosixPath(name).parts)
                    self.assertNotIn("\\", name)
                    self.assertNotIn(name.casefold(), folded)
                    folded.add(name.casefold())
                    self.assertTrue(name == "GUIDELINES.md" or name.startswith("template/"))
                    self.assertIsInstance(body, str)
                    self.assertTrue(body.strip())
                    self.assertNotIn("\x00", body)

    def test_csv_tables_and_json_yaml_subset_are_valid(self):
        parsed_count = {"csv": 0, "json": 0, "yaml": 0}
        for packs in ROLE_PACKS.values():
            for pack in packs:
                for filename, body in pack["documents"].items():
                    if filename.endswith(".csv"):
                        rows = list(csv.reader(io.StringIO(body), strict=True))
                        self.assertGreaterEqual(len(rows), 2, filename)
                        self.assertEqual(len(rows[0]), len(set(rows[0])), filename)
                        self.assertTrue(all(len(row) == len(rows[0]) for row in rows), filename)
                        self.assertTrue(any("DEMO" in field for row in rows[1:] for field in row), filename)
                        parsed_count["csv"] += 1
                    elif filename.endswith((".json", ".yaml")):
                        # These YAML files intentionally use the JSON subset of
                        # YAML 1.2, so stdlib parsing proves their concrete syntax.
                        value = json.loads(body)
                        self.assertIsInstance(value, dict)
                        parsed_count["yaml" if filename.endswith(".yaml") else "json"] += 1
        self.assertGreaterEqual(parsed_count["csv"], 9)
        self.assertGreaterEqual(parsed_count["json"], 4)
        self.assertEqual(parsed_count["yaml"], 2)

    def test_openapi_parameters_references_and_kubernetes_selector_align(self):
        contract = json.loads(ROLE_PACKS["software-backend"][0]["documents"]["template/openapi.yaml"])
        self.assertEqual(contract["openapi"], "3.1.1")
        self.assertEqual(contract["servers"][0]["url"], "https://api.example.invalid")
        for route, operations in contract["paths"].items():
            for operation in operations.values():
                declared = {p["name"] for p in operation.get("parameters", []) if p["in"] == "path" and p["required"]}
                self.assertEqual(set(re.findall(r"\{([^}]+)\}", route)), declared)
        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    self.assertTrue(value["$ref"].startswith("#/"))
                    target = contract
                    for component in value["$ref"][2:].split("/"):
                        target = target[component]
                    self.assertIsInstance(target, dict)
                for item in value.values():
                    check_refs(item)
            elif isinstance(value, list):
                for item in value:
                    check_refs(item)
        check_refs(contract)
        workload = json.loads(ROLE_PACKS["software-devops"][1]["documents"]["template/deployment.yaml"])
        self.assertEqual(workload["apiVersion"], "apps/v1")
        self.assertEqual(workload["spec"]["selector"]["matchLabels"], workload["spec"]["template"]["metadata"]["labels"])
        for container in workload["spec"]["template"]["spec"]["containers"]:
            ports = {item["containerPort"] for item in container["ports"]}
            self.assertIn(container["readinessProbe"]["httpGet"]["port"], ports)
            self.assertIn(container["livenessProbe"]["httpGet"]["port"], ports)

    def test_actual_code_files_and_python_syntax(self):
        expected = {".dart", ".swift", ".kt", ".ts", ".py", ".html"}
        found = set()
        for packs in ROLE_PACKS.values():
            for pack in packs:
                for filename, body in pack["documents"].items():
                    suffix = PurePosixPath(filename).suffix
                    found.add(suffix)
                    if suffix == ".py":
                        ast.parse(body, filename=filename)
        self.assertTrue(expected.issubset(found))
        self.assertIn("COPY app.py", ROLE_PACKS["software-devops"][0]["documents"]["template/Dockerfile"])
        self.assertIn("StatefulWidget", ROLE_PACKS["software-app"][0]["documents"]["template/draft_note_page.dart"])
        self.assertIn("@Composable", ROLE_PACKS["software-app"][2]["documents"]["template/DraftNoteScreen.kt"])

    def test_typescript_fixture_parses_with_existing_esbuild_without_execution(self):
        root = Path(__file__).resolve().parents[1]
        esbuild = root / "openwiki-tools/node_modules/esbuild/lib/main.js"
        node = shutil.which("node") or "/Users/winfield/.nvm/versions/node/v24.18.0/bin/node"
        if not esbuild.is_file() or not Path(node).is_file():
            self.skipTest("Existing esbuild/Node runtime unavailable; no dependency installation")
        source = ROLE_PACKS["software-testing"][0]["documents"]["template/form.spec.ts"]
        script = ("const esbuild = await import(process.argv[1]); let text=''; "
                  "for await(const chunk of process.stdin) text+=chunk; "
                  "await esbuild.transform(text,{loader:'ts'}); process.stdout.write('parsed');")
        result = subprocess.run([node, "--input-type=module", "-e", script, esbuild.as_uri()],
                                input=source, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "parsed")

    def test_keywords_select_distinct_app_devops_and_testing_packs(self):
        examples = [
            ("software-app", "需要Flutter页面", "flutter-stateful-screen"),
            ("software-app", "用SwiftUI编写视图", "swiftui-state-screen"),
            ("software-app", "Android Compose界面", "android-compose-screen"),
            ("software-devops", "Dockerfile封装服务", "docker-local-service"),
            ("software-devops", "Kubernetes探针", "kubernetes-workload"),
            ("software-testing", "Playwright浏览器测试", "playwright-form-checks"),
            ("software-testing", "pytest接口测试", "pytest-api-contract"),
        ]
        for role, query, expected in examples:
            scored = [(sum(word.casefold() in query.casefold() for word in pack["keywords"]), pack["id"])
                      for pack in ROLE_PACKS[role]]
            self.assertGreater(max(score for score, _ in scored), 0)
            self.assertEqual(max(scored)[1], expected)

    def test_custom_descendant_inherits_nearest_role_and_renders_own_scope(self):
        definitions = copy.deepcopy(FederationStore._builtin_definitions())
        definitions["custom-mobile"] = {"id": "custom-mobile", "name": "客户移动端", "description": "客户移动端登录与离线场景", "parent_id": "software-app"}
        class ReadOnlyStore:
            def space(self, identifier):
                return definitions[identifier]
        packs = packs_for_agent(ReadOnlyStore(), "custom-mobile")
        self.assertEqual(len(packs), len(ROLE_PACKS["software-app"]))
        self.assertIn("客户移动端（custom-mobile）", packs[0]["documents"]["GUIDELINES.md"])
        self.assertIn("登录与离线场景", packs[0]["documents"]["GUIDELINES.md"])
        self.assertIn("继承自", packs[0]["documents"]["GUIDELINES.md"])
        packs[0]["documents"]["GUIDELINES.md"] = "modified local return"
        self.assertNotEqual(ROLE_PACKS["software-app"][0]["documents"]["GUIDELINES.md"], "modified local return")

    def test_catalog_calls_do_not_persist_or_mutate_state(self):
        def snapshot():
            return {path.relative_to(self.store.base).as_posix(): path.read_bytes()
                    for path in self.store.base.rglob("*") if path.is_file()}
        before = snapshot()
        for space in ROLE_PACKS:
            packs_for_agent(self.store, space)
        self.assertEqual(before, snapshot())


if __name__ == "__main__":
    unittest.main()

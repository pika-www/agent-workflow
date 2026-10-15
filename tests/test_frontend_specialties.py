"""Frontend recipe assets and local compiler syntax checks.

The TypeScript/esbuild checks deliberately do not claim Angular AOT, external
component-library type checking, Tailwind expansion, Less or Sass compilation.
"""
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import unittest

from federation.frontend_specialties import build_frontend_specialties
from federation.specialist_catalog import ROLE_PACKS, _pack


ROOT = Path(__file__).resolve().parents[1]


class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class FrontendSpecialtiesTest(unittest.TestCase):
    def setUp(self):
        self.packs = {item["id"]: item for item in build_frontend_specialties(_pack)}

    def test_catalog_exposes_framework_style_and_component_recipes(self):
        expected = {
            "angular-ts": "angular", "frontend-css": "css", "frontend-less": "less",
            "frontend-scss": "scss", "frontend-tailwind": "tailwind", "frontend-bootstrap": "bootstrap",
            "frontend-element-plus": "element-plus", "frontend-ant-design": "ant-design", "frontend-mui": "mui",
        }
        self.assertEqual({key: item["framework"] for key, item in self.packs.items()}, expected)
        frontend = {item["id"]: item for item in ROLE_PACKS["software-frontend"]}
        self.assertTrue(set(expected).issubset(frontend))
        self.assertEqual(frontend["frontend-accessible-form"]["documents"]["template/form_example.html"].count("<form"), 1)
        for item in self.packs.values():
            self.assertEqual(item["kind"], "specialist")
            self.assertTrue(item["source_url"].startswith("local-policy://"))
            self.assertEqual(item["upstream_commit"], "")
            self.assertIn("原创适配", item["documents"]["GUIDELINES.md"])
            self.assertIn("https://", item["documents"]["GUIDELINES.md"])

    def test_factory_returns_independent_metadata_and_documents(self):
        first = build_frontend_specialties(_pack)
        second = build_frontend_specialties(_pack)
        first[0]["documents"]["GUIDELINES.md"] = "local edit"
        first[0]["keywords"].append("local edit")
        self.assertNotEqual(first, second)
        self.assertNotIn("local edit", second[0]["keywords"])
        self.assertNotIn("local edit", second[0]["documents"]["GUIDELINES.md"])

    def test_angular_links_bootstrap_and_component_assets_consistently(self):
        files = self.packs["angular-ts"]["documents"]
        component = files["template/src/app/demo-contact.component.ts"]
        self.assertIn("standalone: true", component)
        self.assertIn("signal(", component)
        for path in re.findall(r"(?:templateUrl|styleUrl):\s*['\"]([^'\"]+)", component):
            self.assertIn("template/src/app/" + path.removeprefix("./"), files)
        template = files["template/src/app/demo-contact.component.html"]
        markup = Markup(template)
        ids = {attrs["id"] for _, attrs in markup.tags if "id" in attrs}
        self.assertEqual(len(ids), sum("id" in attrs for _, attrs in markup.tags))
        for tag, attrs in markup.tags:
            if tag == "label":
                self.assertIn(attrs["for"], ids)
        self.assertIn("(submit)=\"save($event, emailInput.value)\"", template)
        self.assertIn("{{ status() }}", template)
        self.assertIn("event.preventDefault()", component)
        main = files["template/src/main.ts"]
        self.assertIn("bootstrapApplication(DemoContactComponent, appConfig)", main)
        self.assertIn("<demo-contact>", files["template/src/index.html"])
        self.assertNotIn("template/package.json", files, "This is a CLI integration recipe, not a scaffold")
        self.assertIn("不是", files["template/INTEGRATION.md"])
        self.assertIn("providers", files["template/INTEGRATION.md"])

    def test_style_imports_resolve_with_less_and_sass_module_conventions(self):
        less = self.packs["frontend-less"]["documents"]
        scss = self.packs["frontend-scss"]["documents"]
        for path, text in less.items():
            if path.endswith(".less"):
                for dependency in re.findall(r'@import\s+\(reference\)\s+"([^"]+)"', text):
                    self.assertIn("template/" + dependency, less)
        self.assertIn("@brand:", less["template/tokens.less"])
        self.assertIn(".focus-ring()", less["template/mixins.less"])
        for path, text in scss.items():
            if path.endswith(".scss"):
                self.assertNotRegex(text, r"@import\b")
                for dependency in re.findall(r'@use\s+"([^"]+)"', text):
                    self.assertIn("template/_" + dependency + ".scss", scss)
        self.assertIn("tokens.$brand", scss["template/styles.scss"])
        self.assertIn("@include mixins.focus-ring", scss["template/styles.scss"])
        self.assertIn("!default", scss["template/_tokens.scss"])

    def test_style_demos_include_accessible_and_responsive_states(self):
        for identifier, extension in (("frontend-css", "css"), ("frontend-less", "less"), ("frontend-scss", "scss")):
            files = self.packs[identifier]["documents"]
            source = files["template/styles." + extension]
            markup = Markup(files["template/demo.html"])
            stylesheets = [attrs["href"] for tag, attrs in markup.tags if tag == "link" and attrs.get("rel") == "stylesheet"]
            self.assertEqual(stylesheets, ["styles.css"])
            classes = {value for _, attrs in markup.tags for value in attrs.get("class", "").split()}
            for class_name in classes:
                self.assertIn("." + class_name, source)
            self.assertIn(":focus-visible", source)
            self.assertIn("@media (min-width:", source)
            self.assertIn("@media (prefers-reduced-motion: reduce)", source)
            self.assertIn("transform: none", source)
            self.assertIn("minmax(0, 1fr)", source)
            self.assertNotIn("outline: none", source)
            combinations = files["template/COMBINATIONS.md"]
            for platform in ("Angular + SCSS", "Vue + Less", "React Native", "StyleSheet", "WXSS", "Taro"):
                self.assertIn(platform, combinations)

    def test_tailwind_next_and_vite_paths_are_explicit_and_distinct(self):
        files = self.packs["frontend-tailwind"]["documents"]
        self.assertIn("@tailwindcss/vite", files["template/vite.plugin.ts"])
        self.assertIn("@tailwindcss/postcss", files["template/postcss.config.mjs"])
        self.assertNotIn("@tailwindcss/vite", files["template/postcss.config.mjs"])
        self.assertIn('@import "tailwindcss"', files["template/styles.css"])
        for token in ("md:grid-cols-2", "focus-visible:", "motion-reduce:"):
            self.assertIn(token, files["template/demo.html"])
        for token in ("Next.js", "Nuxt", "Angular", "保留"):
            self.assertIn(token, files["template/INTEGRATION.md"])

    def test_component_libraries_have_real_framework_components(self):
        element = self.packs["frontend-element-plus"]["documents"]
        antd = self.packs["frontend-ant-design"]["documents"]
        mui = self.packs["frontend-mui"]["documents"]
        self.assertIn("import { ElButton, ElInput } from 'element-plus'", element["template/DemoElementForm.vue"])
        self.assertIn("element-plus/dist/index.css", element["template/INTEGRATION.md"])
        self.assertIn("from 'antd'", antd["template/DemoAntDesignForm.tsx"])
        self.assertIn("from '@mui/material'", mui["template/DemoMuiForm.tsx"])
        self.assertIn("@emotion/react", mui["template/INTEGRATION.md"])
        for files in (element, antd, mui):
            component = next(body for path, body in files.items() if path.endswith((".vue", ".tsx")))
            self.assertIn('aria-live="polite"', component)
            self.assertIn("trim()", component)
            self.assertNotRegex(component, r"\b(fetch|XMLHttpRequest|axios)\s*\(")

    def test_next_component_recipes_distinguish_client_boundary_and_ssr_setup(self):
        antd = self.packs["frontend-ant-design"]["documents"]
        mui = self.packs["frontend-mui"]["documents"]
        self.assertIn('<Space orientation="vertical"', antd["template/DemoAntDesignForm.tsx"])
        self.assertNotIn('<Space direction=', antd["template/DemoAntDesignForm.tsx"])
        self.assertIn('v5', antd["template/INTEGRATION.md"])
        self.assertIn('direction="vertical"', antd["template/INTEGRATION.md"])
        for files, name, provider, package in (
            (antd, "DemoAntDesignForm.tsx", "AntdRegistry", "@ant-design/nextjs-registry"),
            (mui, "DemoMuiForm.tsx", "AppRouterCacheProvider", "@mui/material-nextjs"),
        ):
            self.assertTrue(files["template/" + name].startswith("'use client';\n"))
            guide = files["template/INTEGRATION.md"]
            for required in (provider, package, "app/layout.tsx", "Pages Router", "保留", "复用", "SSR", "水合"):
                self.assertIn(required, guide)
        self.assertIn("@emotion/cache", mui["template/INTEGRATION.md"])
        self.assertIn("与目标 Next.js 版本匹配", mui["template/INTEGRATION.md"])

    def _run_node(self, source, payload):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable; no dependency installation is attempted")
        result = subprocess.run([node, "-e", source], cwd=ROOT, input=json.dumps(payload),
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_actual_typescript_parser_and_transpiler_accept_code_syntax(self):
        if not (ROOT / "openwiki-upstream/node_modules/typescript/lib/typescript.js").exists():
            self.skipTest("Existing upstream TypeScript compiler is unavailable")
        files = []
        for pack in self.packs.values():
            for path, content in pack["documents"].items():
                if path.endswith((".ts", ".tsx", ".mjs")):
                    files.append({"name": pack["id"] + "/" + path, "content": content})
                elif path.endswith(".vue"):
                    script = re.search(r"<script setup lang=\"ts\">(.*?)</script>", content, re.S)
                    self.assertIsNotNone(script)
                    files.append({"name": path + ".ts", "content": script.group(1)})
        results = self._run_node(r'''
            const fs = require('node:fs');
            const ts = require('./openwiki-upstream/node_modules/typescript/lib/typescript.js');
            const files = JSON.parse(fs.readFileSync(0, 'utf8'));
            const results = files.map(file => {
              const parsed = ts.createSourceFile(file.name, file.content, ts.ScriptTarget.Latest, true);
              const result = ts.transpileModule(file.content, {fileName: file.name, reportDiagnostics: true,
                compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
                  jsx: ts.JsxEmit.ReactJSX, experimentalDecorators: true}});
              const errors = [...parsed.parseDiagnostics, ...(result.diagnostics || [])]
                .filter(item => item.category === ts.DiagnosticCategory.Error)
                .map(item => ts.flattenDiagnosticMessageText(item.messageText, '\n'));
              const first = parsed.statements[0];
              const clientBoundary = first && ts.isExpressionStatement(first) &&
                ts.isStringLiteral(first.expression) && first.expression.text === 'use client';
              return {name: file.name, errors, output: result.outputText.length, clientBoundary: !!clientBoundary};
            });
            process.stdout.write(JSON.stringify(results));
        ''', files)
        self.assertGreaterEqual(len(results), 9)
        for result in results:
            self.assertEqual(result["errors"], [], result["name"])
            self.assertGreater(result["output"], 0)
            if result["name"].endswith(("DemoAntDesignForm.tsx", "DemoMuiForm.tsx")):
                self.assertTrue(result["clientBoundary"], result["name"])

    def test_actual_esbuild_parser_accepts_plain_css_syntax(self):
        if not (ROOT / "openwiki-tools/node_modules/esbuild/lib/main.js").exists():
            self.skipTest("Existing esbuild is unavailable")
        files = [{"name": pack["id"] + "/" + path, "content": content}
                 for pack in self.packs.values() for path, content in pack["documents"].items()
                 if path.endswith(".css")]
        results = self._run_node(r'''
            const fs = require('node:fs');
            const esbuild = require('./openwiki-tools/node_modules/esbuild/lib/main.js');
            const files = JSON.parse(fs.readFileSync(0, 'utf8'));
            const results = files.map(file => {
              const result = esbuild.transformSync(file.content, {loader: 'css', sourcefile: file.name});
              return {name: file.name, warnings: result.warnings.map(item => item.text), output: result.code.length};
            });
            process.stdout.write(JSON.stringify(results));
        ''', files)
        self.assertGreaterEqual(len(results), 4)
        for result in results:
            self.assertEqual(result["warnings"], [], result["name"])
            self.assertGreater(result["output"], 0)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from zipfile import ZipFile

from federation.core import FederationStore
from federation.reports import save_report, report_file, write_docx


class ReportTest(unittest.TestCase):
    def test_malformed_model_table_preserves_every_cell_without_false_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'model.docx'
            text = '# 报告\n\n| 功能 | 说明 |\n| :--- :--- |\n| 图像生成 | 原文含未转义 | 必须保留的尾部 |'
            write_docx(text, destination)
            with ZipFile(destination) as z:
                xml = z.read('word/document.xml').decode()
                self.assertIn('必须保留的尾部', xml)
                self.assertIn('原文含未转义', xml)
                self.assertNotIn('<w:tbl>', xml)

    def test_document_export_preserves_body_and_does_not_write_knowledge(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = FederationStore(Path(temporary) / 'data', project_root=Path(temporary) / 'project')
            store.init()
            before = {str(p): p.read_bytes() for p in store.base.rglob('*') if p.is_file()}
            run_id = uuid.uuid4().hex
            text = '# 产品分析报告\n\n## 实现与盈利\n\n加载失败时保留输入。\n\n| 假设 | 数值 |\n| --- | --- |\n| 用户数 | 100 |\n\n<script>这只是文字</script>'
            artifacts = save_report(store, run_id, text)
            for artifact in artifacts:
                file, meta = report_file(store, run_id, artifact['format'])
                self.assertEqual(meta, artifact)
                if artifact['format'] == 'md':
                    self.assertEqual(file.read_text().strip(), text)
                else:
                    with ZipFile(file) as z:
                        xml = z.read('word/document.xml').decode()
                        self.assertIn('加载失败时保留输入', xml)
                        self.assertIn('&lt;script&gt;', xml)
                        self.assertIn('D9D9D9', xml)
            self.assertTrue(all(Path(p).read_bytes() == data for p, data in before.items()))
            for identifier, extension in [('../private', 'md'), (run_id, '../env'), ('a' * 31, 'docx')]:
                with self.assertRaises(ValueError): report_file(store, identifier, extension)
            file, _ = report_file(store, run_id, 'md')
            file.write_text('changed')
            with self.assertRaises(ValueError): report_file(store, run_id, 'md')

"""Controlled HTTP tests for branch-scoped, incremental web source collection."""
import asyncio
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from federation.core import FederationStore
from federation import web_learning as web

TEXT = ("A browser form should have a visible label for each input. "
        "Authentication responses should avoid revealing whether an account exists. "
        "Keyboard users must be able to submit the form and discover validation errors. "
        "A server must validate the submitted values before creating a session.")


def response(url="https://example.com/docs", text=TEXT, status=200, headers=None):
    body = ("<html><head><title>Form guide</title></head><body><main><article>"
            "<h1>Form guide</h1><p>" + text + "</p></article></main></body></html>").encode()
    return {"url": url, "status": status, "headers": headers or {"content-type": "text/html; charset=utf-8"}, "body": body}


class NetworkPolicyTests(unittest.TestCase):
    def test_blocks_private_credentials_ports_schemes_and_obfuscated_hosts(self):
        for url in ["file:///etc/passwd", "https://user:secret@example.com", "http://localhost/",
                    "http://127.0.0.1/", "http://10.2.3.4/", "http://169.254.169.254/", "http://[::1]/",
                    "http://[::ffff:127.0.0.1]/", "http://[2002:a00:1::]/", "http://example.com:8080/",
                    "http://example.local/", "http://localhost./", "http://foo\\@example.com/", "http://example.com/\n"]:
            with self.subTest(url=url), self.assertRaises(web.CollectionError):
                web.canonical_url(url)
        self.assertEqual(web.canonical_url("https://EXAMPLE.com:443/a?utm_source=x&b=2#foo"), "https://example.com/a?b=2")

    def test_rejects_any_private_dns_answer_and_pins_actual_connection(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(socket, "getaddrinfo", return_value=answers), self.assertRaises(web.CollectionError):
            web._resolve_public("example.com", 443)
        with patch.object(socket, "socket") as sock, patch.object(socket, "getaddrinfo") as dns:
            conn = web._PinnedHTTPConnection("example.com", 80, "93.184.216.34", socket.AF_INET, 5)
            conn.connect()
            sock.return_value.connect.assert_called_once_with(("93.184.216.34", 80))
            dns.assert_not_called()

    def test_tls_uses_original_host_for_certificate_verification(self):
        with patch.object(socket, "socket"), patch.object(web.ssl, "create_default_context") as context:
            conn = web._PinnedHTTPSConnection("example.com", 443, "93.184.216.34", socket.AF_INET, 5)
            conn.connect()
            self.assertEqual(context.return_value.wrap_socket.call_args.kwargs["server_hostname"], "example.com")

    def test_existing_proxy_tunnels_to_validated_ip_with_original_tls_identity(self):
        with patch.object(socket, 'create_connection') as socket_factory, patch.object(web._PinnedProxyConnection, '_tunnel') as tunnel, patch.object(web.ssl, 'create_default_context') as context:
            conn = web._PinnedHTTPSProxyConnection('example.com', 443, '93.184.216.34', socket.AF_INET, 5, urlsplit('http://127.0.0.1:7897'))
            conn.connect()
            socket_factory.assert_called_once_with(('127.0.0.1', 7897), 5)
            tunnel.assert_called_once()
            self.assertEqual(conn._tunnel_host, '93.184.216.34')
            self.assertEqual(conn._tunnel_port, 443)
            self.assertEqual(context.return_value.wrap_socket.call_args.kwargs['server_hostname'], 'example.com')

    def test_proxy_does_not_bypass_target_validation_or_redirect_policy(self):
        fetcher = web.SafeFetcher(use_system_proxy=True)
        with patch.object(web, '_PinnedHTTPSProxyConnection') as connection:
            with self.assertRaises(web.CollectionError):
                fetcher._request('https://127.0.0.1/private')
            connection.assert_not_called()
        with patch.object(fetcher, '_robots'), patch.object(fetcher, '_request', return_value=response(status=302, headers={'location':'http://169.254.169.254/latest'})) as request:
            with self.assertRaises(web.CollectionError):
                fetcher.fetch('https://example.com/news')
            self.assertEqual(request.call_count, 1)

    def test_redirect_rechecks_destination_and_robots(self):
        fetcher = web.SafeFetcher()
        with patch.object(fetcher, "_robots") as robots, patch.object(fetcher, "_request") as request:
            request.return_value = response(status=302, headers={"location": "http://127.0.0.1/private"})
            with self.assertRaises(web.CollectionError):
                fetcher.fetch("https://example.com/docs")
            self.assertEqual(request.call_count, 1)
        with patch.object(fetcher, "_robots") as robots, patch.object(fetcher, "_request") as request:
            request.side_effect = [response(status=302, headers={"location": "https://other.example/docs"}), response("https://other.example/docs")]
            self.assertEqual(fetcher.fetch("https://example.com/docs")["url"], "https://other.example/docs")
            self.assertEqual([call.args[0] for call in robots.call_args_list], ["https://example.com/docs", "https://other.example/docs"])

    def test_robots_denial_and_unknown_failure_block_page(self):
        for status, body in [(200, b"User-agent: *\nDisallow: /private"), (503, b"unavailable")]:
            fetcher = web.SafeFetcher()
            with patch.object(fetcher, "_request", return_value={"url": "https://example.com/robots.txt", "status": status, "headers": {}, "body": body}) as request:
                with self.assertRaises(web.CollectionError):
                    fetcher.fetch("https://example.com/private")
                self.assertEqual(request.call_count, 1 if status == 200 else 3)
                self.assertTrue(all(call.args[0].endswith("/robots.txt") for call in request.call_args_list))

    def test_response_type_redirect_limit_and_download_limit(self):
        fetcher = web.SafeFetcher()
        with patch.object(fetcher, "_robots"), patch.object(fetcher, "_request", return_value=response(headers={"content-type": "application/pdf"})):
            with self.assertRaises(web.CollectionError):
                fetcher.fetch("https://example.com/file")
        with patch.object(web, "_resolve_public", return_value=(socket.AF_INET, "93.184.216.34")), patch.object(web, "_PinnedHTTPSConnection") as connection:
            result = connection.return_value.getresponse.return_value
            result.getheaders.return_value = [("Content-Length", str(web.MAX_DOWNLOAD_BYTES + 1))]
            with self.assertRaises(web.CollectionError):
                fetcher._request("https://example.com/big")
            connection.return_value.close.assert_called_once()


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FederationStore(Path(self.temp.name) / "data", project_root=Path(self.temp.name) / "project")
        self.store.init()

    def tearDown(self):
        self.temp.cleanup()

    async def collect(self, **kwargs):
        return await web.collect_sources(self.store, "software-frontend", "学习登录表单", urls=["https://example.com/docs"], **kwargs)

    async def test_actual_extractor_and_duplicate_preserve_inbox_bytes(self):
        events = []
        with patch.object(web.SafeFetcher, "fetch", return_value=response()):
            first = await self.collect(progress=events.append)
            name = first["sources"][0]["filename"]
            before = (self.store._source("software-frontend") / name).read_bytes()
            second = await self.collect()
        self.assertEqual(first["changed_count"], 1)
        self.assertEqual(second["changed_count"], 0)
        self.assertEqual(second["sources"][0]["status"], "unchanged")
        self.assertEqual((self.store._source("software-frontend") / name).read_bytes(), before)
        self.assertEqual(len(self.store.sources("software-frontend")), 1)
        self.assertEqual(len(self.store.sources("software-backend")), 0)
        self.assertTrue(all(event["status"] == "collecting" for event in events))
        self.assertTrue((self.store.base / first["report_path"]).exists())
        self.assertIn("browser form", (self.store.base / first["sources"][0]["markdown_path"]).read_text())

    async def test_updated_source_archives_old_and_only_latest_is_visible(self):
        with patch.object(web.SafeFetcher, "fetch", return_value=response()):
            first = await self.collect()
        with patch.object(web.SafeFetcher, "fetch", return_value=response(text=TEXT + " Add a browser autocomplete attribute for the username.")):
            second = await self.collect()
        old, new = first["sources"][0], second["sources"][0]
        self.assertEqual(new["status"], "updated")
        self.assertEqual(new["supersedes"], old["filename"])
        self.assertEqual([item["name"] for item in self.store.sources("software-frontend")], [new["filename"]])
        archived = self.store.base / "web-learning/archive/software-frontend" / old["filename"]
        self.assertTrue(archived.exists())
        with patch.object(web.SafeFetcher, "fetch", return_value=response()):
            reverted = await self.collect()
        self.assertEqual(reverted["sources"][0]["filename"], old["filename"])
        self.assertEqual(reverted["sources"][0]["status"], "updated")
        self.assertEqual(len(self.store.sources("software-frontend")), 1)

    async def test_user_changed_inbox_is_not_relearned_or_archived(self):
        with patch.object(web.SafeFetcher, "fetch", return_value=response()):
            first = await self.collect()
        source = self.store._source("software-frontend") / first["sources"][0]["filename"]
        source.write_text("My deliberate local edits", encoding="utf-8")
        for text in [TEXT, TEXT + " This is an updated public guide."]:
            with patch.object(web.SafeFetcher, "fetch", return_value=response(text=text)):
                report = await self.collect()
            self.assertEqual(report["sources"], [])
            self.assertIn("本地被修改", report["errors"][0]["error"])
            self.assertEqual(source.read_text(), "My deliberate local edits")
            self.assertEqual(len(self.store.sources("software-frontend")), 1)

    async def test_two_sources_keep_partial_success_but_mark_integrity_conflict(self):
        with patch.object(web.SafeFetcher, "fetch", return_value=response()):
            original = await self.collect()
        filename = original["sources"][0]["filename"]
        source = self.store._source("software-frontend") / filename
        source.write_text("User modified this previously collected source", encoding="utf-8")
        with patch.object(web.SafeFetcher, "fetch", side_effect=[response("https://example.com/new"), response()]):
            report = await web.collect_sources(self.store, "software-frontend", "form validation", urls=["https://example.com/new", "https://example.com/docs"], max_pages=2)
        self.assertEqual(len(report["sources"]), 1)
        self.assertEqual(report["sources"][0]["url"], "https://example.com/new")
        self.assertEqual(report["errors"][0]["code"], "local_source_conflict")
        self.assertEqual(source.read_text(), "User modified this previously collected source")
        self.assertEqual(len(self.store.sources("software-frontend")), 2)
        with self.assertRaises(web.LocalSourceConflict):
            web.validate_inbox_integrity(self.store, "software-frontend")
        web.validate_inbox_integrity(self.store, "software-backend")

    async def test_integrity_check_also_protects_unvisited_old_sources(self):
        with patch.object(web.SafeFetcher, "fetch", return_value=response()):
            original = await self.collect()
        web.validate_inbox_integrity(self.store, "software-frontend")
        source = self.store._source("software-frontend") / original["sources"][0]["filename"]
        source.write_text("Manually revised source", encoding="utf-8")
        with patch.object(web.SafeFetcher, "fetch", return_value=response("https://example.com/new")):
            report = await web.collect_sources(self.store, "software-frontend", "form validation", urls=["https://example.com/new"], max_pages=1)
        self.assertEqual(report["errors"], [])
        with self.assertRaises(web.LocalSourceConflict):
            web.validate_inbox_integrity(self.store, "software-frontend")

    async def test_user_changed_archive_is_not_restored(self):
        with patch.object(web.SafeFetcher, "fetch", return_value=response()):
            first = await self.collect()
        with patch.object(web.SafeFetcher, "fetch", return_value=response(text=TEXT + " New information.")):
            second = await self.collect()
        archived = self.store.base / "web-learning/archive/software-frontend" / first["sources"][0]["filename"]
        archived.write_text("Manually changed archive", encoding="utf-8")
        with patch.object(web.SafeFetcher, "fetch", return_value=response()):
            report = await self.collect()
        self.assertEqual(report["sources"], [])
        self.assertIn("归档资料在本地被修改", report["errors"][0]["error"])
        self.assertEqual(archived.read_text(), "Manually changed archive")
        self.assertEqual([item["name"] for item in self.store.sources("software-frontend")], [second["sources"][0]["filename"]])

    async def test_one_page_budget_selects_discovered_topic_before_seed_index(self):
        seed = web.OFFICIAL_SITES["software-frontend"][0]
        seed_response = response(seed)
        seed_response["body"] += b'<a href="/en-US/docs/Web/HTML/form">Form validation</a>'
        with patch.object(web, "_search_key", return_value=""), patch.object(web.SafeFetcher, "fetch", side_effect=lambda url: seed_response if url == seed else response(url)):
            report = await web.collect_sources(self.store, "software-frontend", "HTML form validation", max_pages=1)
        self.assertEqual(len(report["sources"]), 1)
        self.assertNotEqual(report["sources"][0]["url"], seed)
        self.assertTrue(report["sources"][0]["url"].endswith("/form"))

    async def test_partial_error_empty_body_and_final_url_dedup(self):
        with patch.object(web.SafeFetcher, "fetch", side_effect=[web.CollectionError("blocked"), response(text="empty"), response(), response()]):
            report = await web.collect_sources(self.store, "software", "学习网页", urls=["https://example.com/blocked", "https://example.com/empty", "https://example.com/a", "https://example.com/b"], max_pages=3)
        self.assertEqual(len(report["errors"]), 2)
        self.assertEqual(len(report["sources"]), 1)
        self.assertEqual(report["attempted_count"], 4)

    async def test_no_url_discovers_official_links_using_planned_topics(self):
        seed = web.OFFICIAL_SITES["software-frontend"][0]
        seed_response = response(seed)
        seed_response["body"] = seed_response["body"].replace(b"</main>", b'<a href="/en-US/docs/Web/HTML/form">Authentication form guide</a></main>')
        calls = []
        def fetch(url):
            calls.append(url)
            return seed_response if url == seed else response(url)
        with patch.object(web, "_search_key", return_value=""), patch.object(web.SafeFetcher, "fetch", side_effect=fetch):
            report = await web.collect_sources(self.store, "software-frontend", "学习登录页", max_pages=2, queries=["HTML authentication form"])
        self.assertEqual(report["provider"], "official-sites")
        self.assertEqual(len(report["sources"]), 2)
        self.assertIn("/en-US/docs/Web/HTML/form", calls[1])
        self.assertEqual(report["discovery"]["queries"], ["HTML authentication form"])
        self.assertIn(calls[1], report["discovery"]["candidates"])

    async def test_tavily_failure_falls_back_and_key_is_boolean_only(self):
        with patch.object(web, "_search_key", return_value="secret"), patch.object(web, "_tavily_urls", side_effect=web.CollectionError("search failed")), patch.object(web.SafeFetcher, "fetch", side_effect=lambda url: response(url)):
            self.assertIs(web.has_search_key(self.store), True)
            report = await web.collect_sources(self.store, "software", "Python language", max_pages=1)
        self.assertEqual(report["provider"], "official-sites")
        self.assertEqual(report["errors"][0]["stage"], "search")
        self.assertNotIn("secret", json.dumps(report))

    async def test_central_limits_and_symlink_are_rejected_before_fetch(self):
        cases = [{"space_id": "central"}, {"max_pages": 0}, {"max_pages": 6}, {"max_pages": True},
                 {"queries": []}, {"run_id": "../outside"}, {"urls": "https://example.com"}]
        with patch.object(web.SafeFetcher, "fetch") as fetch:
            for kwargs in cases:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    await web.collect_sources(self.store, kwargs.pop("space_id", "software"), "learn", **kwargs)
            outside = Path(self.temp.name) / "outside"
            outside.mkdir()
            (self.store.base / "web-learning").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                await web.collect_sources(self.store, "software", "learn")
            fetch.assert_not_called()

    def test_planned_platform_topics_choose_matching_official_seeds(self):
        app = web.official_sites(self.store, "software-app")
        self.assertEqual(web._select_seeds(app, "Swift iOS navigation"), ["https://developer.apple.com/documentation/"])
        backend = web.official_sites(self.store, "software-backend")
        self.assertEqual(web._select_seeds(backend, "Java dependency injection"), ["https://docs.spring.io/spring-boot/"])

    def test_catalog_covers_every_existing_noncentral_agent(self):
        self.assertEqual(set(web.OFFICIAL_SITES), set(self.store._definitions) - {"central"})


if __name__ == "__main__":
    unittest.main()

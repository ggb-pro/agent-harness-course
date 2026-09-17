import os
from pathlib import Path
import tempfile
import unittest

from sonic_agent import (
    AgentRunner,
    AssistantResponse,
    ExactTextCompletion,
    FakeProvider,
    InMemoryEventStore,
    ReadOnlyRepositoryTools,
    ToolCall,
    ToolError,
    ToolRegistry,
    ToolRuntime,
    WorkspaceLimits,
    WorkspaceScope,
)


class RepositoryToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "docs").mkdir()
        (self.root / ".git").mkdir()
        (self.root / "src" / "app.py").write_text(
            "def greet():\n    return 'hello sonic'\n", encoding="utf-8"
        )
        (self.root / "docs" / "guide.txt").write_text(
            "literal [abc]\nhello sonic again\n", encoding="utf-8"
        )
        (self.root / ".git" / "config").write_text("private", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=private", encoding="utf-8")
        (self.root / "server.pem").write_text("private-key", encoding="utf-8")
        self.scope = WorkspaceScope.open(self.root)
        self.tools = ReadOnlyRepositoryTools(self.scope)

    def tearDown(self):
        self.temporary.cleanup()

    def test_list_is_deterministic_bounded_and_omits_sensitive_paths(self):
        output = self.tools.list({"path": ".", "depth": 2}).value
        paths = [entry["path"] for entry in output["entries"]]
        self.assertEqual(paths, ["docs", "docs/guide.txt", "src", "src/app.py"])
        self.assertEqual(output["trust"], "untrusted_repository_content")
        self.assertFalse(output["truncated"])
        self.assertNotIn(".git", repr(output))
        self.assertNotIn(".env", repr(output))
        self.assertNotIn("server.pem", repr(output))

    def test_read_returns_bounded_text_and_content_hash(self):
        output = self.tools.read({"path": "src/app.py", "start_line": 2, "max_lines": 1}).value
        self.assertEqual(output["text"], "    return 'hello sonic'")
        self.assertEqual((output["start_line"], output["end_line"]), (2, 2))
        self.assertTrue(output["truncated"])
        self.assertEqual(len(output["sha256"]), 64)
        self.assertNotIn(str(self.root), repr(output))

    def test_search_is_literal_deterministic_and_reports_coverage(self):
        literal = self.tools.search({"query": "[abc]", "path": "."}).value
        self.assertEqual([(match["path"], match["line"]) for match in literal["matches"]], [
            ("docs/guide.txt", 1),
        ])
        result = self.tools.search({"query": "hello sonic", "path": "."}).value
        self.assertEqual([(match["path"], match["line"]) for match in result["matches"]], [
            ("docs/guide.txt", 2),
            ("src/app.py", 2),
        ])
        self.assertEqual(result["coverage"]["files_scanned"], 2)
        self.assertFalse(result["truncated"])

    def test_rejects_absolute_traversal_windows_and_sensitive_paths(self):
        rejected = [
            "../outside.txt",
            "/etc/passwd",
            "C:/Windows/win.ini",
            r"src\app.py",
            ".git/config",
            ".env",
            "server.pem",
            "src/./app.py",
            "src//app.py",
            "src/CON.txt",
            "src/bad\nname.py",
        ]
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(ToolError) as caught:
                self.tools.read({"path": value})
            self.assertTrue(caught.exception.denied)

    def test_rejects_unknown_arguments_and_non_integer_limits(self):
        with self.assertRaises(ToolError) as extra:
            self.tools.list({"path": ".", "root": "elsewhere"})
        with self.assertRaises(ToolError) as boolean:
            self.tools.list({"path": ".", "depth": True})
        self.assertEqual((extra.exception.code, boolean.exception.code), (
            "invalid_argument", "invalid_argument"
        ))

    def test_allowed_subtree_cannot_be_widened_by_tool_arguments(self):
        scoped = ReadOnlyRepositoryTools(WorkspaceScope.open(self.root, allowed_paths=("src",)))
        self.assertIn("greet", scoped.read({"path": "src/app.py"}).value["text"])
        with self.assertRaises(ToolError) as caught:
            scoped.read({"path": "docs/guide.txt"})
        self.assertEqual(caught.exception.code, "path_scope_denied")

    def test_binary_non_utf8_and_oversized_files_are_denied(self):
        (self.root / "binary.bin").write_bytes(b"a\x00b")
        (self.root / "latin.txt").write_bytes(b"\xff")
        (self.root / "large.txt").write_text("12345", encoding="utf-8")
        limited = ReadOnlyRepositoryTools(WorkspaceScope.open(
            self.root, limits=WorkspaceLimits(max_file_bytes=4)
        ))
        expected = {
            "binary.bin": "binary_file",
            "latin.txt": "unsupported_encoding",
            "large.txt": "file_too_large",
        }
        for path, code in expected.items():
            with self.subTest(path=path), self.assertRaises(ToolError) as caught:
                limited.read({"path": path})
            self.assertEqual(caught.exception.code, code)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO files are POSIX-only")
    def test_special_files_are_omitted_and_cannot_be_read(self):
        fifo = self.root / "src" / "events.pipe"
        os.mkfifo(fifo)
        listing = self.tools.list({"path": "src"}).value
        self.assertNotIn("events.pipe", repr(listing))
        with self.assertRaises(ToolError) as caught:
            self.tools.read({"path": "src/events.pipe"})
        self.assertEqual(caught.exception.code, "not_a_file")

    def test_listing_and_search_stop_at_hard_limits(self):
        limited = ReadOnlyRepositoryTools(WorkspaceScope.open(
            self.root,
            limits=WorkspaceLimits(max_list_entries=2, max_search_results=1),
        ))
        listing = limited.list({"path": ".", "depth": 3}).value
        search = limited.search({"query": "hello sonic", "path": "."}).value
        self.assertEqual(len(listing["entries"]), 2)
        self.assertTrue(listing["truncated"])
        self.assertEqual(len(search["matches"]), 1)
        self.assertEqual(search["stop_reason"], "result_limit")

    def test_linked_file_is_never_followed(self):
        outside = self.root.parent / f"{self.root.name}-outside.txt"
        outside.write_text("outside-secret", encoding="utf-8")
        link = self.root / "src" / "escape.txt"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            outside.unlink(missing_ok=True)
            self.skipTest("symlinks are unavailable for this test account")
        try:
            with self.assertRaises(ToolError) as caught:
                self.tools.read({"path": "src/escape.txt"})
            self.assertEqual(caught.exception.code, "linked_path")
            listing = self.tools.list({"path": "src"}).value
            self.assertNotIn("escape.txt", repr(listing))
            root_link = self.root.parent / f"{self.root.name}-root-link"
            os.symlink(self.root, root_link, target_is_directory=True)
            try:
                with self.assertRaises(ValueError):
                    WorkspaceScope.open(root_link)
            finally:
                root_link.unlink(missing_ok=True)
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

    def test_registry_manifest_marks_repository_tools_read_only(self):
        registry = ToolRegistry()
        self.tools.register(registry)
        self.assertEqual(registry.names, ("repo.list", "repo.read", "repo.search"))
        self.assertTrue(all(spec.read_only for spec in registry.manifest()))
        self.assertTrue(all(spec.input_schema["additionalProperties"] is False
                            for spec in registry.manifest()))

    def test_runtime_audit_never_persists_query_or_file_content(self):
        registry = ToolRegistry()
        self.tools.register(registry)
        store = InMemoryEventStore()
        runtime = ToolRuntime(registry, store)
        query = "hello sonic"
        result = runtime.run("run", ToolCall("search", "repo.search", {"query": query}))
        self.assertTrue(result.ok)
        persisted = repr([event.payload for event in store.load("run")])
        self.assertNotIn(query, persisted)
        self.assertNotIn("hello sonic again", persisted)
        self.assertIn("query_sha256", persisted)

    def test_malicious_rejected_argument_is_hashed_before_audit(self):
        registry = ToolRegistry()
        self.tools.register(registry)
        store = InMemoryEventStore()
        secret_path = "../../private/hidden-token.txt"
        result = ToolRuntime(registry, store).run(
            "run", ToolCall("read", "repo.read", {"path": secret_path})
        )
        self.assertTrue(result.denied)
        self.assertEqual(result.error_code, "invalid_path")
        self.assertNotIn(secret_path, repr([event.payload for event in store.load("run")]))

    def test_fake_provider_completes_list_read_search_loop(self):
        registry = ToolRegistry()
        self.tools.register(registry)
        store = InMemoryEventStore()
        provider = FakeProvider([
            AssistantResponse(tool_calls=(ToolCall("l", "repo.list", {"path": "."}),)),
            AssistantResponse(tool_calls=(ToolCall("r", "repo.read", {"path": "src/app.py"}),)),
            AssistantResponse(tool_calls=(ToolCall(
                "s", "repo.search", {"query": "hello sonic", "path": "."}
            ),)),
            AssistantResponse("repository inspected"),
        ])
        runner = AgentRunner(
            provider,
            ToolRuntime(registry, store),
            store,
            completion=ExactTextCompletion("repository inspected"),
        )
        result = runner.run("inspect the repository", run_id="repo-e2e")
        self.assertEqual((result.status, result.answer), ("completed", "repository inspected"))
        self.assertEqual(provider.calls[2][-1]["content"]["path"], "src/app.py")
        self.assertEqual(len(provider.calls[3][-1]["content"]["matches"]), 2)


if __name__ == "__main__":
    unittest.main()

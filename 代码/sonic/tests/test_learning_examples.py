"""Keep the documented runnable lesson and failure experiments reproducible."""
import contextlib
import importlib.util
import io
from pathlib import Path
import re
import sqlite3
import unittest


ROOT = Path(__file__).resolve().parents[3]


class LearningExamplesTests(unittest.TestCase):
    def test_documented_minimal_loop_runs(self):
        text = (ROOT / "学习文档.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)
        executable = [block for block in blocks if block.startswith("# runnable: minimal_loop")]
        self.assertEqual(len(executable), 1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(compile(executable[0], "learning:minimal_loop", "exec"), {})
        self.assertIn("观察到：def total", output.getvalue())

    def test_documented_schema_can_be_created(self):
        text = (ROOT / "设计说明.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```sql\n(.*?)\n```", text, re.DOTALL)
        self.assertEqual(len(blocks), 1)
        with contextlib.closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(blocks[0])
            connection.execute("INSERT INTO workspaces VALUES ('w', '/sample')")
            connection.execute("INSERT INTO sessions VALUES ('s', 'w', '2026-09-18T00:00:00Z')")
            connection.execute("INSERT INTO runs VALUES ('r1','s','running','{}','{}','{}')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO runs VALUES ('r2','s','running','{}','{}','{}')")
            connection.execute("UPDATE runs SET status='interrupted' WHERE id='r1'")
            connection.execute("INSERT INTO runs VALUES ('r2','s','running','{}','{}','{}')")

    def test_seven_laboratory_scenarios(self):
        path = ROOT / "代码" / "sonic" / "examples" / "mini_sonic.py"
        spec = importlib.util.spec_from_file_location("mini_sonic_lesson", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for case in ("normal", "denied", "stale", "timeout", "false_finish", "resume", "context"):
            with self.subTest(case=case), contextlib.redirect_stdout(io.StringIO()) as output:
                module.experiment(case)
                self.assertIn("experiment: PASS", output.getvalue())


if __name__ == "__main__":
    unittest.main()

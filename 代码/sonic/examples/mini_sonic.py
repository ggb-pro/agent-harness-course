"""Offline teaching laboratory. Scripted decisions, real disposable files/tests.

Run: python examples/mini_sonic.py --case normal
This is not a real-model provider, sandbox, or Sonic product entry point.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


BUG = "def total(cents, percent):\n    return cents * (100 - percent)\n"
FIX = "def total(cents, percent):\n    return cents * (100 - percent) // 100\n"
TEST = """import unittest
from pricing import total
class PricingTest(unittest.TestCase):
    def test_discount(self):
        self.assertEqual(total(10000, 20), 8000)
    def test_zero(self):
        self.assertEqual(total(10000, 0), 10000)
    def test_full(self):
        self.assertEqual(total(10000, 100), 0)
if __name__ == '__main__':
    unittest.main()
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Lab:
    def __init__(self, root, case):
        self.root = Path(root)
        self.case = case
        self.log = self.root / "session.jsonl"
        self.messages = []
        self.events = []

    def record(self, kind, data):
        event = {"seq": len(self.events) + 1, "kind": kind, "data": data}
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.events.append(event)
        if kind == "message":
            self.messages.append(data)

    @classmethod
    def reopen(cls, root, case):
        lab = cls(root, case)
        for line in lab.log.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            lab.events.append(event)
            if event["kind"] == "message":
                lab.messages.append(event["data"])
        return lab

    def execute(self, call):
        # The fixture has ONE editable file; no arbitrary path/command interface.
        name, args = call["name"], call["args"]
        path = self.root / "pricing.py"
        if name == "read":
            raw = path.read_bytes()
            return {"ok": True, "text": raw.decode(), "hash": digest(raw)}
        if name == "edit":
            if self.case == "denied":
                return {"ok": False, "error": "permission_denied"}
            raw = path.read_bytes()
            if digest(raw) != args["expected_hash"]:
                return {"ok": False, "error": "conflict"}
            # Snapshot before replacing; one writer in this teaching fixture.
            (self.root / "before.bin").write_bytes(raw)
            replacement = args["text"].encode()
            pending = self.root / "pricing.pending"
            pending.write_bytes(replacement)
            pending.replace(path)
            return {"ok": True, "hash": digest(replacement)}
        if name == "test":
            command = [sys.executable, "-B", "test_pricing.py"]
            timeout = 10
            if self.case == "timeout":
                command = [sys.executable, "-c", "import time; time.sleep(5)"]
                timeout = 0.1
            try:
                result = subprocess.run(command, cwd=self.root, capture_output=True,
                                        text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "timeout"}
            return {"ok": True, "exit_code": result.returncode,
                    "output": (result.stdout + result.stderr)[-2000:],
                    "hash": digest(path.read_bytes())}
        return {"ok": False, "error": "unknown_tool"}

    def verification(self):
        observations = [m["result"] for m in self.messages if m["role"] == "tool"]
        tests = [r for r in observations if "exit_code" in r]
        current = digest((self.root / "pricing.py").read_bytes())
        passed = bool(tests and tests[-1]["exit_code"] == 0
                      and tests[-1]["hash"] == current)
        return "verified" if passed else "unverified"

    def run(self, model, pause_after_edit=False):
        # Model controls proposed actions. Runtime owns budgets, execution and verdict.
        while sum(e["kind"] == "model.requested" for e in self.events) < 8:
            self.record("model.requested", {})
            reply = model.complete(self.messages)
            self.record("message", {"role": "assistant", **reply})
            if "call" not in reply:
                status = self.verification()
                self.record("finished", {"status": status})
                return status
            call = reply["call"]
            if self.case == "stale" and call["name"] == "edit":
                path = self.root / "pricing.py"
                path.write_text(path.read_text() + "# user edit\n", encoding="utf-8")
            self.record("tool.started", {"id": call["id"], "name": call["name"]})
            result = self.execute(call)
            self.record("message", {"role": "tool", "call_id": call["id"],
                                    "name": call["name"], "result": result})
            if pause_after_edit and call["name"] == "edit" and result["ok"]:
                self.record("paused", {"reason": "clean teaching checkpoint"})
                return "paused"
        self.record("finished", {"status": "budget_exhausted"})
        return "budget_exhausted"


class ScriptedModel:
    """A fixture for control flow, not an LLM and not a code-solving algorithm."""
    def complete(self, messages):
        results = [m for m in messages if m["role"] == "tool"]
        def call(name, **args):
            return {"call": {"id": f"c{len(results) + 1}", "name": name, "args": args}}
        if not results:
            return call("test")
        last = results[-1]
        if not last["result"]["ok"]:
            return {"text": "Stopped: " + last["result"]["error"]}
        if last["name"] == "test":
            if last["result"]["exit_code"] == 0:
                return {"text": "The three fixture tests passed."}
            return call("read")
        if last["name"] == "read":
            return call("edit", expected_hash=last["result"]["hash"], text=FIX)
        return call("test")


def compact_observations(messages):
    """Deterministic output thinning, NOT LLM summarization or token budgeting."""
    view = json.loads(json.dumps(messages))
    for message in view:
        result = message.get("result", {})
        if "output" in result:
            output = result.pop("output")
            result["output_ref"] = digest(output.encode())
    return view


def experiment(case):
    with tempfile.TemporaryDirectory(prefix="mini-sonic-") as directory:
        root = Path(directory)
        (root / "pricing.py").write_bytes(BUG.encode())
        (root / "test_pricing.py").write_bytes(TEST.encode())
        lab = Lab(root, case)
        lab.record("message", {"role": "user", "content": "Fix total; do not change tests."})
        if case == "false_finish":
            class PrematureModel:
                def complete(self, messages):
                    return {"text": "Done!"}
            status = lab.run(PrematureModel())
        else:
            status = lab.run(ScriptedModel(), pause_after_edit=case == "resume")
            if case == "resume":
                assert status == "paused"
                # A second OS process reconstructs state from the persisted transcript.
                child = subprocess.run([sys.executable, "-B", __file__, "--resume-root", str(root)],
                                       capture_output=True, text=True, timeout=20, check=True)
                status = child.stdout.strip()
                lab = Lab.reopen(root, case)
        results = [m for m in lab.messages if m["role"] == "tool"]
        print("tools:", " -> ".join(m["name"] for m in results) or "none")
        print("status:", status)
        print("errors:", [m["result"]["error"] for m in results if not m["result"]["ok"]])
        expected = "unverified" if case in {"stale", "denied", "timeout", "false_finish"} else "verified"
        assert status == expected
        if case in {"normal", "resume", "context"}:
            codes = [m["result"]["exit_code"] for m in results if m["name"] == "test"]
            assert codes == [1, 0], codes
            assert (root / "before.bin").read_bytes() == BUG.encode()
        if case == "resume":
            assert sum(m["name"] == "edit" for m in results) == 1
        if case == "denied":
            assert (root / "pricing.py").read_text() == BUG
        if case == "stale":
            assert (root / "pricing.py").read_text() == BUG + "# user edit\n"
        if case == "context":
            view = compact_observations(lab.messages)
            before, after = len(json.dumps(lab.messages)), len(json.dumps(view))
            print("context characters:", before, "->", after)
            assert after < before
            assert view[0] == lab.messages[0]
            assert [m["call_id"] for m in view if m["role"] == "tool"] == [m["call_id"] for m in results]
        print("experiment: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="normal", choices=[
        "normal", "denied", "stale", "timeout", "false_finish", "resume", "context"])
    parser.add_argument("--resume-root", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.resume_root:
        print(Lab.reopen(args.resume_root, "resume").run(ScriptedModel()))
    else:
        experiment(args.case)

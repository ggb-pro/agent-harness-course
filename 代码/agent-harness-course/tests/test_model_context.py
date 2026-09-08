import unittest

from traceforge_harness import AssistantResponse, ContextBuilder, ContextItem, FakeProvider


class ModelAndContextTests(unittest.TestCase):
    def test_fake_provider_returns_script_in_order(self):
        provider = FakeProvider([AssistantResponse("one"), AssistantResponse("two")])
        self.assertEqual(provider.complete([]).text, "one")
        self.assertEqual(provider.complete([]).text, "two")
        self.assertEqual(provider.remaining, 0)

    def test_fake_provider_fails_when_script_is_exhausted(self):
        provider = FakeProvider([])
        with self.assertRaisesRegex(RuntimeError, "exhausted"):
            provider.complete([])

    def test_fake_provider_records_each_request_snapshot(self):
        messages = [{"role": "user", "content": "before"}]
        provider = FakeProvider([AssistantResponse("ok")])
        provider.complete(messages)
        messages[0]["content"] = "after"
        self.assertEqual(provider.calls[0][0]["content"], "before")

    def test_context_selects_higher_priority_within_budget(self):
        items = [
            ContextItem("low", "a", priority=1, token_estimate=2),
            ContextItem("high", "b", priority=9, token_estimate=2),
        ]
        selected = ContextBuilder(2).build(items)
        self.assertEqual([item.source for item in selected], ["high"])

    def test_required_context_survives_budget_overflow(self):
        required = ContextItem("policy", "must stay", required=True, token_estimate=10)
        optional = ContextItem("note", "drop", priority=99, token_estimate=1)
        self.assertEqual(ContextBuilder(2).build([required, optional]), [required])


if __name__ == "__main__":
    unittest.main()


from contextlib import contextmanager
from dataclasses import asdict
import importlib.util
import json
import os
import sys
from types import ModuleType, SimpleNamespace
import traceback
import unittest
from unittest.mock import patch

from sonic_agent import (
    AgentRunner,
    ExactTextCompletion,
    InMemoryEventStore,
    ModelAccess,
    OpenAIResponsesProvider,
    ProviderError,
    ProviderInfo,
    ToolRegistry,
    ToolRuntime,
)


REMOTE_ACCESS = ModelAccess(
    allow_remote=True,
    allowed_origins=("https://api.openai.com",),
    grant_id="test-grant",
)


class FakeResponses:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, *outcomes):
        self.responses = FakeResponses(*outcomes)


@contextmanager
def mocked_openai_sdk(client, *, client_error=None, api_key="test-placeholder"):
    """Replace the SDK constructors without exposing a production injection hook."""

    client_options = []
    http_options = []
    http_client = SimpleNamespace(close=lambda: None)

    def build_http_client(**options):
        http_options.append(options)
        return http_client

    def build_client(**options):
        client_options.append(options)
        if client_error is not None:
            raise client_error
        return client

    fake_sdk = ModuleType("openai")
    fake_sdk.DefaultHttpxClient = build_http_client
    fake_sdk.OpenAI = build_client
    environment = {} if api_key is None else {"OPENAI_API_KEY": api_key}
    with (
        patch.dict(os.environ, environment, clear=api_key is None),
        patch.dict(sys.modules, {"openai": fake_sdk}),
    ):
        yield client_options, http_options


def response(
    text="ok",
    *,
    output=(),
    status="completed",
    usage=None,
    request_id="req_safe",
    error=None,
):
    return SimpleNamespace(
        id="resp_safe",
        model="gpt-test-resolved",
        status=status,
        output_text=text,
        output=list(output),
        usage=usage,
        error=error,
        _request_id=request_id,
    )


class OpenAIProviderTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("openai"), "optional OpenAI SDK is not installed")
    def test_installed_sdk_uses_hardened_transport_without_network_call(self):
        provider = OpenAIResponsesProvider("compatibility-check")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "placeholder-not-a-real-key"}):
            client = provider._client_or_create()
            try:
                self.assertEqual(client.max_retries, 0)
                self.assertIs(client._client.follow_redirects, False)
                self.assertIs(client._client._trust_env, False)
            finally:
                client.close()

    def test_remote_denied_before_credential_or_client_lookup(self):
        provider = OpenAIResponsesProvider("gpt-test")
        with mocked_openai_sdk(FakeClient(response())) as (client_options, http_options):
            with patch(
                "sonic_agent.models.openai_responses.os.environ.get"
            ) as credential_lookup:
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(caught.exception.code, "egress_denied")
        credential_lookup.assert_not_called()
        self.assertEqual(client_options, [])
        self.assertEqual(http_options, [])

    def test_missing_key_fails_before_client_creation(self):
        provider = OpenAIResponsesProvider("gpt-test")
        with mocked_openai_sdk(
            FakeClient(response()), api_key=None
        ) as (client_options, http_options):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([{"role": "user", "content": "hello"}], access=REMOTE_ACCESS)
        self.assertEqual(caught.exception.code, "missing_api_key")
        self.assertEqual(client_options, [])
        self.assertEqual(http_options, [])

    def test_configuration_error_traceback_does_not_chain_raw_secret(self):
        secret = "credential-resolver-raw-secret"

        provider = OpenAIResponsesProvider("gpt-test")
        with patch(
            "sonic_agent.models.openai_responses.os.environ.get",
            side_effect=RuntimeError(f"failed while holding {secret}"),
        ):
            with self.assertRaises(ProviderError) as caught:
                provider.complete(
                    [{"role": "user", "content": "hello"}], access=REMOTE_ACCESS
                )
        failure = caught.exception
        self.assertEqual(failure.code, "configuration")
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        self.assertNotIn(secret, "".join(traceback.format_exception(failure)))

    def test_local_endpoint_needs_no_remote_grant_or_remote_key(self):
        client = FakeClient(response())
        provider = OpenAIResponsesProvider(
            "local-model",
            base_url="http://127.0.0.1:11434/v1",
        )
        with mocked_openai_sdk(client) as (client_options, http_options):
            result = provider.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(result.text, "ok")
        self.assertEqual(provider.info.transport, "local")
        self.assertEqual(client_options[0]["api_key"], "local-no-credential")
        self.assertEqual(client_options[0]["max_retries"], 0)
        self.assertEqual(http_options, [{
            "timeout": 60.0, "follow_redirects": False, "trust_env": False,
        }])

    def test_remote_endpoint_must_be_https_and_exactly_allowlisted(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            OpenAIResponsesProvider("model", base_url="http://models.example/v1")

        client = FakeClient(response())
        provider = OpenAIResponsesProvider(
            "model",
            base_url="https://models.example/v1",
            credential_env="MODELS_EXAMPLE_API_KEY",
        )
        with mocked_openai_sdk(client) as (client_options, http_options):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([{"role": "user", "content": "hello"}], access=REMOTE_ACCESS)
        self.assertEqual(caught.exception.code, "egress_denied")
        self.assertEqual(client.responses.calls, [])
        self.assertEqual(client_options, [])
        self.assertEqual(http_options, [])

    def test_custom_remote_endpoint_never_receives_default_openai_credential(self):
        with self.assertRaisesRegex(ValueError, "credential_env"):
            OpenAIResponsesProvider(
                "model", base_url="https://models.example/v1"
            )

        client = FakeClient(response())
        provider = OpenAIResponsesProvider(
            "model",
            base_url="https://models.example/v1",
            credential_env="MODELS_EXAMPLE_API_KEY",
        )
        access = ModelAccess(
            allow_remote=True,
            allowed_origins=("https://models.example",),
        )
        with mocked_openai_sdk(client, api_key="must-not-use") as (client_options, _):
            with patch.dict(
                os.environ,
                {"MODELS_EXAMPLE_API_KEY": "custom-endpoint-key"},
            ):
                result = provider.complete(
                    [{"role": "user", "content": "hello"}], access=access
                )
        self.assertEqual(result.text, "ok")
        self.assertEqual(client_options[0]["api_key"], "custom-endpoint-key")

    def test_invalid_endpoint_and_origin_do_not_chain_raw_input(self):
        marker = "endpoint-secret-marker"
        cases = (
            lambda: OpenAIResponsesProvider(
                "model", base_url=f"https://api.openai.com:{marker}/v1"
            ),
            lambda: ModelAccess(
                allow_remote=True,
                allowed_origins=(f"https://api.openai.com:{marker}",),
            ),
        )
        for build in cases:
            with self.subTest(build=build):
                with self.assertRaises(ValueError) as caught:
                    build()
                failure = caught.exception
                self.assertIsNone(failure.__cause__)
                self.assertIsNone(failure.__context__)
                self.assertNotIn(marker, "".join(traceback.format_exception(failure)))

    def test_production_constructor_has_no_client_or_transport_injection_hook(self):
        with self.assertRaises(TypeError):
            OpenAIResponsesProvider("model", client=FakeClient())
        with self.assertRaises(TypeError):
            OpenAIResponsesProvider("model", client_factory=lambda **_: FakeClient())

    def test_completed_response_maps_text_usage_ids_and_request_options(self):
        usage = SimpleNamespace(
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
            input_tokens_details=SimpleNamespace(cached_tokens=3),
            output_tokens_details=SimpleNamespace(reasoning_tokens=2),
        )
        client = FakeClient(response("answer", usage=usage))
        ticks = iter((10.0, 10.125))
        provider = OpenAIResponsesProvider(
            "gpt-test",
            max_output_tokens=123,
            monotonic=ticks.__next__,
        )
        with mocked_openai_sdk(client):
            result = provider.complete(
                [{"role": "user", "content": "hello"}], access=REMOTE_ACCESS
            )

        self.assertEqual(result.text, "answer")
        self.assertEqual(result.metadata.response_id, "resp_safe")
        self.assertEqual(result.metadata.request_id, "req_safe")
        self.assertEqual(result.metadata.latency_ms, 125)
        self.assertEqual(asdict(result.metadata.usage), {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "cached_input_tokens": 3,
            "reasoning_output_tokens": 2,
        })
        request = client.responses.calls[0]
        self.assertEqual(request["model"], "gpt-test")
        self.assertEqual(request["max_output_tokens"], 123)
        self.assertNotIn("tools", request)
        self.assertIs(request["store"], False)
        self.assertNotIn("api_key", json.dumps(request))

    def test_function_calls_are_rejected_by_text_only_contract(self):
        output = [
            SimpleNamespace(type="reasoning"),
            SimpleNamespace(
                type="function_call", id="fc_ignored", call_id="call_1",
                name="first", arguments='{"value": 1}',
            ),
        ]
        client = FakeClient(response("", output=output))
        provider = OpenAIResponsesProvider("gpt-test")
        with mocked_openai_sdk(client):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([{"role": "user", "content": "go"}], access=REMOTE_ACCESS)
        self.assertEqual(caught.exception.code, "unsupported_response")

    def test_tool_history_is_rejected_until_context_contract_exists(self):
        provider = OpenAIResponsesProvider("gpt-test")
        with patch("sonic_agent.models.openai_responses.os.environ.get") as credential_lookup:
            with self.assertRaises(ProviderError) as caught:
                provider.complete([
                    {"role": "user", "content": "calculate"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "call_1",
                            "name": "add",
                            "arguments": {"b": 2, "a": 1},
                        }],
                    },
                ], access=REMOTE_ACCESS)
        self.assertEqual(caught.exception.code, "unsupported_input")
        credential_lookup.assert_not_called()

    def test_remote_authorization_requires_a_real_bool(self):
        for value in ("1", "true", "false", 1, 0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "bool"):
                    ModelAccess(allow_remote=value, allowed_origins=("https://api.openai.com",))

    def test_provider_rejects_non_model_access_before_lookup_or_client_creation(self):
        provider = OpenAIResponsesProvider("gpt-test")
        with mocked_openai_sdk(FakeClient(response())) as (client_options, http_options):
            with patch(
                "sonic_agent.models.openai_responses.os.environ.get"
            ) as credential_lookup:
                with self.assertRaisesRegex(TypeError, "ModelAccess"):
                    provider.complete(
                        [{"role": "user", "content": "hello"}], access=True
                    )
        credential_lookup.assert_not_called()
        self.assertEqual(client_options, [])
        self.assertEqual(http_options, [])

    def test_incomplete_and_empty_responses_are_rejected(self):
        for outcome, code in ((response(status="incomplete"), "incomplete"), (response(""), "invalid_response")):
            with self.subTest(code=code):
                client = FakeClient(outcome)
                provider = OpenAIResponsesProvider("gpt-test")
                with mocked_openai_sdk(client):
                    with self.assertRaises(ProviderError) as caught:
                        provider.complete(
                            [{"role": "user", "content": "go"}], access=REMOTE_ACCESS
                        )
                self.assertEqual(caught.exception.code, code)

    def test_failed_response_uses_whitelisted_error_code_not_raw_message(self):
        remote_error = SimpleNamespace(
            code="server_error",
            message="Authorization: Bearer response-secret-must-not-leak",
        )
        client = FakeClient(response("", status="failed", error=remote_error))
        provider = OpenAIResponsesProvider("gpt-test")
        with mocked_openai_sdk(client):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([{"role": "user", "content": "go"}], access=REMOTE_ACCESS)
        failure = caught.exception
        self.assertEqual((failure.code, failure.retryable), ("unavailable", True))
        self.assertNotIn("response-secret", str(failure))

    def test_sdk_errors_are_classified_without_raw_message(self):
        cases = (
            ("AuthenticationError", 401, "auth", False),
            ("PermissionDeniedError", 403, "permission", False),
            ("RateLimitError", 429, "rate_limit", True),
            ("APITimeoutError", None, "timeout", True),
            ("APIConnectionError", None, "network", True),
            ("InternalServerError", 503, "unavailable", True),
            ("APIStatusError", 408, "timeout", True),
            ("APIStatusError", 409, "conflict", True),
            ("BadRequestError", 400, "invalid_request", False),
        )
        for name, status, code, retryable in cases:
            with self.subTest(name=name):
                error_type = type(name, (Exception,), {})
                error = error_type("raw-secret-marker Authorization: Bearer hidden")
                error.status_code = status
                error.request_id = "req_error"
                ticks = iter((4.0, 4.01))
                provider = OpenAIResponsesProvider(
                    "gpt-test",
                    monotonic=ticks.__next__,
                )
                with mocked_openai_sdk(FakeClient(error)):
                    with self.assertRaises(ProviderError) as caught:
                        provider.complete(
                            [{"role": "user", "content": "go"}], access=REMOTE_ACCESS
                        )
                failure = caught.exception
                self.assertEqual((failure.code, failure.retryable), (code, retryable))
                self.assertEqual(failure.request_id, "req_error")
                self.assertEqual(failure.latency_ms, 10)
                self.assertNotIn("raw-secret-marker", str(failure))
                self.assertNotIn("Authorization", str(failure))
                self.assertIsNone(failure.__cause__)
                self.assertIsNone(failure.__context__)
                formatted = "".join(traceback.format_exception(failure))
                self.assertNotIn("raw-secret-marker", formatted)
                self.assertNotIn("Authorization", formatted)


class ProviderRunnerEventTests(unittest.TestCase):
    def _runner(self, provider, store):
        return AgentRunner(
            provider,
            ToolRuntime(ToolRegistry(), store),
            store,
            completion=ExactTextCompletion("done"),
        )

    def test_success_events_include_safe_model_telemetry_not_key(self):
        secret = "sk-test-never-persist-this"
        usage = SimpleNamespace(input_tokens=2, output_tokens=1, total_tokens=3)
        client = FakeClient(response("done", usage=usage))
        provider = OpenAIResponsesProvider("gpt-test")
        store = InMemoryEventStore()
        access = ModelAccess(
            allow_remote=True,
            allowed_origins=("https://api.openai.com",),
            grant_id=secret,
        )
        with mocked_openai_sdk(client, api_key=secret) as (client_options, _):
            result = self._runner(provider, store).run(
                "say done", "provider-success", model_access=access
            )
        events = store.load(result.run_id)
        requested = next(event for event in events if event.type == "model.requested")
        responded = next(event for event in events if event.type == "model.responded")
        self.assertEqual(result.status, "completed")
        self.assertEqual(responded.payload["usage"]["total_tokens"], 3)
        self.assertEqual(responded.payload["provider"], "openai")
        self.assertTrue(requested.payload["grant_ref"].startswith("sha256:"))
        self.assertEqual(client_options[0]["api_key"], secret)
        serialized = json.dumps([asdict(event) for event in events], ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("api_key", serialized)

    def test_failure_events_are_classified_and_never_persist_raw_sdk_error(self):
        secret = "sk-test-failure-secret"
        error_type = type("RateLimitError", (Exception,), {})
        error = error_type(f"Authorization: Bearer {secret}")
        error.status_code = 429
        error.request_id = "req_rate"
        provider = OpenAIResponsesProvider("gpt-test")
        store = InMemoryEventStore()
        with mocked_openai_sdk(FakeClient(error), api_key=secret):
            result = self._runner(provider, store).run(
                "work", "provider-failure", model_access=REMOTE_ACCESS
            )
        events = store.load(result.run_id)
        self.assertEqual(result.status, "failed")
        self.assertEqual([event.type for event in events], [
            "run.started", "model.requested", "model.failed", "run.failed",
        ])
        failed = events[-2].payload
        self.assertEqual((failed["code"], failed["retryable"]), ("rate_limit", True))
        serialized = json.dumps([asdict(event) for event in events], ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("Authorization", serialized)

    def test_unexpected_provider_exception_is_persisted_as_fixed_safe_error(self):
        secret = "unexpected-provider-secret"

        class LeakyProvider:
            @property
            def info(self):
                return ProviderInfo("custom", "test", "test")

            def complete(self, messages, *, access=None):
                del messages, access
                raise RuntimeError(f"raw failure contains {secret}")

        store = InMemoryEventStore()
        runner = AgentRunner(LeakyProvider(), ToolRuntime(ToolRegistry(), store), store)
        result = runner.run("work", "unexpected-provider-failure")
        serialized = json.dumps([asdict(event) for event in store.load(result.run_id)], ensure_ascii=False)
        self.assertEqual(result.status, "failed")
        self.assertNotIn(secret, serialized)
        self.assertIn("model provider failed unexpectedly", serialized)

    def test_legacy_provider_contract_is_rejected_before_run_events_exist(self):
        class LegacyProvider:
            def complete(self, messages):
                del messages

        store = InMemoryEventStore()
        with self.assertRaisesRegex(TypeError, "ProviderInfo"):
            AgentRunner(LegacyProvider(), ToolRuntime(ToolRegistry(), store), store)
        self.assertEqual(store.load(), [])

    def test_provider_without_access_parameter_is_rejected_before_run_events_exist(self):
        class LegacyProvider:
            @property
            def info(self):
                return ProviderInfo("legacy", "model", "test")

            def complete(self, messages):
                del messages

        store = InMemoryEventStore()
        with self.assertRaisesRegex(TypeError, "access keyword"):
            AgentRunner(LegacyProvider(), ToolRuntime(ToolRegistry(), store), store)
        self.assertEqual(store.load(), [])

    def test_provider_with_positional_only_access_is_rejected_before_run_events_exist(self):
        class PositionalOnlyProvider:
            @property
            def info(self):
                return ProviderInfo("legacy", "model", "test")

            def complete(self, messages, access, /):
                del messages, access

        store = InMemoryEventStore()
        with self.assertRaisesRegex(TypeError, "access keyword"):
            AgentRunner(
                PositionalOnlyProvider(), ToolRuntime(ToolRegistry(), store), store
            )
        self.assertEqual(store.load(), [])

    def test_runner_rejects_non_model_access_before_run_events_exist(self):
        store = InMemoryEventStore()
        runner = self._runner(OpenAIResponsesProvider("gpt-test"), store)
        with self.assertRaisesRegex(TypeError, "ModelAccess"):
            runner.run("work", "invalid-access", model_access=True)
        self.assertEqual(store.load(), [])

    def test_runner_denies_remote_provider_before_client_call(self):
        client = FakeClient(response("done"))
        provider = OpenAIResponsesProvider("gpt-test")
        store = InMemoryEventStore()
        runner = AgentRunner(provider, ToolRuntime(ToolRegistry(), store), store)
        result = runner.run("work", "provider-denied")
        self.assertEqual(result.status, "failed")
        self.assertEqual([event.type for event in store.load(result.run_id)], [
            "run.started", "model.denied", "run.failed",
        ])
        self.assertEqual(client.responses.calls, [])

    def test_runner_does_not_reuse_a_previous_runs_remote_grant(self):
        client = FakeClient(response("done"))
        provider = OpenAIResponsesProvider("gpt-test")
        store = InMemoryEventStore()
        runner = self._runner(provider, store)

        with mocked_openai_sdk(client):
            first = runner.run("work", "provider-first", model_access=REMOTE_ACCESS)
            second = runner.run("work", "provider-second")

        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "failed")
        self.assertEqual(len(client.responses.calls), 1)
        self.assertEqual(
            [event.type for event in store.load(second.run_id)],
            ["run.started", "model.denied", "run.failed"],
        )


if __name__ == "__main__":
    unittest.main()

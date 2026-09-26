"""Offline regression suite. Uses real Pydantic and mocked WebUI/HTTP boundaries.

Run with Python 3.11+ and Pydantic 2: python -m unittest discover -s tests -v
No credentials, network traffic or API charges are involved.
"""
import asyncio
import copy
import importlib.util
import json
import logging
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock


def load_pipe():
    # WebUI is a server-only dependency; aiohttp/fastapi are optional for this
    # offline suite. Fake transport below tests calls at the HTTP boundary.
    if importlib.util.find_spec("aiohttp") is None:
        aio = types.ModuleType("aiohttp")
        aio.ClientTimeout = lambda **kwargs: kwargs
        aio.ClientSession = object
        class ClientResponseError(Exception):
            def __init__(self, *args, **kwargs):
                super().__init__(kwargs.get("message", "HTTP error"))
                self.status = kwargs.get("status")
        aio.ClientResponseError = ClientResponseError
        sys.modules["aiohttp"] = aio
    if importlib.util.find_spec("fastapi") is None:
        fastapi = types.ModuleType("fastapi")
        fastapi.Request = object
        sys.modules["fastapi"] = fastapi
    for name in ("open_webui", "open_webui.models", "open_webui.models.chats",
                 "open_webui.utils", "open_webui.utils.misc"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["open_webui.models.chats"].Chats = object
    sys.modules["open_webui.utils.misc"].get_last_user_message = lambda messages: next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
    )
    path = Path(__file__).resolve().parents[1] / "functions/openai_responses.py"
    spec = importlib.util.spec_from_file_location("responses_v170", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


m = load_pipe()


def completed(text):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [
        {"type": "output_text", "text": text}]}]}


def decision(model="gpt-6-sol", effort="medium", task="routine", kind="substantive"):
    return {"target_model": model, "reasoning_effort": effort, "task_class": task,
            "route_kind": kind, "explanation": "test routing decision"}


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pipe = m.Pipe()
        self.pipe.logger = logging.getLogger("test")

    async def route(self, data=None, valves=None, hint=None, prompt="Explain this", alias="gpt-6-auto", response=None):
        self.pipe.send_openai_responses_nonstreaming_request = AsyncMock(
            return_value=response or completed(json.dumps(data or decision()))
        )
        body = m.ResponsesBody(model=alias, input=prompt)
        return await self.pipe._route_auto_model_and_reasoning(
            "gpt-6-luna", body, valves or m.Pipe.Valves(), public_alias=alias, routing_hint=hint
        )

    async def test_new_family_only_and_router_schema(self):
        body = await self.route()
        self.assertEqual(body.model, "gpt-6-sol")
        wire = self.pipe.send_openai_responses_nonstreaming_request.call_args.args[0]
        schema = wire["text"]["format"]["schema"]
        self.assertEqual(schema["properties"]["target_model"]["enum"], ["gpt-6-luna", "gpt-6-sol", "gpt-6-astra"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertNotIn("Terra", wire["instructions"])

    async def test_simple_and_mechanical_work_can_use_luna(self):
        for kind in ("simple", "trivial", "mechanical_batch"):
            with self.subTest(kind=kind):
                body = await self.route(decision("gpt-6-luna", "none", kind=kind))
                self.assertEqual((body.model, body.reasoning["effort"]), ("gpt-6-luna", "none"))

    async def test_substantive_or_professional_work_gets_sol_floor(self):
        for task, kind, prompt in (("routine", "substantive", "Explain this"),
                                   ("professional", "simple", "Draft a plan"),
                                   ("routine", "simple", "학생부 세특 작성해줘")):
            with self.subTest(task=task, kind=kind, prompt=prompt):
                body = await self.route(decision("gpt-6-luna", task=task, kind=kind), prompt=prompt)
                self.assertEqual(body.model, "gpt-6-sol")

    async def test_astra_requires_exceptional_class(self):
        for task in ("routine", "professional", "hard_reasoning"):
            with self.subTest(task=task):
                body = await self.route(decision("gpt-6-astra", "high", task))
                self.assertEqual(body.model, "gpt-6-sol")
                self.assertEqual(body.reasoning["effort"], "high" if task == "hard_reasoning" else "medium")

    async def test_exceptional_astra_and_none_normalization(self):
        body = await self.route(decision("gpt-6-astra", "none", "agentic_exceptional"))
        self.assertEqual((body.model, body.reasoning["effort"]), ("gpt-6-astra", "low"))

    async def test_astra_disabled_ceiling_and_saved_terra_ceiling(self):
        for settings, target in (({"ENABLE_GPT6_ASTRA": False}, "gpt-6-sol"),
                                 ({"ASTRA_PROMOTION": "disabled"}, "gpt-6-sol"),
                                 ({"GPT6_AUTO_MAX_TARGET": "terra"}, "gpt-6-sol"),
                                 ({"GPT6_AUTO_MAX_TARGET": "luna"}, "gpt-6-luna")):
            with self.subTest(settings=settings):
                body = await self.route(decision("gpt-6-astra", "high", "agentic_exceptional"), m.Pipe.Valves(**settings))
                self.assertEqual(body.model, target)

    async def test_hwpx_hints_respect_tier_and_effort_caps(self):
        hint = {"min_target": "astra", "min_effort": "max"}
        body = await self.route(decision("gpt-6-luna", "none", kind="simple"), hint=hint)
        self.assertEqual((body.model, body.reasoning["effort"]), ("gpt-6-sol", "medium"))
        body = await self.route(decision("gpt-6-luna", "none", kind="simple"), hint={"min_target": "terra"})
        self.assertEqual(body.model, "gpt-6-sol")
        body = await self.route(decision("gpt-6-luna", "none", kind="simple"),
                                valves=m.Pipe.Valves(GPT6_AUTO_MAX_TARGET="luna"), hint=hint)
        self.assertEqual(body.model, "gpt-6-luna")

    async def test_invalid_or_incomplete_router_falls_back(self):
        for response in (completed("not json"), completed("{}"), completed(json.dumps(decision("gpt-5.6-terra"))),
                         completed(json.dumps(decision(effort="max"))),
                         dict(completed(json.dumps(decision())), status="incomplete")):
            with self.subTest(response=response):
                body = await self.route(response=response)
                self.assertEqual((body.model, body.reasoning["effort"]), ("gpt-6-sol", "medium"))
                self.assertTrue(body.model_router_result["fallback"])

    async def test_transport_failure_fallback_and_cancellation(self):
        body = m.ResponsesBody(model="gpt-6-auto", input="hello")
        self.pipe.send_openai_responses_nonstreaming_request = AsyncMock(side_effect=RuntimeError("HTTP 503"))
        result = await self.pipe._route_auto_model_and_reasoning("gpt-6-luna", body, m.Pipe.Valves(), public_alias="gpt-6-auto")
        self.assertEqual(result.model, "gpt-6-sol")
        self.assertTrue(result.model_router_result["fallback"])
        self.pipe.send_openai_responses_nonstreaming_request = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await self.pipe._route_auto_model_and_reasoning("gpt-6-luna", body, m.Pipe.Valves(), public_alias="gpt-6-auto")

    async def test_configured_luna_fallback(self):
        body = await self.route(response=completed("{}"), valves=m.Pipe.Valves(GPT6_AUTO_FALLBACK_TARGET="luna"))
        self.assertEqual(body.model, "gpt-6-luna")

    async def test_legacy_auto_is_still_56_only(self):
        for model in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"):
            with self.subTest(model=model):
                body = await self.route(decision(model), alias="gpt-5.6-auto")
                self.assertEqual(body.model, model)
                schema = self.pipe.send_openai_responses_nonstreaming_request.call_args.args[0]["text"]["format"]["schema"]
                self.assertEqual(schema["properties"]["target_model"]["enum"], ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"])

    async def test_fixed_auto_preserves_model_and_effort_ceiling(self):
        for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra"):
            with self.subTest(model=model):
                self.pipe.send_openai_responses_nonstreaming_request = AsyncMock(return_value=completed(json.dumps({"reasoning_effort": "max", "explanation": "hard"})))
                body = await self.pipe._route_auto_reasoning("gpt-6-luna", m.ResponsesBody(model=model, input="hello"), [], m.Pipe.Valves(), public_alias=model + "-auto")
                self.assertEqual((body.model, body.reasoning["effort"]), (model, "high"))

    async def test_model_listing_with_saved_model_list_and_disabled_astra(self):
        self.pipe.valves = m.Pipe.Valves(MODEL_ID="gpt-6-auto,gpt-6-astra,gpt-6-astra-auto,gpt-5.6-ocr", ENABLE_GPT6_ASTRA=False)
        ids = [item["id"] for item in await self.pipe.pipes()]
        for model in ("gpt-6-auto", "gpt-6-sol", "gpt-6-luna", "gpt-6-sol-auto", "gpt-6-luna-auto", "gpt-6-ocr"):
            self.assertIn(model, ids)
        self.assertNotIn("gpt-6-astra", ids)
        self.assertNotIn("gpt-6-astra-auto", ids)


class ConfigurationTests(unittest.TestCase):
    def test_saved_valves_migrate_without_touching_credentials_or_legacy(self):
        for policy in ("terra_first", "legacy", "sol_first"):
            with self.subTest(policy=policy):
                original = dict(GPT6_AUTO_POLICY=policy, GPT6_AUTO_ROUTER_MODEL="gpt-5.6-luna", GPT6_AUTO_MAX_TARGET="terra",
                                GPT6_AUTO_FALLBACK_TARGET="terra", API_KEY="test-only", AUTO_MODEL_ROUTER_MODEL="gpt-5.6-luna")
                before = copy.deepcopy(original)
                valves = m.Pipe.Valves(**original)
                self.assertEqual(original, before)
                self.assertEqual(valves.GPT6_AUTO_POLICY, "sol_first")
                self.assertEqual(valves.GPT6_AUTO_ROUTER_MODEL, "gpt-6-luna")
                self.assertEqual(valves.GPT6_AUTO_MAX_TARGET, "sol")
                self.assertEqual(valves.GPT6_AUTO_FALLBACK_TARGET, "sol")
                self.assertEqual(valves.AUTO_MODEL_ROUTER_MODEL, "gpt-5.6-luna")
                self.assertEqual(valves.API_KEY, "test-only")
        self.assertEqual(m.Pipe.Valves(GPT6_AUTO_FALLBACK_TARGET="astra").GPT6_AUTO_FALLBACK_TARGET, "sol")
        self.assertEqual(m.Pipe.Valves(GPT6_AUTO_ROUTER_MODEL="custom-router").GPT6_AUTO_ROUTER_MODEL, "custom-router")

    def test_aliases_efforts_and_legacy_ocr(self):
        for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra"):
            with self.subTest(model=model):
                body = m.ResponsesBody(model="openai_responses." + model + "-auto", input="hello")
                self.assertEqual(body.model, model)
                self.assertNotIn("_auto_reasoning", body.model_dump())
                self.assertTrue(m.ModelFamily.supports("function_calling", model))
                self.assertEqual(m.ModelFamily.normalize_reasoning_effort(model, "minimal"), "low")
        self.assertEqual(m.ModelFamily.base_model("gpt-5.6-ocr"), "gpt-6-luna")
        self.assertEqual(m.Pipe.Valves().OCR_FALLBACK_MODEL, "gpt-6-sol")

    def test_gpt6_sampling_compatibility_and_no_mutation(self):
        for model in ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra"):
            for effort in (None, "none", "minimal", "high"):
                with self.subTest(model=model, effort=effort):
                    body = {"model": model, "input": "hello", "temperature": 0.4, "top_p": 0.8, "top_logprobs": 2,
                            "include": ["reasoning.encrypted_content", "message.output_text.logprobs"], "model_router_result": {"private": True}}
                    if effort:
                        body["reasoning"] = {"effort": effort, "summary": "auto"}
                    original = copy.deepcopy(body)
                    wire = m._prepare_responses_request(body)
                    self.assertEqual(body, original)
                    self.assertNotIn("model_router_result", wire)
                    sampling = effort == "none" and model != "gpt-6-astra"
                    self.assertEqual("temperature" in wire, sampling)
                    self.assertEqual("top_p" in wire, sampling)
                    self.assertEqual("top_logprobs" in wire, sampling)
                    self.assertEqual("message.output_text.logprobs" in wire["include"], sampling)
                    if model == "gpt-6-astra" and effort == "none":
                        self.assertEqual(wire["reasoning"]["effort"], "low")

    def test_legacy_parameters_preserved(self):
        body = {"model": "gpt-5.6-terra", "input": "hello", "temperature": 0.2}
        self.assertEqual(m._prepare_responses_request(body), body)

    def test_tools_build_for_both_new_models(self):
        registry = {"echo": {"spec": {"name": "echo", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}}}}
        valves = m.Pipe.Valves(REMOTE_MCP_SERVERS_JSON=json.dumps({"server_label": "test", "server_url": "https://example.invalid/mcp", "require_approval": "never"}))
        for model in ("gpt-6-luna", "gpt-6-sol"):
            body = m.ResponsesBody(model=model, input="hello", reasoning={"effort": "medium"}, tool_choice="auto")
            tools = m.build_tools(body, valves, registry)
            self.assertEqual({t["type"] for t in tools}, {"function", "web_search", "mcp"})
            function = next(t for t in tools if t["type"] == "function")
            self.assertEqual(function["name"], "echo")
            self.assertNotIn("function", function)  # Responses format, not Completions nesting.

    def test_cross_turn_reasoning_strip_keeps_tool_results(self):
        items = [{"type": "reasoning", "encrypted_content": "test"}, {"role": "user", "content": "hi"},
                 {"type": "function_call_output", "call_id": "call_1", "output": "result"}]
        self.assertEqual(m._strip_reasoning_items(items), items[1:])

    def test_router_receives_context_and_latest_media(self):
        items = [{"role": "user", "content": [{"type": "input_image", "image_url": "old"}]},
                 {"role": "assistant", "content": "This is a complex proof."},
                 {"role": "user", "content": [{"type": "input_text", "text": "continue"},
                      {"type": "input_image", "file_id": "file-image", "detail": "low"},
                      {"type": "input_file", "file_id": "file-document"}]}]
        routed = m._build_router_input(items, include_attachments=True)
        wire = json.dumps(routed["messages"])
        self.assertIn("complex proof", wire)
        self.assertIn("file-image", wire)
        self.assertIn("file-document", wire)
        self.assertNotIn('"old"', wire)


class FakeResponse:
    status = 200
    def __init__(self, payload=None, chunks=None, status=200):
        self.payload = payload or completed("OK")
        self.chunks = chunks or []
        self.status = status
        self.content = self
        self.reason = "mock error"
        self.headers = {"x-request-id": "req_test"}
        self.request_info = None
        self.history = ()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def json(self):
        return self.payload
    async def text(self):
        return json.dumps(self.payload)
    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pipe = m.Pipe()
        self.pipe.logger = logging.getLogger("test")

    async def test_nonstreaming_wire_request_and_continuation(self):
        session = FakeSession(FakeResponse())
        self.pipe._get_or_init_http_session = AsyncMock(return_value=session)
        body = {"model": "gpt-6-sol", "input": [{"type": "function_call", "call_id": "c1", "name": "echo", "arguments": "{}"},
                    {"type": "function_call_output", "call_id": "c1", "output": "hello"}],
                "reasoning": {"effort": "medium"}, "temperature": 0.7, "model_router_result": {"internal": True}}
        await self.pipe.send_openai_responses_nonstreaming_request(body, "fake-test-key", "https://example.invalid/v1/")
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://example.invalid/v1/responses")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-test-key")
        self.assertNotIn("temperature", kwargs["json"])
        self.assertNotIn("model_router_result", kwargs["json"])
        self.assertEqual(kwargs["json"]["input"], body["input"])

    async def test_streaming_fragmented_sse_and_wire_request(self):
        event = {"type": "response.output_text.delta", "delta": "안녕"}
        raw = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode()
        session = FakeSession(FakeResponse(chunks=[raw[:7], raw[7:61], raw[61:]]))
        self.pipe._get_or_init_http_session = AsyncMock(return_value=session)
        events = [e async for e in self.pipe.send_openai_responses_streaming_request(
            {"model": "gpt-6-luna", "input": "hello", "reasoning": {"effort": "low"}, "top_p": 0.9, "stream": True},
            "fake-test-key", "https://example.invalid/v1")]
        self.assertEqual(events, [event])
        self.assertNotIn("top_p", session.calls[0][1]["json"])
        self.assertTrue(session.calls[0][1]["json"]["stream"])

    async def test_api_errors_keep_model_access_detail(self):
        session = FakeSession(FakeResponse(payload={"error": {"code": "model_not_found", "message": "No access to gpt-6-sol"}}, status=404))
        self.pipe._get_or_init_http_session = AsyncMock(return_value=session)
        with self.assertRaisesRegex(RuntimeError, "model_not_found"):
            await self.pipe.send_openai_responses_nonstreaming_request({"model": "gpt-6-sol", "input": "hello"}, "fake-test-key", "https://example.invalid/v1")

    async def test_function_call_roundtrip_retains_call_id_and_model(self):
        call = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "echo", "arguments": '{"text":"hello"}'}
        responses = [{"status": "completed", "output": [call]}, completed("hello")]
        requests = []
        async def stream(body, **kwargs):
            requests.append(copy.deepcopy(body))
            yield {"type": "response.completed", "response": responses[len(requests) - 1]}
        self.pipe.send_openai_responses_streaming_request = stream
        self.pipe._execute_function_calls = AsyncMock(return_value=[{"type": "function_call_output", "call_id": "call_1", "output": "hello"}])
        body = m.ResponsesBody(model="gpt-6-sol", input="echo hello", stream=True, reasoning={"effort": "medium"})
        result = await self.pipe._run_streaming_loop(body, m.Pipe.Valves(PERSIST_TOOL_RESULTS=False), AsyncMock())
        self.assertEqual(result, "hello")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]["model"], "gpt-6-sol")
        self.assertEqual(requests[1]["reasoning"]["effort"], "medium")
        self.assertIn(call, requests[1]["input"])
        self.assertIn({"type": "function_call_output", "call_id": "call_1", "output": "hello"}, requests[1]["input"])


class PipeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the actual WebUI conversion/routing/tool-construction sequence."""
    async def run_pipe(self, model, stream=True, settings=None, effort=None):
        pipe = m.Pipe()
        pipe.valves = m.Pipe.Valves(**(settings or {}))
        pipe.send_openai_responses_nonstreaming_request = AsyncMock(return_value=completed(json.dumps(decision())))
        pipe._run_streaming_loop = AsyncMock(return_value="stream result")
        pipe._run_nonstreaming_loop = AsyncMock(return_value="nonstream result")
        body = {"model": "openai_responses." + model, "messages": [{"role": "user", "content": "Explain this algorithm"}],
                "stream": stream, "tool_choice": "auto", "temperature": 0.7}
        if effort:
            body["reasoning_effort"] = effort
        result = await pipe._pipe_impl(body, {"id": "test-user"}, None, AsyncMock(), None,
                                       {"model": {"id": "openai_responses." + model}},
                                       {"echo": {"spec": {"name": "echo", "parameters": {"type": "object", "properties": {}}}}})
        call = pipe._run_streaming_loop if stream else pipe._run_nonstreaming_loop
        return pipe, result, call.call_args.args[0]

    async def test_auto_works_when_astra_disabled_in_both_ui_paths(self):
        for stream in (True, False):
            with self.subTest(stream=stream):
                pipe, result, body = await self.run_pipe("gpt-6-auto", stream, {"ENABLE_GPT6_ASTRA": False})
                self.assertEqual(body.model, "gpt-6-sol")
                self.assertEqual(body.reasoning["effort"], "medium")
                self.assertEqual({t["type"] for t in body.tools}, {"function", "web_search"})
                self.assertEqual(pipe.send_openai_responses_nonstreaming_request.call_args.args[0]["model"], "gpt-6-luna")

    async def test_fixed_alias_uses_new_router_and_keeps_luna(self):
        pipe, result, body = await self.run_pipe("gpt-6-luna-auto")
        self.assertEqual(body.model, "gpt-6-luna")
        self.assertEqual(pipe.send_openai_responses_nonstreaming_request.call_args.args[0]["model"], "gpt-6-luna")

    async def test_direct_gpt6_minimal_normalized_before_building_tools(self):
        pipe, result, body = await self.run_pipe("gpt-6-sol", effort="minimal")
        self.assertEqual(body.reasoning["effort"], "low")
        self.assertIn("web_search", {t["type"] for t in body.tools})
        pipe.send_openai_responses_nonstreaming_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()

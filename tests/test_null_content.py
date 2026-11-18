"""Nullable WebUI history must not prevent a new request from reaching the API."""
import copy
import json
import unittest
from unittest.mock import AsyncMock
from test_responses import m, completed, decision


class NullContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_assistant_history_preserves_text_and_markers(self):
        marker = m.wrap_marker(m.create_marker("reasoning"))
        messages = [
            {"role": "assistant", "content": None},
            {"role": "assistant"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "이전 답변" + marker},
            {"role": "user", "content": "안녕"},
        ]
        original = copy.deepcopy(messages)
        result = await m.ResponsesBody.transform_messages_to_input(messages)
        self.assertEqual(result, [
            {"role": "assistant", "content": [{"type": "output_text", "text": "이전 답변"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "안녕"}]},
        ])
        self.assertEqual(messages, original)

    async def test_public_pipe_accepts_null_assistant_for_auto_model(self):
        for stream in (True, False):
            with self.subTest(stream=stream):
                pipe = m.Pipe()
                pipe.send_openai_responses_nonstreaming_request = AsyncMock(
                    return_value=completed(json.dumps(decision())))
                pipe._run_streaming_loop = AsyncMock(return_value="안녕하세요")
                pipe._run_nonstreaming_loop = AsyncMock(return_value="안녕하세요")
                body = {"model": "openai_responses.gpt-6-auto", "stream": stream,
                        "messages": [{"role": "user", "content": "안녕"},
                                     {"role": "assistant", "content": None}]}
                emitter = AsyncMock()
                result = await pipe.pipe(body, {"id": "test-user"}, None, emitter, None,
                                         {"model": {"id": body["model"]}}, None)
                self.assertEqual(result, "안녕하세요")
                loop = pipe._run_streaming_loop if stream else pipe._run_nonstreaming_loop
                loop.assert_awaited_once()
                self.assertEqual(loop.call_args.args[0].input, [
                    {"role": "user", "content": [{"type": "input_text", "text": "안녕"}]}])

    async def test_failure_logs_traceback_and_retains_ui_error(self):
        pipe = m.Pipe()
        pipe._pipe_impl = AsyncMock(side_effect=TypeError("test failure"))
        with self.assertLogs(pipe.logger.name, level="ERROR") as captured:
            result = await pipe.pipe({}, {"id": "test-user"}, None, AsyncMock(), None, {}, None)
        self.assertIn("요청 처리 실패: test failure", result)
        self.assertIsNotNone(captured.records[0].exc_info)

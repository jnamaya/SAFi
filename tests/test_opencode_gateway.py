#!/usr/bin/env python3
"""Regression tests for OpenCode -> SAFi gateway protocol translation.

OpenCode sends a full OpenAI chat transcript. The gateway intentionally does
not forward arbitrary client system instructions into SAFi, but it must preserve
the small, trusted runtime facts the governed agent needs: the active user turn,
the result and identity of tools run in that turn, and OpenCode's actual working
directory. Dropping those caused incorrect paths and repeated tool calls.

Run: venv/bin/python tests/test_opencode_gateway.py
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations import opencode_gateway as gateway


class GatewayTranslationTests(unittest.TestCase):
    def test_extracts_latest_user_and_current_turn_tool_result_metadata(self):
        messages = [
            {"role": "system", "content": "system instructions not forwarded"},
            {"role": "user", "content": "older question"},
            {"role": "assistant", "tool_calls": [{
                "id": "old-id", "type": "function",
                "function": {"name": "read", "arguments": '{"filePath":"old.py"}'},
            }]},
            {"role": "tool", "tool_call_id": "old-id", "content": "old result"},
            {"role": "user", "content": "review conscience.py"},
            {"role": "assistant", "tool_calls": [{
                "id": "current-id", "type": "function",
                "function": {
                    "name": "glob",
                    "arguments": '{"pattern":"**/conscience.py"}',
                },
            }]},
            {"role": "tool", "tool_call_id": "current-id", "content": "safi_app/core/faculties/conscience.py"},
        ]

        user, results = gateway._extract_user_and_tool_results(messages)

        self.assertEqual(user, "review conscience.py")
        self.assertEqual(results, [{
            "tool_name": "glob",
            "arguments": {"pattern": "**/conscience.py"},
            "result": "safi_app/core/faculties/conscience.py",
        }])

    def test_handles_structured_user_content_and_bad_tool_arguments(self):
        user, results = gateway._extract_user_and_tool_results([
            {"role": "user", "content": [{"type": "text", "text": "Find the file"}]},
            {"role": "assistant", "tool_calls": [{
                "id": "x", "function": {"name": "glob", "arguments": "not-json"},
            }]},
            {"role": "tool", "tool_call_id": "x", "content": {"files": ["x.py"]}},
        ])
        self.assertEqual(user, "Find the file")
        self.assertEqual(results[0]["tool_name"], "glob")
        self.assertEqual(results[0]["arguments"], {})
        self.assertEqual(json.loads(results[0]["result"]), {"files": ["x.py"]})

    def test_extracts_prior_context_but_not_current_user_or_system_prompt(self):
        messages = [
            {"role": "system", "content": "private client system prompt"},
            {"role": "user", "content": "Review conscience.py"},
            {"role": "assistant", "content": "I will locate and inspect it."},
            {"role": "assistant", "tool_calls": [{
                "id": "prior-read", "function": {
                    "name": "read", "arguments": '{"filePath":"conscience.py"}',
                },
            }]},
            {"role": "tool", "tool_call_id": "prior-read", "content": "source contents"},
            {"role": "assistant", "content": "It implements the auditor."},
            {"role": "user", "content": "Can you read intellect.py also?"},
        ]

        history = gateway._extract_recent_turns(messages)

        self.assertIn("User: Review conscience.py", history)
        self.assertIn("Assistant: It implements the auditor.", history)
        self.assertIn("Tool result: read({\"filePath\": \"conscience.py\"})", history)
        self.assertIn("source contents", history)
        self.assertNotIn("Can you read intellect.py also?", history)
        self.assertNotIn("private client system prompt", history)

    def test_extracts_only_workspace_path_lines_from_system_context(self):
        context = gateway._extract_workspace_context([
            {"role": "system", "content": (
                "Do not forward this arbitrary instruction.\n"
                "<env>\n"
                "  Working directory: /home/user/project/subdir\n"
                "  Workspace root folder: /home/user/project\n"
                "</env>"
            )},
        ])
        self.assertEqual(context, {
            "working_directory": "/home/user/project/subdir",
            "workspace_root": "/home/user/project",
        })

    def test_rejects_relative_or_multiline_workspace_values(self):
        context = gateway._extract_workspace_context([
            {"role": "system", "content": (
                "Working directory: ../../tmp\n"
                "Workspace root folder: /tmp\n"
            )},
        ])
        self.assertEqual(context, {
            "working_directory": None,
            "workspace_root": "/tmp",
        })

    def test_route_forwards_context_and_current_turn_result_only(self):
        backend_response = type("BackendResponse", (), {
            "status_code": 200,
            "json": lambda self: {"finalOutput": "I found the file.", "messageId": "m1"},
        })()
        messages = [
            {"role": "system", "content": (
                "<env>\n  Working directory: /home/user/project\n"
                "  Workspace root folder: /home/user/project\n</env>"
            )},
            {"role": "user", "content": "old request"},
            {"role": "assistant", "tool_calls": [{
                "id": "old", "function": {"name": "read", "arguments": "{}"},
            }]},
            {"role": "tool", "tool_call_id": "old", "content": "old output"},
            {"role": "user", "content": "review conscience.py"},
            {"role": "assistant", "tool_calls": [{
                "id": "new", "function": {
                    "name": "glob", "arguments": '{"pattern":"**/conscience.py"}',
                },
            }]},
            {"role": "tool", "tool_call_id": "new", "content": "found path"},
        ]

        with patch.object(gateway, "SAFI_API_KEY", "test-key"), \
             patch.object(gateway.requests, "post", return_value=backend_response) as post:
            response = gateway.app.test_client().post(
                "/v1/chat/completions",
                json={"model": "coding_harness", "messages": messages},
                headers={"Authorization": "Bearer test-key"},
            )

        self.assertEqual(response.status_code, 200)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["message"], "review conscience.py")
        self.assertIn("User: old request", payload["recent_turns"])
        self.assertIn("old output", payload["recent_turns"])
        self.assertNotIn("review conscience.py", payload["recent_turns"])
        self.assertEqual(payload["workspace_context"], {
            "working_directory": "/home/user/project",
            "workspace_root": "/home/user/project",
        })
        self.assertEqual(payload["tool_results"], [{
            "tool_name": "glob",
            "arguments": {"pattern": "**/conscience.py"},
            "result": "found path",
        }])
        self.assertNotIn("old output", json.dumps(payload["tool_results"]))
        self.assertNotIn("arbitrary instruction", json.dumps(payload))

    def test_streaming_tool_call_is_returned_as_sse_deltas(self):
        backend_response = type("BackendResponse", (), {
            "status_code": 200,
            "json": lambda self: {
                "type": "tool_call",
                "tool_name": "read",
                "parameters": {"filePath": "safi_app/core/faculties/conscience.py"},
                "messageId": "msg-123",
                "willDecision": "approve",
                "token_usage": {
                    "prompt_tokens": 900,
                    "completion_tokens": 35,
                    "total_tokens": 935,
                },
            },
        })()
        progress_response = type("ProgressResponse", (), {
            "status_code": 200,
            "json": lambda self: {"progress": ["checking_request", "analyzing", "checking_tool"]},
        })()
        with patch.object(gateway, "SAFI_API_KEY", "test-key"), \
             patch.object(gateway.requests, "post", return_value=backend_response), \
             patch.object(gateway.requests, "get", return_value=progress_response):
            response = gateway.app.test_client().post(
                "/v1/chat/completions",
                json={
                    "model": "coding_harness",
                    "stream": True,
                    "messages": [{"role": "user", "content": "Read conscience.py"}],
                    "tools": [{"type": "function", "function": {"name": "read"}}],
                },
                headers={"Authorization": "Bearer test-key"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.mimetype.startswith("text/event-stream"))
        chunks = [
            json.loads(line[len("data: "):])
            for line in response.get_data(as_text=True).splitlines()
            if line.startswith("data: {")
        ]
        tool_chunk = next(
            chunk for chunk in chunks
            if chunk.get("choices")
            and chunk["choices"][0]["delta"].get("tool_calls")
        )
        tool_delta = tool_chunk["choices"][0]["delta"]["tool_calls"][0]
        self.assertEqual(tool_delta["function"]["name"], "read")
        self.assertEqual(json.loads(tool_delta["function"]["arguments"]), {
            "filePath": "safi_app/core/faculties/conscience.py",
        })
        finish_chunk = next(
            chunk for chunk in reversed(chunks)
            if chunk.get("choices") and chunk["choices"][0].get("finish_reason")
        )
        self.assertEqual(finish_chunk["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(next(c for c in chunks if c.get("usage"))["usage"], {
            "prompt_tokens": 900,
            "completion_tokens": 35,
            "total_tokens": 935,
        })

    def test_nonstream_completion_includes_provider_token_usage(self):
        backend_response = type("BackendResponse", (), {
            "status_code": 200,
            "json": lambda self: {
                "finalOutput": "Done.",
                "token_usage": {
                    "prompt_tokens": 77,
                    "completion_tokens": 4,
                    "total_tokens": 81,
                },
            },
        })()
        with patch.object(gateway, "SAFI_API_KEY", "test-key"), \
             patch.object(gateway.requests, "post", return_value=backend_response):
            response = gateway.app.test_client().post(
                "/v1/chat/completions",
                json={"model": "coding_harness", "messages": [{"role": "user", "content": "Do it"}]},
                headers={"Authorization": "Bearer test-key"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["usage"], {
            "prompt_tokens": 77,
            "completion_tokens": 4,
            "total_tokens": 81,
        })

    def test_model_alias_maps_to_registered_safi_agent(self):
        backend_response = type("BackendResponse", (), {
            "status_code": 200,
            "json": lambda self: {"finalOutput": "Done."},
        })()
        with patch.object(gateway, "SAFI_API_KEY", "test-key"), \
             patch.dict(gateway.MODEL_AGENT_MAP, {"coding_harness": "coding_harness"}), \
             patch.object(gateway.requests, "post", return_value=backend_response) as post:
            response = gateway.app.test_client().post(
                "/v1/chat/completions",
                json={"model": "coding_harness", "messages": [{"role": "user", "content": "Review this project"}]},
                headers={"Authorization": "Bearer test-key"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_args.kwargs["json"]["agent"], "coding_harness")

    def test_coding_harness_model_supplies_connector_declaration(self):
        backend_response = type("BackendResponse", (), {
            "status_code": 200,
            "json": lambda self: {"finalOutput": "Done."},
        })()
        with patch.object(gateway, "SAFI_API_KEY", "test-key"), \
             patch.dict(gateway.MODEL_AGENT_MAP, {"coding_harness": "coding_harness"}), \
             patch.object(gateway.requests, "post", return_value=backend_response) as post:
            response = gateway.app.test_client().post(
                "/v1/chat/completions",
                json={"model": "coding_harness", "messages": [{"role": "user", "content": "Explain this code"}]},
                headers={"Authorization": "Bearer test-key"},
            )

        self.assertEqual(response.status_code, 200)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["agent"], "coding_harness")
        self.assertNotIn("coding_harness", payload.get("tools", []))

    def test_streaming_turn_forwards_safe_progress_as_reasoning_deltas(self):
        backend_response = type("BackendResponse", (), {
            "status_code": 200,
            "json": lambda self: {
                "finalOutput": "The policy wizard edits software policy settings.",
                "messageId": "server-message",
                "willDecision": "approve",
                "token_usage": {
                    "prompt_tokens": 3210,
                    "completion_tokens": 140,
                    "total_tokens": 3350,
                },
            },
        })()
        progress_response = type("ProgressResponse", (), {
            "status_code": 200,
            "json": lambda self: {
                "progress": ["checking_request", "analyzing", "auditing", "alignment", "finalizing"],
                "complete": True,
            },
        })()
        with patch.object(gateway, "SAFI_API_KEY", "test-key"), \
             patch.object(gateway.requests, "post", return_value=backend_response) as post, \
             patch.object(gateway.requests, "get", return_value=progress_response) as get:
            response = gateway.app.test_client().post(
                "/v1/chat/completions",
                json={
                    "model": "coding_harness",
                    "stream": True,
                    "user": "tester",
                    "messages": [{"role": "user", "content": "What does the policy wizard do?"}],
                },
                headers={"Authorization": "Bearer test-key"},
            )
            body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        chunks = [
            json.loads(line[len("data: "):])
            for line in body.splitlines()
            if line.startswith("data: {")
        ]
        chunks_with_choices = [chunk for chunk in chunks if chunk.get("choices")]
        reasoning = "".join(
            chunk["choices"][0]["delta"].get("reasoning_content", "")
            for chunk in chunks_with_choices
        )
        answer = "".join(
            chunk["choices"][0]["delta"].get("content", "")
            for chunk in chunks_with_choices
        )
        self.assertIn("SAFi: Analyzing the request…", reasoning)
        self.assertIn("SAFi: Auditing the response against policy…", reasoning)
        self.assertEqual(answer, "The policy wizard edits software policy settings.")
        finish_chunk = next(
            chunk for chunk in reversed(chunks)
            if chunk.get("choices") and chunk["choices"][0].get("finish_reason")
        )
        self.assertEqual(finish_chunk["choices"][0]["finish_reason"], "stop")
        usage_chunk = next(chunk for chunk in chunks if chunk.get("usage"))
        self.assertEqual(usage_chunk["usage"], {
            "prompt_tokens": 3210,
            "completion_tokens": 140,
            "total_tokens": 3350,
        })
        self.assertIn("message_id", post.call_args.kwargs["json"])
        self.assertIn("/progress/", get.call_args.args[0])


class DockerGatewayPackagingTests(unittest.TestCase):
    def test_compose_gateway_runs_from_image_with_a_separate_secret_file(self):
        root = Path(__file__).resolve().parent.parent
        dockerfile = (root / "Dockerfile").read_text()
        compose = (root / "docker-compose.yml").read_text()
        entrypoint = (root / "docker-entrypoint.sh").read_text()
        dockerignore = (root / ".dockerignore").read_text()
        env_example = (root / "gateways" / "opencode-gateway.env.example").read_text()

        self.assertIn("COPY integrations/ ./integrations/", dockerfile)
        self.assertIn("opencode-gateway:", compose)
        self.assertIn('profiles: ["opencode"]', compose)
        self.assertIn("SAFI_OPENAI_API_URL: \"http://app:5000/api/harness/process_prompt\"", compose)
        self.assertIn('"127.0.0.1:${OPENCODE_GATEWAY_PORT:-5002}:5002"', compose)
        self.assertIn("SERVICE: opencode-gateway", compose)
        self.assertIn('"${SERVICE}" = "opencode-gateway"', entrypoint)
        self.assertIn("SAFI_POLICY_API_KEY=", env_example)
        self.assertIn("gateways/*.env", dockerignore)
        self.assertIn("opencode.json", dockerignore)


if __name__ == "__main__":
    unittest.main(verbosity=2)

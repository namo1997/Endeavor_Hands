import json
import unittest

from client.api_chat import ResponsesTunnelChat, _output_text


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class ResponsesTunnelChatTests(unittest.TestCase):
    def test_requires_a_tunnel_identifier(self):
        with self.assertRaises(ValueError):
            ResponsesTunnelChat(api_key="sk-test", tunnel_id="not-a-tunnel")

    def test_initial_request_uses_tunnel_and_always_requires_approval(self):
        captured = []

        def opener(request, timeout):
            captured.append(json.loads(request.data.decode("utf-8")))
            return _FakeHTTPResponse(
                {
                    "id": "resp_1",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "พร้อม"}],
                        }
                    ],
                }
            )

        chat = ResponsesTunnelChat(
            api_key="sk-test", tunnel_id="tunnel_test", opener=opener
        )
        self.assertEqual(chat.send("สวัสดี"), "พร้อม")
        self.assertEqual(captured[0]["input"], "สวัสดี")
        self.assertEqual(captured[0]["tools"][0]["tunnel_id"], "tunnel_test")
        self.assertEqual(captured[0]["tools"][0]["require_approval"], "always")
        self.assertNotIn("server_url", captured[0]["tools"][0])

    def test_approval_response_is_chained_to_requesting_response(self):
        captured = []
        responses = iter(
            [
                {
                    "id": "resp_request",
                    "output": [
                        {
                            "id": "mcpr_1",
                            "type": "mcp_approval_request",
                            "name": "read_file",
                            "arguments": '{"path":"/tmp/example"}',
                        }
                    ],
                },
                {
                    "id": "resp_final",
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "total_tokens": 25,
                    },
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "done"}],
                        }
                    ],
                },
            ]
        )

        def opener(request, timeout):
            captured.append(json.loads(request.data.decode("utf-8")))
            return _FakeHTTPResponse(next(responses))

        chat = ResponsesTunnelChat(
            api_key="sk-test",
            tunnel_id="tunnel_test",
            opener=opener,
            approval_prompt=lambda prompt: "y",
            output=lambda text: None,
        )
        self.assertEqual(chat.send("read it"), "done")
        self.assertEqual(captured[1]["previous_response_id"], "resp_request")
        self.assertEqual(
            captured[1]["input"],
            [
                {
                    "type": "mcp_approval_response",
                    "approval_request_id": "mcpr_1",
                    "approve": True,
                }
            ],
        )
        self.assertEqual(chat.previous_response_id, "resp_final")
        self.assertEqual(chat.last_turn_usage["total_tokens"], 25)
        self.assertIn("total 25 tokens", chat.usage_summary())

    def test_follow_up_uses_previous_response(self):
        captured = []
        responses = iter(
            [
                {"id": "resp_1", "output_text": "one", "output": []},
                {"id": "resp_2", "output_text": "two", "output": []},
            ]
        )

        def opener(request, timeout):
            captured.append(json.loads(request.data.decode("utf-8")))
            return _FakeHTTPResponse(next(responses))

        chat = ResponsesTunnelChat(
            api_key="sk-test", tunnel_id="tunnel_test", opener=opener
        )
        chat.send("first")
        chat.send("second")
        self.assertEqual(captured[1]["previous_response_id"], "resp_1")

    def test_output_text_falls_back_to_message_content(self):
        self.assertEqual(
            _output_text(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "first"},
                                {"type": "output_text", "text": "second"},
                            ],
                        }
                    ]
                }
            ),
            "first\nsecond",
        )


if __name__ == "__main__":
    unittest.main()

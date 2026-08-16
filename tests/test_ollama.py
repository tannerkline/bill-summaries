import unittest
from unittest.mock import Mock, patch

from models.ollama import OllamaGenerationError, generate_summary


class GenerateSummaryTests(unittest.TestCase):
    @patch("models.ollama.requests.post")
    def test_posts_non_streaming_request_to_configured_ollama_server(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {"response": "  Plain-language summary.  "}
        post.return_value = response

        with patch.dict(
            "os.environ",
            {
                "OLLAMA_BASE_URL": "http://ollama.test:11434/",
                "OLLAMA_MODEL": "local-bill-model",
                "OLLAMA_TIMEOUT_SECONDS": "120",
                "OLLAMA_THINK": "false",
            },
            clear=False,
        ):
            summary = generate_summary("Summarize this bill", max_tokens=250)

        self.assertEqual(summary, "Plain-language summary.")
        post.assert_called_once_with(
            "http://ollama.test:11434/api/generate",
            json={
                "model": "local-bill-model",
                "prompt": "Summarize this bill",
                "stream": False,
                "think": False,
                "options": {"num_predict": 250, "temperature": 0.2},
            },
            timeout=120,
        )

    @patch("models.ollama.requests.post")
    def test_rejects_empty_responses(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "response": " ",
            "thinking": "internal reasoning",
            "done_reason": "length",
            "eval_count": 1_000,
        }
        post.return_value = response

        with self.assertRaisesRegex(
            OllamaGenerationError,
            "done_reason='length'.*thinking_chars=18",
        ):
            generate_summary("Summarize this bill")

    @patch("models.ollama.requests.post")
    def test_can_explicitly_enable_thinking(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {"response": "Summary."}
        post.return_value = response

        with patch.dict("os.environ", {"OLLAMA_THINK": "true"}, clear=False):
            generate_summary("Summarize this bill")

        self.assertTrue(post.call_args.kwargs["json"]["think"])


if __name__ == "__main__":
    unittest.main()

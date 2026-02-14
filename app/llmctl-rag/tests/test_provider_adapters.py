import io
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from provider_adapters import GeminiEmbeddingFunction, build_embedding_function
from tests.helpers import test_config


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class ProviderAdaptersTests(unittest.TestCase):
    def test_build_embedding_function_uses_gemini_http_adapter(self):
        config = replace(
            test_config(),
            embed_provider="gemini",
            gemini_api_key="gemini-key",
            gemini_embedding_model="models/gemini-embedding-001",
        )
        embedding_fn = build_embedding_function(config)
        self.assertIsInstance(embedding_fn, GeminiEmbeddingFunction)

    def test_gemini_embedding_parses_batch_response(self):
        captured_requests = []

        def _fake_urlopen(request, timeout=60):
            captured_requests.append((request.full_url, timeout, request.data))
            return _FakeResponse(
                {
                    "embeddings": [
                        {"values": [0.1, 0.2]},
                        {"embedding": {"values": [0.3, 0.4]}},
                    ]
                }
            )

        embedding_fn = GeminiEmbeddingFunction(
            api_key="gemini-key",
            model_name="gemini-embedding-001",
        )
        with patch("provider_adapters.urlopen", _fake_urlopen):
            vectors = embedding_fn(["alpha", "beta"])

        np.testing.assert_allclose(
            np.array([[0.1, 0.2], [0.3, 0.4]]),
            np.array([item.tolist() for item in vectors]),
            rtol=1e-6,
            atol=1e-6,
        )
        self.assertEqual(1, len(captured_requests))
        url, timeout, raw_payload = captured_requests[0]
        payload = json.loads(raw_payload.decode("utf-8"))
        self.assertIn(":batchEmbedContents", url)
        self.assertEqual(60, timeout)
        self.assertEqual(2, len(payload.get("requests", [])))

    def test_gemini_embedding_http_error_has_detail(self):
        error = HTTPError(
            url="https://example.invalid",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b"rate limit"),
        )

        def _raise_error(request, timeout=60):
            raise error

        embedding_fn = GeminiEmbeddingFunction(
            api_key="gemini-key",
            model_name="gemini-embedding-001",
        )
        with patch("provider_adapters.urlopen", _raise_error):
            with self.assertRaisesRegex(RuntimeError, "rate limit"):
                embedding_fn(["alpha"])

    def test_gemini_embedding_supports_embed_query_and_documents(self):
        captured_texts = []

        def _fake_embed(*, api_key, model_name, texts, batch_size=64):
            captured_texts.append(list(texts))
            return [[float(index)] for index, _ in enumerate(texts, start=1)]

        embedding_fn = GeminiEmbeddingFunction(
            api_key="gemini-key",
            model_name="gemini-embedding-001",
        )
        with patch("provider_adapters._embed_gemini_texts", _fake_embed):
            documents = embedding_fn.embed_documents(["alpha", "beta"])
            query = embedding_fn.embed_query(["question"])
            callable_docs = embedding_fn(["gamma"])

        self.assertTrue(all(isinstance(item, np.ndarray) for item in documents))
        self.assertTrue(all(isinstance(item, np.ndarray) for item in query))
        self.assertTrue(all(isinstance(item, np.ndarray) for item in callable_docs))
        self.assertEqual([[1.0], [2.0]], [item.tolist() for item in documents])
        self.assertEqual([[1.0]], [item.tolist() for item in query])
        self.assertEqual([[1.0]], [item.tolist() for item in callable_docs])
        self.assertEqual(
            [
                ["alpha", "beta"],
                ["question"],
                ["gamma"],
            ],
            captured_texts,
        )

    def test_build_embedding_function_loads_openai_class_lazily(self):
        class _FakeOpenAIEmbeddingFunction:
            def __init__(self, api_key, model_name):
                self.api_key = api_key
                self.model_name = model_name

        config = replace(
            test_config(),
            embed_provider="openai",
            openai_api_key="openai-key",
            openai_embedding_model="text-embedding-3-small",
        )
        with patch(
            "provider_adapters._load_openai_embedding_function",
            return_value=_FakeOpenAIEmbeddingFunction,
        ):
            embedding_fn = build_embedding_function(config)
        self.assertEqual("openai-key", embedding_fn.api_key)
        self.assertEqual("text-embedding-3-small", embedding_fn.model_name)


if __name__ == "__main__":
    unittest.main()

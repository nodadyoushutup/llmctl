from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from chat.contracts import (
    RAGCollection,
    RAGContractError,
    RAGHealth,
    RAGRetrievalRequest,
    RAGRetrievalResponse,
    RAG_HEALTH_CONFIGURED_HEALTHY,
    RAG_HEALTH_UNCONFIGURED,
    RAG_REASON_RETRIEVAL_FAILED,
)


class RAGContractClient(Protocol):
    def health(self) -> RAGHealth: ...

    def list_collections(self) -> list[RAGCollection]: ...

    def retrieve(self, payload: RAGRetrievalRequest) -> RAGRetrievalResponse: ...


@dataclass(slots=True)
class StubRAGContractClient:
    health_result: RAGHealth = field(
        default_factory=lambda: RAGHealth(state=RAG_HEALTH_UNCONFIGURED, provider="chroma")
    )
    collections: list[RAGCollection] = field(default_factory=list)
    retrieval_response: RAGRetrievalResponse = field(default_factory=RAGRetrievalResponse)

    def health(self) -> RAGHealth:
        return self.health_result

    def list_collections(self) -> list[RAGCollection]:
        return list(self.collections)

    def retrieve(self, payload: RAGRetrievalRequest) -> RAGRetrievalResponse:
        if self.health_result.state != RAG_HEALTH_CONFIGURED_HEALTHY:
            raise RAGContractError(
                reason_code=RAG_REASON_RETRIEVAL_FAILED,
                message="Stubbed RAG retrieval unavailable.",
                metadata={
                    "rag_health_state": self.health_result.state,
                    "selected_collections": payload.collections,
                    "provider": self.health_result.provider,
                },
            )
        return self.retrieval_response


@dataclass(slots=True)
class HttpRAGContractClient:
    base_url: str
    timeout_seconds: float = 2.0

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, method=method, headers=headers, data=data)
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RAGContractError(
                reason_code=RAG_REASON_RETRIEVAL_FAILED,
                message=body or str(exc),
                metadata={"status": exc.code, "path": path},
            ) from exc
        except URLError as exc:
            raise RAGContractError(
                reason_code=RAG_REASON_RETRIEVAL_FAILED,
                message=str(exc),
                metadata={"path": path},
            ) from exc
        try:
            decoded = json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise RAGContractError(
                reason_code=RAG_REASON_RETRIEVAL_FAILED,
                message=f"Invalid RAG contract JSON response for {path}.",
                metadata={"body": body[:240]},
            ) from exc
        if not isinstance(decoded, dict):
            raise RAGContractError(
                reason_code=RAG_REASON_RETRIEVAL_FAILED,
                message=f"Invalid RAG contract response payload type for {path}.",
            )
        return decoded

    def health(self) -> RAGHealth:
        payload = self._request_json(method="GET", path="/api/rag/contract/health")
        state = str(payload.get("state") or "").strip() or RAG_HEALTH_UNCONFIGURED
        provider = str(payload.get("provider") or "chroma")
        error = str(payload.get("error") or "").strip() or None
        return RAGHealth(state=state, provider=provider, error=error)

    def list_collections(self) -> list[RAGCollection]:
        payload = self._request_json(method="GET", path="/api/rag/contract/collections")
        provider = str(payload.get("provider") or "chroma")
        rows = payload.get("collections")
        if not isinstance(rows, list):
            return []
        collections: list[RAGCollection] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            coll_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip() or coll_id
            if not coll_id or not name:
                continue
            collections.append(
                RAGCollection(
                    id=coll_id,
                    name=name,
                    provider=provider,
                    status=str(row.get("status") or "").strip() or None,
                )
            )
        return collections

    def retrieve(self, payload: RAGRetrievalRequest) -> RAGRetrievalResponse:
        response = self._request_json(
            method="POST",
            path="/api/rag/contract/retrieve",
            payload={
                "question": payload.question,
                "collections": payload.collections,
                "top_k": payload.top_k,
                "model_id": payload.model_id,
                "request_id": payload.request_id,
            },
        )
        retrieval_context = response.get("retrieval_context")
        normalized_context: list[str] = []
        if isinstance(retrieval_context, list):
            for item in retrieval_context:
                if isinstance(item, str):
                    cleaned = item.strip()
                    if cleaned:
                        normalized_context.append(cleaned)
                elif isinstance(item, dict):
                    value = str(item.get("text") or item.get("content") or "").strip()
                    if value:
                        normalized_context.append(value)
        elif isinstance(retrieval_context, str):
            cleaned = retrieval_context.strip()
            if cleaned:
                normalized_context.append(cleaned)
        citation_records = response.get("citation_records")
        if not isinstance(citation_records, list):
            citation_records = []
        return RAGRetrievalResponse(
            answer=response.get("answer")
            if isinstance(response.get("answer"), str) or response.get("answer") is None
            else str(response.get("answer")),
            retrieval_context=normalized_context,
            retrieval_stats=response.get("retrieval_stats")
            if isinstance(response.get("retrieval_stats"), dict)
            else {},
            synthesis_error=response.get("synthesis_error")
            if isinstance(response.get("synthesis_error"), dict)
            else None,
            mode=str(response.get("mode") or "query"),
            collections=[
                str(item)
                for item in (response.get("collections") or [])
                if str(item).strip()
            ],
            citation_records=[
                item for item in citation_records if isinstance(item, dict)
            ],
        )


_rag_client_override: RAGContractClient | None = None


def set_rag_contract_client(client: RAGContractClient | None) -> None:
    global _rag_client_override
    _rag_client_override = client


def get_rag_contract_client() -> RAGContractClient:
    if _rag_client_override is not None:
        return _rag_client_override
    base_url = (os.getenv("CHAT_RAG_CONTRACT_BASE_URL") or "").strip()
    if not base_url:
        return StubRAGContractClient()
    return HttpRAGContractClient(base_url=base_url)

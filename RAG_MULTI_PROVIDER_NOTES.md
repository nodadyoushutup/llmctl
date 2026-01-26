# RAG multi-provider notes (theory)

## Goal (theory)
- Support Gemini for generation and embeddings (not optional), alongside existing OpenAI usage.
- Support an alternative vector store: Google Vertex RAG Engine, alongside ChromaDB.
- No implementation yet; capture considerations and likely adapter work.

## Provider choice (global)
- Embeddings are required, not optional.
- Provide a model + API keys to select either OpenAI or Google for all AI tasks.
- The provider choice applies to both generation and embeddings.

## Gemini (generation)
- Feasible to swap the LLM call layer while keeping Chroma retrieval.
- Requires an LLM provider abstraction so prompts + retrieved chunks can be routed to Gemini.

## Gemini (embeddings)
- Requires an embedding provider abstraction (keys/models/config).
- Switching embedding models implies a full re-index (different vector space).

## Vertex RAG Engine (vector store/retrieval)
- Requires a new vector store/retriever adapter; Chroma ingest/query flow won’t map 1:1.
- Likely needs a parallel ingest path using Vertex APIs (often via GCS + index config).
- Query semantics/filters/metadata fields need a mapping layer to Vertex capabilities.

## Cross-cutting changes (conceptual)
- Introduce interface boundaries:
  - EmbeddingProvider
  - LLMProvider
  - VectorStore/Retriever
- Keep business logic agnostic to the underlying provider.

## Practical implications
- Re-index when changing embeddings or stores.
- Ensure chunking strategy is compatible with Vertex ingestion (or adapt to Vertex chunking).
- Additional auth/config for Gemini + Vertex (keys, project, region, models).

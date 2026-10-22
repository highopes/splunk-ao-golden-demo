"""
LangGraph RAG Integration
Handles RAG retrieval logic for LangGraph agents using LangChain's retrieval chain pattern.
Uses PostgreSQL with pgvector for vector storage.
"""
import asyncio
import json
import os
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from helpers.llm_utils import (
    get_chat_model,
    get_default_chat_model,
    get_llm_provider,
    get_domain_chat_model,
)
from helpers.pgvector_utils import get_pgvector_store, strict_index_provider, verify_strict_index
from domain_manager import DomainManager
from helpers.agent_control_helpers import domain_controlled_tool
from setup_env import setup_environment


# Global cache for RAG instances
_rag_cache = {}

_RAG_MODES = ("chain", "documents")
# Source metadata surfaced to the agent in documents mode (when present).
_CITATION_METADATA_KEYS = (
    "fact_id",
    "vendor",
    "sku",
    "attribute",
    "value",
    "unit",
    "source_title",
    "source_url",
    "source_section",
    "source_updated_at",
    "verified_at",
)


# Matches langchain-ai/retrieval-qa-chat without pulling from LangChain Hub.
_RETRIEVAL_QA_CHAT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Answer any user questions based solely on the context below:\n\n"
            "<context>\n{context}\n</context>\n\n"
            "If you don't know the answer, just say that you don't know, "
            "don't try to make up an answer.",
        ),
        ("human", "{input}"),
    ]
)


class DomainRAGSystem:
    """RAG system for a specific domain with eager initialization.

    ``rag.mode: chain`` (default) answers through an inner retrieval chain LLM.
    ``rag.mode: documents`` returns the retrieved chunks and their source
    metadata directly, so the agent model is the only application LLM.
    """

    def __init__(self, domain_name: str, top_k: int = 5, model_name: Optional[str] = None):
        self.domain_name = domain_name
        self.top_k = top_k
        self.model_name = model_name
        self.retrieval_chain = None
        self.retriever = None
        self.mode = "chain"
        self.index_info: dict = {}
        self._initialized = False

        self.initialize()

    def initialize(self):
        """Initialize the RAG system with eager loading"""
        if self._initialized:
            return

        try:
            domain_manager = DomainManager()
            domain_config = domain_manager.load_domain_config(self.domain_name)

            rag_config = domain_config.config.get("rag", {})
            vectorstore_config = domain_config.config.get("vectorstore", {})
            model_config = domain_config.config.get("model", {})

            mode = str(rag_config.get("mode") or "chain").strip().lower()
            if mode not in _RAG_MODES:
                raise ValueError(f"Unsupported rag.mode '{mode}'; use one of {_RAG_MODES}")
            self.mode = mode

            chat_provider = get_llm_provider()

            _provider_default_model = {
                "hosted": model_config.get("hosted_default_model"),
                "bedrock": model_config.get("bedrock_default_model"),
            }.get(chat_provider, model_config.get("default_model"))

            llm_model = (
                self.model_name
                or _provider_default_model
                or model_config.get("default_model")
                or model_config.get(
                    "model_name", get_default_chat_model(provider=chat_provider)
                )
            )

            setup_environment(self.domain_name, domain_config.config)

            if not os.environ.get("POSTGRES_PASSWORD"):
                raise ValueError(
                    "POSTGRES_PASSWORD not found. Please add it to .streamlit/secrets.toml"
                )

            # Selects the prebuilt index matching the active provider (Ollama,
            # OpenAI, or Bedrock), falling back to whichever index exists. Raises
            # a clear error pointing at setup_vectordb.py if none has been built.
            # Strict-index domains are pinned to one provider with no fallback.
            if strict_index_provider(vectorstore_config):
                self.index_info = verify_strict_index(self.domain_name, vectorstore_config)
            vector_store, collection_name = get_pgvector_store(
                self.domain_name, vectorstore_config=vectorstore_config
            )
            self.index_info.setdefault("collection_name", collection_name)

            retriever = vector_store.as_retriever(search_kwargs={"k": self.top_k})
            self.retriever = retriever

            if self.mode == "documents":
                self._initialized = True
                print(
                    f"✅ RAG system initialized for domain '{self.domain_name}' "
                    f"(documents mode, index: {self.index_info['collection_name']})"
                )
                return

            llm = get_chat_model(
                llm_model,
                temperature=0.1,
                name=f"{self.domain_name.title()} RAG Assistant",
                provider=chat_provider,
            )

            combine_docs_chain = create_stuff_documents_chain(llm, _RETRIEVAL_QA_CHAT_PROMPT)
            self.retrieval_chain = create_retrieval_chain(retriever, combine_docs_chain)

            self._initialized = True
            print(
                f"✅ RAG system initialized for domain '{self.domain_name}' (model: {llm_model})"
            )

        except Exception as e:
            print(f"❌ Error initializing RAG system for domain '{self.domain_name}': {e}")
            import traceback

            traceback.print_exc()
            self._initialized = False
            raise

    async def search_documents(self, query: str, config=None) -> dict:
        """Return retrieved chunks with source metadata (documents mode contract)."""
        if self.retriever is None:
            raise RuntimeError(f"RAG retriever not initialized for domain '{self.domain_name}'")
        docs = await asyncio.to_thread(self.retriever.invoke, query, config)
        documents = []
        for rank, doc in enumerate(docs, start=1):
            item = {"rank": rank, "content": doc.page_content}
            for key in _CITATION_METADATA_KEYS:
                value = doc.metadata.get(key)
                if value not in (None, ""):
                    item[key] = value
            documents.append(item)
        return {
            "query": query,
            "retrieval": {
                "collection": self.index_info.get("collection_name"),
                "embedding_provider": self.index_info.get("embedding_provider"),
                "embedding_model": self.index_info.get("embedding_model"),
                "top_k": self.top_k,
            },
            "documents": documents,
        }

    async def search(self, query: str, config=None) -> str:
        """Search the domain's knowledge base (no @control — applied at tool boundary)."""
        if self.mode == "documents":
            try:
                return json.dumps(
                    await self.search_documents(query, config=config), ensure_ascii=False
                )
            except Exception as e:
                return f"❌ Error during RAG search for domain '{self.domain_name}': {str(e)}"

        if not self.retrieval_chain:
            return (
                f"❌ RAG system not initialized for domain '{self.domain_name}'. "
                "Please check your vector database setup."
            )

        try:
            # PGVector is created in sync mode; use invoke (not ainvoke) in a thread
            # so we don't block the event loop or require async_mode on the store.
            result = await asyncio.to_thread(
                self.retrieval_chain.invoke, {"input": query}, config
            )
            # print(f"---> RAG result: {result}")
            return result["answer"]
        except Exception as e:
            return f"❌ Error during RAG search for domain '{self.domain_name}': {str(e)}"


def get_domain_rag_system(
    domain_name: str,
    top_k: int = None,
    model_name: Optional[str] = None,
) -> DomainRAGSystem:
    """Get or create a RAG system instance with caching (per domain, top_k, and model)."""
    if top_k is None:
        try:
            domain_manager = DomainManager()
            domain_config = domain_manager.load_domain_config(domain_name)
            rag_config = domain_config.config.get("rag", {})
            top_k = rag_config.get("top_k", 5)
        except Exception:
            top_k = 5

    if model_name is None:
        cfg = DomainManager().load_domain_config(domain_name)
        model_name = get_domain_chat_model(cfg.config)

    cache_key = f"{domain_name}_{top_k}_{model_name or 'default'}_{get_llm_provider()}"
    if cache_key not in _rag_cache:
        _rag_cache[cache_key] = DomainRAGSystem(domain_name, top_k, model_name=model_name)
    return _rag_cache[cache_key]


def create_domain_rag_tool(
    domain_name: str,
    top_k: int = None,
    model_name: Optional[str] = None,
):
    """
    Create a LangChain retrieval chain tool that works with GalileoCallback automatically.

    Args:
        domain_name: Name of the domain
        top_k: Default number of documents to retrieve
        model_name: Optional model override (e.g. from sidebar)

    Returns:
        LangChain tool that uses retrieval chain
    """
    rag_system = get_domain_rag_system(domain_name, top_k, model_name=model_name)

    def _resolve_galileo_logger(*_args, **_kwargs):
        try:
            import streamlit as st

            return st.session_state.get(f"galileo_logger_{domain_name}") or st.session_state.get(
                "galileo_logger"
            )
        except Exception:
            return None

    @tool
    @domain_controlled_tool(step_name="retrieval_step", resolve_logger=_resolve_galileo_logger)
    async def retrieve_documents_chain(query: str, config: RunnableConfig) -> str:
        """Retrieve information related to a query from the knowledge base using LangChain retrieval chain."""
        return await rag_system.search(query, config=config)

    retrieve_documents_chain.name = f"retrieve_{domain_name}_documents"
    retrieve_documents_chain.description = (
        f"Retrieve information from the {domain_name} knowledge base"
    )

    return retrieve_documents_chain

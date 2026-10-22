"""
Cisco SE domain tools — read-only presales technical knowledge.

- search_cisco_se_specs: semantic vector search over official Cisco/H3C switch
  specification facts in the strict pgvector collection 'cisco_se_hosted_index'.
  Returns the retrieved facts and their source metadata (no inner RAG LLM), so
  the agent model is the only application LLM and citations are traceable.
"""
import json
import logging
import sys
from pathlib import Path

from langchain_core.runnables import RunnableConfig

_ROOT = Path(__file__).resolve().parents[3]
_DOMAIN_NAME = "cisco_se"

_root = str(_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)

from helpers.agent_control_helpers import domain_controlled_tool
from agent_frameworks.langgraph.langgraph_rag import get_domain_rag_system

# Set per agent by LangGraphAgent.load_tools(); retrieval spans are recorded by
# the LangChain callback through the retriever, so no manual spans are needed.
galileo_logger = None


@domain_controlled_tool(step_name="retrieval_step")
async def search_cisco_se_specs(query: str, config: RunnableConfig = None) -> str:
    """Search official Cisco/H3C data-center switch specification facts."""
    try:
        rag_system = get_domain_rag_system(_DOMAIN_NAME)
        if rag_system.mode != "documents":
            raise RuntimeError("cisco_se requires rag.mode: documents")
        result = await rag_system.search_documents(query, config=config)
    except Exception as e:
        logging.exception("search_cisco_se_specs failed")
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)
    if not result["documents"]:
        result["note"] = "No matching official fact was found in the knowledge base."
    return json.dumps(result, ensure_ascii=False)


TOOLS = [search_cisco_se_specs]

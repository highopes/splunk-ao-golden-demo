"""
Text-to-SQL helpers for domain lookup and delete tools.
"""
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from helpers.llm_utils import (
    get_chat_model,
    get_default_chat_model,
    get_llm_provider,
    get_model_runtime_options,
    message_content_to_text,
)
from sqlalchemy import create_engine

from helpers.pgvector_utils import get_postgres_connection_string
from helpers.sql_utils import get_table_schema_description, relational_table_name

SqlOperation = Literal["select", "delete"]


def _strip_sql_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned.rstrip(";")


async def generate_sql(
    *,
    domain_name: str,
    table_suffix: str,
    id_column: str,
    record_id: str,
    operation: SqlOperation = "select",
    model: str = "",
    temperature: float = 0.0,
    use_case_identifier: str = "",
    use_case_value: str = "",
    model_config: Optional[dict] = None,
) -> str:
    """
    Use an LLM to produce a SELECT or DELETE statement for a relational table.
    """
    table_name = relational_table_name(domain_name, table_suffix)
    engine = create_engine(get_postgres_connection_string())
    try:
        schema = get_table_schema_description(engine, table_name)
    finally:
        engine.dispose()

    if operation == "delete":
        system_prompt = (
            "You are a PostgreSQL expert. Generate exactly one DELETE statement "
            "to remove the requested record. Rules:\n"
            f'- Use DELETE FROM "{table_name}" with a WHERE clause on {id_column}.\n'
            "- Use only the provided table and columns.\n"
            "- Match the identifier exactly (case-sensitive).\n"
            "- Do not use JOINs, subqueries, CTEs, RETURNING, or semicolons.\n"
            "- Output only the SQL statement with no explanation."
        )
        user_prompt = (
            f"{schema}\n\n"
            f"Delete request: remove the row where {use_case_identifier} equals '{use_case_value}'."
            # f"Delete request: remove the row where {id_column} equals '{record_id}'."
        )
    else:
        system_prompt = (
            "You are a PostgreSQL expert. Generate exactly one SELECT statement "
            "to answer the user's lookup request. Rules:\n"
            "- Use only the provided table and columns.\n"
            "- Return all columns for the matching record.\n"
            "- Query does not need to use the primary key column.\n"
            "- Write the SQL statement to use uppercase: WHERE UPPER(column) = UPPER('value').\n"
            # "- Match the identifier exactly (case-sensitive).\n"
            "- Do not use JOINs, subqueries, CTEs, or semicolons.\n"
            "- Output only the SQL statement with no explanation."
        )
        user_prompt = (
            f"{schema}\n\n"
            f"Lookup request: {use_case_identifier}='{use_case_value}'\n\n"
            # f"Lookup request: find the row where {id_column} equals '{record_id}'."
        )

    resolved_model = model or get_default_chat_model()
    provider = get_llm_provider()
    # Reuse the domain's hosted settings (e.g. reasoning_effort) so the inner
    # SQL call matches the agent model's latency profile.
    runtime_options = get_model_runtime_options(model_config, resolved_model, provider)
    llm = get_chat_model(
        resolved_model, temperature=temperature, provider=provider, **runtime_options
    )
    response = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    # Responses API / Bedrock return content blocks, not a plain string.
    return _strip_sql_fences(message_content_to_text(response.content))


async def generate_lookup_sql(
    *,
    domain_name: str,
    table_suffix: str,
    id_column: str,
    lookup_id: str,
    model: str = "",
    temperature: float = 0.0,
) -> str:
    """Backward-compatible wrapper for SELECT lookups."""
    return await generate_sql(
        domain_name=domain_name,
        table_suffix=table_suffix,
        id_column=id_column,
        record_id=lookup_id,
        operation="select",
        model=model,
        temperature=temperature,
    )

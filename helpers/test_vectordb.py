"""Read-only RAG smoke query against this project's PostgreSQL/pgvector data."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain_manager import DomainManager
from setup_env import setup_environment
from helpers.pgvector_utils import get_pgvector_store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain", nargs="?", default="healthcare")
    parser.add_argument("--query", default="Lisinopril")
    args = parser.parse_args()
    cfg = DomainManager().load_domain_config(args.domain)
    setup_environment(args.domain, cfg.config)
    store, collection = get_pgvector_store(args.domain, vectorstore_config=cfg.config.get("vectorstore", {}))
    results = store.similarity_search(args.query, k=2)
    print(f"{collection}: {len(results)} documents")
    for doc in results:
        print(doc.page_content)


if __name__ == "__main__":
    main()

"""Agentic RAG — Knowledge Router + Multi-Source Retrieval."""

from solomon.rag.classifier import classify_retrieval, is_knowledge_query
from solomon.rag.crew import kickoff_knowledge_rag
from solomon.rag.models import KnowledgeRagResult, RetrievalPlan, RetrievalStrategy

__all__ = [
    "KnowledgeRagResult",
    "RetrievalPlan",
    "RetrievalStrategy",
    "classify_retrieval",
    "is_knowledge_query",
    "kickoff_knowledge_rag",
]

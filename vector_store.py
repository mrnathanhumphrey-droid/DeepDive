import os
import json
import hashlib
from datetime import datetime
import chromadb
from chromadb.config import Settings
from config import VECTOR_DB_PATH


class CorrectionStore:
    """Stores and retrieves prompt correction patterns using ChromaDB.

    Each correction record contains:
    - The topic context that triggered it
    - The agent type that was corrected
    - The original issue identified
    - The optimized corrective guidance
    - The user's feedback that led to the correction
    - Whether the correction was effective (updated after re-run)
    """

    COLLECTION_NAME = "prompt_corrections"

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=VECTOR_DB_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "DeepDive agent prompt correction patterns"},
        )

    def store_correction(self, topic: str, agent_type: str, issue: str,
                         original_guidance: str, optimized_guidance: str,
                         user_feedback: str) -> str:
        """Store a correction pattern for future retrieval.
        Returns the document ID."""
        doc_id = hashlib.sha256(
            f"{topic}:{agent_type}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        document = (
            f"Agent: {agent_type}\n"
            f"Issue: {issue}\n"
            f"User feedback: {user_feedback}\n"
            f"Corrective guidance: {optimized_guidance}"
        )

        metadata = {
            "topic": topic[:200],
            "agent_type": agent_type,
            "issue": issue[:500],
            "original_guidance": original_guidance[:500],
            "optimized_guidance": optimized_guidance[:1000],
            "user_feedback": user_feedback[:1000],
            "timestamp": datetime.now().isoformat(),
            "effective": "unknown",
        }

        self.collection.add(
            documents=[document],
            metadatas=[metadata],
            ids=[doc_id],
        )
        return doc_id

    def query_similar_corrections(self, topic: str, agent_type: str = None,
                                   n_results: int = 5) -> list[dict]:
        """Find past corrections relevant to a topic and optional agent type.
        Returns list of correction records sorted by relevance."""
        query_text = f"Topic: {topic}"
        if agent_type:
            query_text += f"\nAgent: {agent_type}"

        where_filter = None
        if agent_type:
            where_filter = {"agent_type": agent_type}

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_filter,
            )
        except Exception:
            # If filtered query fails (e.g., no matching agent_type), try without filter
            try:
                results = self.collection.query(
                    query_texts=[query_text],
                    n_results=n_results,
                )
            except Exception:
                return []

        corrections = []
        if results and results["metadatas"]:
            for i, metadata in enumerate(results["metadatas"][0]):
                correction = {
                    "id": results["ids"][0][i] if results["ids"] else None,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                    **metadata,
                }
                corrections.append(correction)

        return corrections

    def query_corrections_for_agents(self, topic: str,
                                      agent_types: list[str],
                                      n_per_agent: int = 3) -> dict[str, list[dict]]:
        """Retrieve past corrections for multiple agent types in a single query.
        Returns {agent_type: [corrections]}."""
        if not agent_types:
            return {}

        query_text = f"Topic: {topic}"

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=min(n_per_agent * len(agent_types), 50),
                where={"agent_type": {"$in": agent_types}},
            )
        except Exception:
            # Fall back to per-agent queries if $in filter not supported
            fallback = {}
            for agent_type in agent_types:
                corrections = self.query_similar_corrections(topic, agent_type, n_per_agent)
                if corrections:
                    fallback[agent_type] = corrections
            return fallback

        # Group results by agent_type
        grouped: dict[str, list[dict]] = {}
        if results and results["metadatas"]:
            for i, metadata in enumerate(results["metadatas"][0]):
                agent_type = metadata.get("agent_type", "unknown")
                if agent_type not in grouped:
                    grouped[agent_type] = []
                if len(grouped[agent_type]) < n_per_agent:
                    correction = {
                        "id": results["ids"][0][i] if results["ids"] else None,
                        "document": results["documents"][0][i] if results["documents"] else "",
                        "distance": results["distances"][0][i] if results.get("distances") else None,
                        **metadata,
                    }
                    grouped[agent_type].append(correction)

        return grouped

    def mark_effective(self, doc_id: str, effective: bool):
        """Mark whether a stored correction was effective after re-run."""
        self.collection.update(
            ids=[doc_id],
            metadatas=[{"effective": "yes" if effective else "no"}],
        )

    def get_all_corrections(self, limit: int = 100) -> list[dict]:
        """Retrieve all stored corrections for inspection."""
        try:
            results = self.collection.get(limit=limit)
        except Exception:
            return []

        corrections = []
        if results and results["metadatas"]:
            for i, metadata in enumerate(results["metadatas"]):
                correction = {
                    "id": results["ids"][i] if results["ids"] else None,
                    "document": results["documents"][i] if results["documents"] else "",
                    **metadata,
                }
                corrections.append(correction)
        return corrections

    def delete_correction(self, doc_id: str):
        """Remove a correction from the store."""
        self.collection.delete(ids=[doc_id])

    def clear_all(self):
        """Clear all stored corrections."""
        self.client.delete_collection(self.COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "DeepDive agent prompt correction patterns"},
        )

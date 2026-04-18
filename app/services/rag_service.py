"""
RAG Service — Retrieval-Augmented Generation for Medical Intake

Uses ChromaDB (in-process) with default embeddings to provide
contextually relevant medical intake guidance to the AI question generator.

Optimized: Force-reloads knowledge on startup, smaller chunks for precision.
"""

import os
import hashlib
import logging
from pathlib import Path
from typing import List, Optional

# Suppress ChromaDB telemetry completely (harmless PostHog version mismatch)
os.environ["ANONYMIZED_TELEMETRY"] = "False"
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

# Knowledge base directory
KNOWLEDGE_DIR = Path(__file__).parent.parent / "rag" / "knowledge"
CHROMA_DIR = Path(__file__).parent.parent / "rag" / "chroma_db"


class RAGService:
    """
    Retrieval-Augmented Generation service using ChromaDB.
    
    Loads medical intake documents, splits into chunks, embeds them,
    and provides context retrieval for the AI question generator.
    """

    def __init__(self):
        self._client = None
        self._collection = None
        self._initialized = False

    def _compute_knowledge_hash(self) -> str:
        """Compute a hash of all knowledge files to detect changes."""
        hasher = hashlib.md5()
        if not KNOWLEDGE_DIR.exists():
            return "empty"
        for md_file in sorted(KNOWLEDGE_DIR.glob("*.md")):
            stat = md_file.stat()
            hasher.update(f"{md_file.name}:{stat.st_size}:{stat.st_mtime}".encode())
        return hasher.hexdigest()

    async def initialize(self):
        """Initialize ChromaDB and load the knowledge base."""
        if self._initialized:
            return

        if os.getenv("DISABLE_RAG", "false").lower() == "true":
            logger.warning("⚠️ RAG Service locally disabled to save RAM. Returning fallback context.")
            self._initialized = True
            return

        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            persist_dir = str(CHROMA_DIR)
            os.makedirs(persist_dir, exist_ok=True)

            # Check if knowledge files changed
            hash_file = CHROMA_DIR / ".knowledge_hash"
            current_hash = self._compute_knowledge_hash()
            needs_reload = True

            if hash_file.exists():
                stored_hash = hash_file.read_text().strip()
                if stored_hash == current_hash:
                    needs_reload = False

            self._client = chromadb.Client(ChromaSettings(
                anonymized_telemetry=False,
                is_persistent=True,
                persist_directory=persist_dir,
            ))

            if needs_reload:
                # Delete old collection and rebuild
                try:
                    self._client.delete_collection("medical_intake")
                    logger.info("🔄 Knowledge files changed — rebuilding RAG index...")
                except Exception:
                    pass

                self._collection = self._client.create_collection(
                    name="medical_intake",
                    metadata={"description": "Medical intake knowledge base"},
                )
                await self._load_knowledge_base()

                # Save hash
                hash_file.write_text(current_hash)
                logger.info(f"📚 RAG knowledge base rebuilt: {self._collection.count()} chunks")
            else:
                self._collection = self._client.get_collection("medical_intake")
                logger.info(f"📚 RAG knowledge base ready: {self._collection.count()} chunks (cached)")

            self._initialized = True

        except ImportError:
            logger.warning("⚠️ ChromaDB not installed. RAG will return empty context.")
            self._initialized = True
        except Exception as e:
            logger.error(f"❌ Failed to initialize RAG service: {e}")
            self._initialized = True  # Don't block app startup

    async def _load_knowledge_base(self):
        """Load all markdown files from the knowledge directory."""
        if not KNOWLEDGE_DIR.exists():
            logger.warning(f"Knowledge directory not found: {KNOWLEDGE_DIR}")
            return

        documents = []
        metadatas = []
        ids = []
        chunk_id = 0

        for md_file in sorted(KNOWLEDGE_DIR.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
                file_name = md_file.stem

                # Split into smaller, precise chunks
                chunks = self._split_by_headers(content, file_name)

                for chunk_text, chunk_meta in chunks:
                    if len(chunk_text.strip()) < 40:
                        continue  # Skip very short chunks

                    documents.append(chunk_text.strip())
                    metadatas.append(chunk_meta)
                    ids.append(f"chunk_{chunk_id}")
                    chunk_id += 1

                logger.info(f"  📄 Loaded {md_file.name}: {len(chunks)} chunks")

            except Exception as e:
                logger.error(f"  ❌ Failed to load {md_file.name}: {e}")

        if documents and self._collection is not None:
            # Add in batches
            batch_size = 50
            for i in range(0, len(documents), batch_size):
                batch_docs = documents[i:i + batch_size]
                batch_metas = metadatas[i:i + batch_size]
                batch_ids = ids[i:i + batch_size]

                self._collection.add(
                    documents=batch_docs,
                    metadatas=batch_metas,
                    ids=batch_ids,
                )

            logger.info(f"  ✅ Total chunks indexed: {len(documents)}")

    def _split_by_headers(self, content: str, source: str) -> List[tuple]:
        """
        Split markdown content by ## and ### headers into precise chunks.
        Each chunk includes parent header context for better retrieval.
        """
        chunks = []
        current_h1 = ""
        current_h2 = ""
        current_h3 = ""
        current_text_lines = []

        def _flush_chunk():
            if current_text_lines:
                text = "\n".join(current_text_lines)
                if len(text.strip()) > 30:
                    section = current_h3 or current_h2 or current_h1
                    context = f"[{source}] {current_h1}"
                    if current_h2:
                        context += f" > {current_h2}"
                    if current_h3:
                        context += f" > {current_h3}"
                    chunks.append((
                        f"{context}\n{text}",
                        {"source": source, "section": section, "h1": current_h1, "h2": current_h2},
                    ))

        for line in content.split("\n"):
            if line.startswith("# ") and not line.startswith("## "):
                _flush_chunk()
                current_text_lines = []
                current_h1 = line.lstrip("# ").strip()
                current_h2 = ""
                current_h3 = ""

            elif line.startswith("## "):
                _flush_chunk()
                current_text_lines = []
                current_h2 = line.lstrip("# ").strip()
                current_h3 = ""

            elif line.startswith("### "):
                _flush_chunk()
                current_text_lines = []
                current_h3 = line.lstrip("# ").strip()

            else:
                current_text_lines.append(line)

        # Flush final chunk
        _flush_chunk()
        return chunks

    async def retrieve_context(
        self,
        query: str,
        top_k: int = 3,
        source_filter: Optional[str] = None,
    ) -> str:
        """
        Retrieve relevant medical intake context for a symptom query.
        """
        if not self._collection or self._collection.count() == 0:
            return self._get_fallback_context()

        try:
            where_filter = None
            if source_filter:
                where_filter = {"source": source_filter}

            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, self._collection.count()),
                where=where_filter,
            )

            if results and results["documents"] and results["documents"][0]:
                contexts = results["documents"][0]
                return "\n\n---\n\n".join(contexts)

        except Exception as e:
            logger.error(f"RAG retrieval error: {e}")

        return self._get_fallback_context()

    def _get_fallback_context(self) -> str:
        """Minimal fallback context if RAG is unavailable."""
        return """Medical intake best practices:
- Ask about symptom location, duration, severity, and character
- Check for associated symptoms
- Ask about aggravating and relieving factors
- Inquire about medical history and current medications
- Use simple, clear language appropriate for the patient
- Never provide diagnosis or medical advice
- Flag any red flag symptoms (chest pain, difficulty breathing, sudden neurological changes)"""

    async def add_document(self, text: str, metadata: dict) -> bool:
        """Add a new document to the knowledge base."""
        if not self._collection:
            logger.error("RAG collection not initialized")
            return False

        try:
            chunk_id = f"custom_{self._collection.count()}"
            self._collection.add(
                documents=[text],
                metadatas=[metadata],
                ids=[chunk_id],
            )
            logger.info(f"Added document to RAG: {metadata.get('source', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"Failed to add document to RAG: {e}")
            return False

    @property
    def is_ready(self) -> bool:
        return self._initialized and self._collection is not None

    @property
    def chunk_count(self) -> int:
        if self._collection:
            return self._collection.count()
        return 0


# Singleton instance
rag_service = RAGService()

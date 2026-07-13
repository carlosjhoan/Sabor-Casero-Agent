import logging
from typing import List, Dict, Optional
from sentence_transformers import SentenceTransformer, CrossEncoder
import chromadb
from src.core.knowledge.registry import DocumentRegistry
from src.utils.utils import split_text
from src.core.classifier.intent import Detail
from src.core.extractor.retriever_interface import RetrieverInterface
from src.config.environment import settings

# Initialize logger
logger = logging.getLogger("HybridRetriever")

class HybridRetriever(RetrieverInterface):
    def __init__(self):
        # 1. Links to your existing Registry
        self.registry = DocumentRegistry()
        
        # 2. Embedding Model (Local & Fast)
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        
        # 3. Reranker (The 'Brain' for precision)
        self.reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        
        # 4. Vector Database (In-memory for development)
        self.storage = settings.vector_db_path
        self.chroma_client = chromadb.PersistentClient(path=self.storage)
        self.collection = self.chroma_client.get_or_create_collection("sabor_casero")
        
        # 5. Intelligent Splitter (inline, sin langchain_text_splitters)
        self.chunk_size = 400
        self.chunk_overlap = 40

    def _ingest_single_document(self, doc_name: str, content: str):
        """
        Safely processes a document: chunks it, embeds it, and stores it in ChromaDB.
        """
        try:
            # 1. Validation: Ensure content isn't empty
            existing = self.collection.get(
                where={"source": doc_name},
                limit=1
            )

            if len(existing['ids']) > 0:
                logger.info(f"skipping {doc_name}: Already exists in Vector DB.")
                return
            
            if not content.strip():
                logger.warning(f"⚠️ Skipping {doc_name}: Document is empty.")
                
                print("\n", 30*" - x - ")
                print(f"⚠️ Skipping {doc_name}: Document is empty.")
                print(" ", 30*" - x - ", "\n")
                return

            logger.info(f"🚀 Starting ingestion for: {doc_name}")

            print("\n", 30*" - = - ")
            print(f"🚀 Starting ingestion for: {doc_name}")
            print(" ", 30*" - = - ", "\n")

            # 2. Chunking
            chunks = split_text(content, self.chunk_size, self.chunk_overlap)
            if not chunks:
                logger.warning(f"⚠️ No chunks generated for {doc_name}. Check splitter settings.")

                print("\n", 30*" - x - ")
                print(f"⚠️ No chunks generated for {doc_name}. Check splitter settings.")
                print(" ", 30*" - x - ", "\n")
                return

            # 3. Embedding Generation
            # We wrap this in a sub-try because model inference can fail (e.g., out of memory)
            try:
                embeddings = self.embedder.encode(chunks).tolist()
            except Exception as e:
                logger.error(f"❌ Embedding failed for {doc_name}: {str(e)}")

                print("\n", 30*" - x - ")
                print(f"❌ Embedding failed for {doc_name}: {str(e)}")
                print(" ", 30*" - x - ", "\n")
                return

            # 4. Prepare Metadata and IDs
            ids = [f"{doc_name}_{i}" for i in range(len(chunks))]
            metadatas = [{"source": doc_name, "chunk_index": i} for i in range(len(chunks))]

            # 5. Save to ChromaDB
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=chunks
            )
            
            logger.info(f"✅ Successfully ingested {len(chunks)} chunks from {doc_name}.")

            print("\n", 30*" :: ")
            print(f"✅ Successfully ingested {len(chunks)} chunks from {doc_name}.")
            print(" ", 30*" - = - ", "\n")

        except chromadb.errors.ChromaError as ce:
            # Catch specific Vector DB errors (e.g., duplicate IDs, connection issues)
            logger.error(f"❌ ChromaDB Error while ingesting {doc_name}: {str(ce)}")
            print("\n", 30*" - x - ")
            print(f"❌ ChromaDB Error while ingesting {doc_name}: {str(ce)}")
            print(" ", 30*" - x - ", "\n")
            
        except Exception as e:
            # Catch any other unexpected errors (File I/O, memory, etc.)
            logger.error(f"🔥 Unexpected critical error ingesting {doc_name}: {str(e)}", exc_info=True)
            print("\n", 30*" - x - ")
            print(f"🔥 Unexpected critical error ingesting {doc_name}: {str(e)}")
            print(" ", 30*" - x - ", "\n")

    def _load_document_content(self, doc_name: str, folder: str) -> str:
        """Loads document content from storage"""
        with open(f"{folder}/{doc_name}", "r", encoding="utf-8") as f:
            return f.read()

    async def get_context(self, query: str, doc_name: str) -> str:
        """The main retrieval logic — public async interface."""
        # STEP 1: Route using your Registry
        target_file = doc_name
        if target_file == 'no-file':
            return ""

        # STEP 2: Vector Search (filtered by document source)
        query_vector = self.embedder.encode(query).tolist()
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=10,
            where={"source": target_file} # <--- Production optimization
        )

        print("\n", 30*" ~~~ ")
        print(f"Retrieved results for query '{query}' from document '{doc_name}'")
        print("Results:", results['documents'][0] if results['documents'][0] else "No results found")
        print(f"Distances: {results['distances'] if results['distances'] else 'N/A'}")
        print(" ", 30*" ~~~ ", "\n")
        
        candidate_chunks = results['documents'][0]
        if not candidate_chunks:
            return ""

        # STEP 3: Reranking (Cross-Encoder)
        # We pair the query with each chunk: [[query, chunk1], [query, chunk2]...]
        pairs = [[query, chunk] for chunk in candidate_chunks]
        scores = self.reranker.predict(pairs)

        print("\n", 30*" >>> ")
        print(f"Reranking scores for query '{query}': {scores}")
        print(" ", 30*" >>> ", "\n")


        # print("\n", 30*" >>> ")
        # print(f"Reranked chunks for query '{query}':")
        # for score, chunk in zip(scores, candidate_chunks):
        #     print(f"Score: {score:.4f} | Chunk: {chunk}")
        # print(" ", 30*" >>> ", "\n")
        
        # Sort chunks by score (highest first)
        scored_chunks = sorted(zip(scores, candidate_chunks), key=lambda x: x[0], reverse=True)
        
        # Pick the top 3 chunks
        top_3 = [chunk for score, chunk in scored_chunks[:3]]
        
        return "\n---\n".join(top_3)
    
    async def retrieve_dense(
        self,
        query: str,
        candidates: List[str],
        source: str = "",
    ) -> Dict[str, float]:
        """Vector similarity scores for the dense signal in RAG v2 pipeline.

        Queries ChromaDB for chunks relevant to *query*, then scores each
        candidate by the best similarity of any chunk that mentions it.

        Args:
            query: The user's search query.
            candidates: List of candidate item names to score.
            source: Optional source document name to filter by. When provided,
                adds ``where={"source": source}`` to the ChromaDB query.

        Returns:
            Dict mapping candidate name → similarity score (0.0–1.0).
            Candidates not mentioned in any chunk get score 0.0.
        """
        if not query or not candidates:
            return {c: 0.0 for c in candidates}

        query_vector = self.embedder.encode(query).tolist()
        query_kwargs: dict = {
            "query_embeddings": [query_vector],
            "n_results": 20,
        }
        if source:
            query_kwargs["where"] = {"source": source}
        results = self.collection.query(**query_kwargs)

        scores = {c: 0.0 for c in candidates}
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not documents or not distances:
            return scores

        for chunk, dist in zip(documents, distances):
            # Convert cosine distance to similarity (0.0–1.0)
            similarity = max(0.0, 1.0 - (dist / 2.0))
            chunk_lower = chunk.lower()
            for candidate in candidates:
                if candidate.lower() in chunk_lower:
                    scores[candidate] = max(scores[candidate], similarity)

        return scores

    def ingest_all_documents(self, folder_save_docs: str):
        """Ingest multiple documents given their names and a loading function"""
        print("\n", 30*" - = - ")
        print("📥 Ingesting all documents into Vector DB...")
        print(" ", 30*" - = - ", "\n")


        for doc_name in self.registry.list_all_documents():
    
            content = self._load_document_content(doc_name, folder_save_docs)
            self._ingest_single_document(doc_name, content)
        

        print("\n", 30*" - = - ")
        print("✅ Ingestion complete!")
        print(" ", 30*" - = - ", "\n")

    async def retrieve(self, group_by_doc: Dict[str, List[Detail]]) -> list[Detail]:
        """
        Retrieve relevant documents based on the query

        Args:
            group_by_doc (Dict[str, List[Detail]]): The grouped topic details to retrieve information for

        Returns:
            List[Detail]: List of updated topic details with retrieved information
        """
        for doc_name, details in group_by_doc.items():
            for detail in details:
                try:
                    query = detail.segment
                    extracted_info = await self.get_context(query, doc_name)
                    detail.info_extracted = extracted_info

                except Exception as e:
                    logger.error(f"Error retrieving information for query '{query}' from '{doc_name}': {e}")
                    detail.info_extracted = "Ha ocurrido un error al recuperar la información."
                
        return [detail for details in group_by_doc.values() for detail in details]

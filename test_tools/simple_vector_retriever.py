# Add to your existing system
import chromadb
from sentence_transformers import SentenceTransformer

class SimpleVectorRetriever:
    def __init__(self):
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self.client = chromadb.Client()
        self.collection = self.client.get_or_create_collection(name="docs")

        
    def add_document(self, doc_name: str):
        # Simple chunking
        content = self._load_document(doc_name)
        print (f"Adding document {doc_name} to vector store.")
        print(f"A fragment of the content: {content[:200]}...\n")
        chunks = content.split("\n\n")
        
        print(f"Document split into {len(chunks)} chunks.")
        for i, chunk in enumerate(chunks):
            embedding = self.embedder.encode(chunk)
            print(f"A fragment of the embedding: {embedding[:5]}...\n")
            self.collection.add(
                ids=f"{doc_name}_{i}",
                embeddings=[embedding.tolist()],
                documents=[chunk],
                metadatas=[{"document": doc_name}]
            )
            print(f"Added chunk {i+1}/{len(chunks)}")
    
    def retrieve(self, query: str, doc_name: str = None):
        query_embedding = self.embedder.encode(query)
        
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=3,
            where={"document": doc_name} if doc_name else None
        )
        
        return results['documents'][0]
    
    def _load_document(self, doc_name: str) -> str:
        # Placeholder for document loading logic
        with open(f"data/documents/{doc_name}", "r", encoding="utf-8") as f:
            return f.read()
        
def main():
    doc_name = "menu.md"
    retriever = SimpleVectorRetriever()
    retriever.add_document(doc_name=doc_name)
    
    query = "De principio qué tienen?"
    results = retriever.retrieve(query, doc_name=doc_name)
    
    for res in results:
        print(res)

if __name__ == "__main__":
    main()
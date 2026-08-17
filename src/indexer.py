import os
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Import Pydantic models
from src.schemas import QuestionModel

# Load config
load_dotenv("config.env")

def get_embeddings():
    """
    Instantiate appropriate embeddings model based on provider config.
    """
    # Allow overriding embedding provider independently, or fallback to LLM provider
    provider = os.getenv("EMBEDDING_PROVIDER") or os.getenv("LLM_PROVIDER", "gemini")
    provider = provider.lower()
    
    # Gradio only hosts text generation; fall back to local HuggingFace embeddings
    if provider == "gradio":
        provider = "local_api"
        
    if provider == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY must be set in config.env for Gemini provider.")
        return GoogleGenerativeAIEmbeddings(
            model=os.getenv("GEMINI_EMBEDDING_MODEL", "models/embedding-001"),
            google_api_key=api_key
        )
    elif provider == "ollama":
        from langchain_ollama import OllamaEmbeddings
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        # nomic-embed-text is standard, or use llama3 if pulled
        model_name = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        return OllamaEmbeddings(
            model=model_name,
            base_url=base_url
        )
    elif provider == "local_api":
        # Runs a lightweight embeddings model 100% locally inside Python
        from langchain_community.embeddings import HuggingFaceEmbeddings
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_name = os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        return HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device}
        )
    else:
        raise ValueError(f"Unknown LLM provider for embeddings: {provider}")

class QuestionIndexer:
    def __init__(self, persist_directory: str = "db/chromadb"):
        import chromadb
        self.persist_directory = persist_directory
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.embeddings = get_embeddings()
        
        # Get or create collection with cosine space configuration
        self.collection = self.client.get_or_create_collection(
            name="question_bank",
            metadata={"hnsw:space": "cosine"}
        )

    def is_duplicate_id(self, question_id: str) -> bool:
        """
        Check if the unique SHA-256 ID already exists in the vector store.
        """
        results = self.collection.get(ids=[question_id])
        return len(results["ids"]) > 0

    def check_semantic_duplicate(self, statement: str, similarity_threshold: float = 0.95) -> Optional[dict]:
        """
        Query ChromaDB for the closest semantic match to the statement.
        Returns a dict containing the closest match metadata and distance if similarity exceeds threshold.
        For Cosine distance, distance = 1 - similarity.
        So threshold similarity 0.95 means cosine distance <= 0.05.
        """
        # Embed the query statement
        query_vector = self.embeddings.embed_query(statement)
        
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=1
        )
        
        if results and results["ids"] and results["ids"][0]:
            distance = results["distances"][0][0]
            similarity = 1.0 - distance
            
            if similarity >= similarity_threshold:
                return {
                    "id": results["ids"][0][0],
                    "metadata": results["metadatas"][0][0],
                    "similarity": similarity
                }
        return None

    def add_question(self, question: QuestionModel, similarity_threshold: float = 0.95) -> str:
        """
        Indexes a question to ChromaDB. Checks both ID duplicates and semantic vector duplicates.
        Returns status message: 'indexed', 'skipped_id', or 'skipped_semantic'.
        """
        # 1. Check ID duplicate
        if self.is_duplicate_id(question.id):
            return "skipped_id"
            
        # 2. Check Semantic duplicate
        duplicate_info = self.check_semantic_duplicate(question.statement, similarity_threshold)
        if duplicate_info:
            print(f"[Warning] Question skipped due to high semantic similarity ({duplicate_info['similarity']:.2f}) "
                  f"with existing question ID: {duplicate_info['id']}")
            return "skipped_semantic"
            
        # 3. Insert to collection
        # Options dictionary is serialized as a JSON string to fit in flat metadata
        options_str = json.dumps(question.options) if question.options else ""
        
        metadata = {
            "level": question.level.value,
            "topic": question.topic.value,
            "type": question.type.value,
            "difficulty": question.difficulty.value,
            "correct_answer": question.correct_answer,
            "explanation": question.explanation or "",
            "source_file": question.source_file,
            "options_json": options_str
        }
        
        # Embed statement
        vector = self.embeddings.embed_query(question.statement)
        
        self.collection.add(
            ids=[question.id],
            embeddings=[vector],
            documents=[question.statement],
            metadatas=[metadata]
        )
        
        return "indexed"

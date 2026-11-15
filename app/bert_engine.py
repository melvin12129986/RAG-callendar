import os
import hashlib
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
import logging

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
logger = logging.getLogger(__name__)

class BertEmbeddingEngine:
    """
    BERT Embedding Layer with forward pass extraction and semantic hashing.
    Runs raw token inputs through BERT's Transformer layers to generate dense vectors
    and semantic hash signatures for indexing and cosine similarity retrieval.
    """
    def __init__(self, model_name: str = "prajjwal1/bert-tiny"):
        self.model_name = model_name
        self.tokenizer = None
        self.model = None
        self._is_ready = False
        self._load_model()

    def _load_model(self):
        try:
            from transformers import AutoTokenizer, AutoModel, BertTokenizer, BertModel
            import torch
            
            logger.info(f"Loading BERT model and tokenizer: {self.model_name}")
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            except Exception:
                self.tokenizer = BertTokenizer.from_pretrained(self.model_name)

            try:
                self.model = AutoModel.from_pretrained(self.model_name)
            except Exception:
                self.model = BertModel.from_pretrained(self.model_name)

            self.model.eval()  # Inference mode
            self._is_ready = True
            logger.info("BERT model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load transformers BERT model: {e}")
            self._is_ready = False

    def forward_pass(self, text: str) -> np.ndarray:
        """
        Executes a PyTorch forward pass through the BERT embedding and transformer layers.
        Returns a mean-pooled 1D numpy vector representing the semantic text embedding.
        """
        if not self._is_ready:
            # Fallback deterministic pseudo-embedding if model not loaded yet
            return self._fallback_pseudo_embedding(text)

        import torch
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=128,
            padding=True
        )

        with torch.no_grad():
            outputs = self.model(**inputs)
            # outputs.last_hidden_state shape: [batch_size, sequence_length, hidden_dimension]
            last_hidden_state = outputs.last_hidden_state
            
            # Mean pooling taking attention mask into account
            attention_mask = inputs["attention_mask"].unsqueeze(-1).expand(last_hidden_state.size()).float()
            sum_embeddings = torch.sum(last_hidden_state * attention_mask, dim=1)
            sum_mask = torch.clamp(attention_mask.sum(dim=1), min=1e-9)
            mean_pooled = sum_embeddings / sum_mask
            
            # Normalize vector for optimal cosine similarity
            norm = torch.norm(mean_pooled, p=2, dim=1, keepdim=True)
            normalized_vec = (mean_pooled / torch.clamp(norm, min=1e-9)).squeeze(0).cpu().numpy()
            
            return normalized_vec

    def compute_semantic_hash(self, vector: np.ndarray, num_bits: int = 64) -> str:
        """
        Generates a compact hash representation of the BERT forward-pass vector
        using sign-bit quantization / SimHash fingerprinting and hex encoding.
        """
        # Locality-sensitive sign hashing: convert vector dimensions into binary string
        # Sample dimensions evenly if dimension > num_bits or project
        sample_indices = np.linspace(0, len(vector) - 1, num_bits, dtype=int)
        sampled = vector[sample_indices]
        bitstring = "".join(["1" if val > 0 else "0" for val in sampled])
        
        # Hex representation
        hex_val = hex(int(bitstring, 2))[2:].zfill(num_bits // 4)
        return hex_val

    def _fallback_pseudo_embedding(self, text: str, dim: int = 128) -> np.ndarray:
        """Fallback deterministic embedding in case BERT model is not yet loaded."""
        np.random.seed(int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16))
        vec = np.random.randn(dim).astype(np.float32)
        norm = np.linalg.norm(vec)
        return vec / (norm if norm > 0 else 1.0)


class BertHashedCalendarTable:
    """
    Hashed Table with BERT embedding layer storage and Cosine Similarity retrieval.
    Stores calendar events keyed by event ID with their forward pass BERT vector,
    hash fingerprint, and metadata.
    """
    def __init__(self, bert_engine: BertEmbeddingEngine):
        self.bert_engine = bert_engine
        # Key: event_id -> Record: {event: dict, vector: np.ndarray, hash: str, text: str}
        self.table: Dict[str, Dict[str, Any]] = {}

    def format_event_for_embedding(self, event: Dict[str, Any]) -> str:
        """
        Constructs a rich text string combining event metadata to feed into BERT forward pass.
        """
        summary = event.get("summary", "Untitled Event")
        description = event.get("description", "")
        location = event.get("location", "")
        priority = event.get("priority", "medium")
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date") or ""
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date") or ""
        
        parts = [f"Event: {summary}"]
        if priority:
            parts.append(f"Priority: {priority}")
        if description:
            parts.append(f"Description: {description}")
        if location:
            parts.append(f"Location: {location}")
        if start:
            parts.append(f"Scheduled at: {start} to {end}")
            
        return " | ".join(parts)

    def insert_or_update(self, event: Dict[str, Any], user_id: str = "guest") -> Dict[str, Any]:
        """
        Performs BERT forward pass on the event representation, generates hash,
        and stores in the hashed table with user_id scoping.
        """
        event_id = event["id"]
        # Ensure user_id is in event
        if "user_id" not in event or not event.get("user_id"):
            event["user_id"] = user_id
        actual_user_id = event.get("user_id", user_id)
        raw_text = self.format_event_for_embedding(event)
        
        # Forward pass through BERT
        vector = self.bert_engine.forward_pass(raw_text)
        semantic_hash = self.bert_engine.compute_semantic_hash(vector)
        
        record = {
            "id": event_id,
            "user_id": actual_user_id,
            "event": event,
            "raw_text": raw_text,
            "vector": vector,
            "vector_preview": [round(float(v), 4) for v in vector[:8]], # preview first 8 dimensions
            "dimension": int(vector.shape[0]),
            "semantic_hash": semantic_hash
        }
        self.table[event_id] = record
        return record

    def remove(self, event_id: str, user_id: Optional[str] = None) -> bool:
        if event_id in self.table:
            if user_id and self.table[event_id].get("user_id") != user_id:
                return False
            del self.table[event_id]
            return True
        return False

    def get_all_records(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns records filtered by user_id without the raw full numpy array for JSON serialization."""
        results = []
        for rec in self.table.values():
            if user_id and rec.get("user_id") and rec.get("user_id") != user_id:
                continue
            results.append({
                "id": rec["id"],
                "user_id": rec.get("user_id", "guest"),
                "summary": rec["event"].get("summary", "Untitled"),
                "start": rec["event"].get("start", {}),
                "end": rec["event"].get("end", {}),
                "location": rec["event"].get("location", ""),
                "description": rec["event"].get("description", ""),
                "raw_text": rec["raw_text"],
                "semantic_hash": rec["semantic_hash"],
                "dimension": rec["dimension"],
                "vector_preview": rec["vector_preview"]
            })
        return results

    def query_similarity(self, query: str, user_id: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Performs BERT forward pass on the user query, then computes Cosine Similarity
        against all indexed events in the hashed table for this user.
        Cosine similarity: (A . B) / (||A|| * ||B||)
        """
        if not self.table:
            return []

        query_vec = self.bert_engine.forward_pass(query)
        query_norm = np.linalg.norm(query_vec)
        query_hash = self.bert_engine.compute_semantic_hash(query_vec)
        
        scores = []
        for event_id, rec in self.table.items():
            if user_id and rec.get("user_id") and rec.get("user_id") != user_id:
                continue
            doc_vec = rec["vector"]
            doc_norm = np.linalg.norm(doc_vec)
            
            if query_norm > 0 and doc_norm > 0:
                cosine_sim = float(np.dot(query_vec, doc_vec) / (query_norm * doc_norm))
            else:
                cosine_sim = 0.0

            scores.append({
                "id": event_id,
                "user_id": rec.get("user_id", "guest"),
                "summary": rec["event"].get("summary", "Untitled"),
                "event": rec["event"],
                "raw_text": rec["raw_text"],
                "semantic_hash": rec["semantic_hash"],
                "similarity_score": round(cosine_sim, 4),
                "vector_preview": rec["vector_preview"],
                "query_hash": query_hash
            })

        # Sort descending by cosine similarity score
        scores.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scores[:top_k]

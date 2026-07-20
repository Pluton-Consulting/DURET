from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID


class DocumentChunk(BaseModel):
    id: UUID
    content: str
    source_type: str
    source_id: str
    source_filename: Optional[str] = None
    chunk_index: int
    chunk_total: int
    similarity: float  # Score 0.0 à 1.0


class SearchRequest(BaseModel):
    query_text: str
    source_types: Optional[List[str]] = None
    top_k: int = 5
    similarity_threshold: float = 0.3


class SearchResult(BaseModel):
    chunks: List[DocumentChunk]
    total_found: int
    search_method: str  # 'vector', 'hybrid', 'fulltext'


class InsertDocumentRequest(BaseModel):
    content: str
    source_type: str
    source_id: str
    access_level: str = "all"
    source_filename: Optional[str] = None
    chunk_index: int = 0
    chunk_total: int = 1
    contains_pii: bool = False
    is_anonymized: bool = False

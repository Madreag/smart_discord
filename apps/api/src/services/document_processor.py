"""
Document Ingestion Service - Multimodal Content Processing

Handles PDF, TXT, MD, and Image files uploaded to Discord.
CRITICAL: File I/O happens HERE in the API worker, NEVER in the Bot process.

Pipeline:
1. Bot detects attachment → pushes URL/metadata to Redis
2. Celery worker calls this service to download and process
3. Content is chunked and embedded to Qdrant with source_type tagging
"""

import os
import io
import re
import tempfile
from typing import Optional
from dataclasses import dataclass
from enum import Enum
from uuid import uuid4

import httpx


class SourceType(str, Enum):
    """Document source types for Qdrant filtering."""
    CHAT = "chat"
    DOCUMENT = "document"
    IMAGE = "image"
    PDF = "pdf"
    TEXT = "text"
    MARKDOWN = "markdown"


class ProcessingStatus(str, Enum):
    """Attachment processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Whitelisted extensions (security)
ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Blocked extensions (executables)
BLOCKED_EXTENSIONS = {".exe", ".bat", ".sh", ".ps1", ".dll", ".so", ".bin"}

# Max file size (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


@dataclass
class AttachmentPayload:
    """Payload for attachment processing (from Redis queue)."""
    attachment_id: int
    message_id: int
    guild_id: int
    channel_id: int
    url: str
    proxy_url: Optional[str]
    filename: str
    content_type: Optional[str]
    size_bytes: int


@dataclass
class DocumentChunk:
    """A chunk of processed document content."""
    text: str
    chunk_index: int
    chunk_type: str  # 'text', 'header', 'paragraph', 'image_caption'
    heading_context: Optional[str] = None
    metadata: Optional[dict] = None


@dataclass
class ProcessingResult:
    """Result of document processing."""
    success: bool
    source_type: SourceType
    extracted_text: Optional[str] = None
    description: Optional[str] = None  # For images
    chunks: list[DocumentChunk] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.chunks is None:
            self.chunks = []


class DocumentProcessor:
    """
    Multimodal document processor.
    
    Routes files to appropriate parsers based on MIME type.
    """
    
    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client
    
    def validate_attachment(self, payload: AttachmentPayload) -> tuple[bool, Optional[str]]:
        """
        Validate attachment before processing.
        
        Returns:
            (is_valid, error_message)
        """
        # Check file size
        if payload.size_bytes > MAX_FILE_SIZE:
            return False, f"File too large: {payload.size_bytes} bytes (max: {MAX_FILE_SIZE})"
        
        # Check extension
        ext = os.path.splitext(payload.filename.lower())[1]
        
        if ext in BLOCKED_EXTENSIONS:
            return False, f"Blocked file type: {ext}"
        
        if ext not in ALLOWED_EXTENSIONS:
            return False, f"Unsupported file type: {ext}"
        
        return True, None
    
    def detect_source_type(self, payload: AttachmentPayload) -> SourceType:
        """Detect source type from filename/content_type."""
        ext = os.path.splitext(payload.filename.lower())[1]
        content_type = (payload.content_type or "").lower()
        
        if ext == ".pdf" or "pdf" in content_type:
            return SourceType.PDF
        elif ext == ".md" or "markdown" in content_type:
            return SourceType.MARKDOWN
        elif ext == ".txt" or "text/plain" in content_type:
            return SourceType.TEXT
        elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"} or "image/" in content_type:
            return SourceType.IMAGE
        
        return SourceType.DOCUMENT
    
    async def download_file(self, url: str) -> bytes:
        """
        Download file from Discord CDN.
        
        CRITICAL: This runs in API worker, not Bot process.
        """
        client = await self.get_client()
        response = await client.get(url)
        response.raise_for_status()
        return response.content
    
    async def process_attachment(self, payload: AttachmentPayload) -> ProcessingResult:
        """
        Process an attachment based on its type.
        
        Routes to appropriate parser:
        - PDF → extract_pdf_text
        - TXT/MD → extract_text_file
        - Image → describe_image (Vision LLM)
        """
        # Validate first
        is_valid, error = self.validate_attachment(payload)
        if not is_valid:
            return ProcessingResult(
                success=False,
                source_type=SourceType.DOCUMENT,
                error=error,
            )
        
        source_type = self.detect_source_type(payload)
        
        try:
            # Download file
            file_content = await self.download_file(payload.url)
            
            # Route to appropriate processor
            if source_type == SourceType.PDF:
                return await self._process_pdf(file_content, payload)
            elif source_type == SourceType.MARKDOWN:
                return await self._process_markdown(file_content, payload)
            elif source_type == SourceType.TEXT:
                return await self._process_text(file_content, payload)
            elif source_type == SourceType.IMAGE:
                return await self._process_image(payload)
            else:
                return ProcessingResult(
                    success=False,
                    source_type=source_type,
                    error=f"No processor for type: {source_type}",
                )
                
        except Exception as e:
            return ProcessingResult(
                success=False,
                source_type=source_type,
                error=str(e),
            )
    
    async def _process_pdf(self, content: bytes, payload: AttachmentPayload) -> ProcessingResult:
        """
        Extract text from PDF using pypdf.
        
        If PDF has no text layer (scanned), routes to Vision LLM for OCR.
        """
        try:
            from pypdf import PdfReader
            
            reader = PdfReader(io.BytesIO(content))
            
            full_text = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    full_text.append(text)
            
            extracted = "\n\n".join(full_text)
            
            # If no text extracted, it might be a scanned PDF
            if not extracted.strip():
                # Route to Vision LLM for OCR
                return await self._process_scanned_pdf(payload)
            
            # Chunk the text
            chunks = self._recursive_chunk(extracted, payload.filename)
            
            return ProcessingResult(
                success=True,
                source_type=SourceType.PDF,
                extracted_text=extracted,
                chunks=chunks,
            )
            
        except ImportError:
            return ProcessingResult(
                success=False,
                source_type=SourceType.PDF,
                error="pypdf not installed. Run: pip install pypdf",
            )
        except Exception as e:
            return ProcessingResult(
                success=False,
                source_type=SourceType.PDF,
                error=f"PDF processing failed: {e}",
            )
    
    async def _process_scanned_pdf(self, payload: AttachmentPayload) -> ProcessingResult:
        """Handle scanned PDFs by routing to Vision LLM."""
        # For now, return error - Vision OCR can be added later
        return ProcessingResult(
            success=False,
            source_type=SourceType.PDF,
            error="Scanned PDF detected (no text layer). OCR not yet implemented.",
        )
    
    async def _process_markdown(self, content: bytes, payload: AttachmentPayload) -> ProcessingResult:
        """Process Markdown files with semantic chunking."""
        try:
            text = content.decode("utf-8")
            chunks = self._semantic_chunk_markdown(text, payload.filename)
            
            return ProcessingResult(
                success=True,
                source_type=SourceType.MARKDOWN,
                extracted_text=text,
                chunks=chunks,
            )
        except Exception as e:
            return ProcessingResult(
                success=False,
                source_type=SourceType.MARKDOWN,
                error=f"Markdown processing failed: {e}",
            )
    
    async def _process_text(self, content: bytes, payload: AttachmentPayload) -> ProcessingResult:
        """Process plain text files."""
        try:
            # Try UTF-8 first, fall back to latin-1
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
            
            chunks = self._recursive_chunk(text, payload.filename)
            
            return ProcessingResult(
                success=True,
                source_type=SourceType.TEXT,
                extracted_text=text,
                chunks=chunks,
            )
        except Exception as e:
            return ProcessingResult(
                success=False,
                source_type=SourceType.TEXT,
                error=f"Text processing failed: {e}",
            )
    
    async def _process_image(self, payload: AttachmentPayload) -> ProcessingResult:
        """
        Process images using Vision LLM for captioning.
        
        We embed the description, not the image pixels.
        """
        try:
            description = await self._describe_image_with_vision(payload.url)
            
            if not description:
                return ProcessingResult(
                    success=False,
                    source_type=SourceType.IMAGE,
                    error="Vision LLM returned empty description",
                )
            
            # Single chunk for image description
            chunks = [DocumentChunk(
                text=description,
                chunk_index=0,
                chunk_type="image_caption",
                heading_context=f"Image: {payload.filename}",
            )]
            
            return ProcessingResult(
                success=True,
                source_type=SourceType.IMAGE,
                description=description,
                chunks=chunks,
            )
            
        except Exception as e:
            return ProcessingResult(
                success=False,
                source_type=SourceType.IMAGE,
                error=f"Image processing failed: {e}",
            )
    
    async def _describe_image_with_vision(self, image_url: str) -> str:
        """
        Use Vision LLM to generate image description.
        
        Returns dense text description suitable for embedding.
        """
        try:
            from apps.api.src.core.config import get_settings
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage
            
            settings = get_settings()
            
            if not settings.openai_api_key:
                raise ValueError("OpenAI API key not configured for Vision")
            
            # Use GPT-4o for vision
            llm = ChatOpenAI(
                model="gpt-4o",
                api_key=settings.openai_api_key,
                max_tokens=500,
            )
            
            message = HumanMessage(
                content=[
                    {"type": "text", "text": "Describe this image in detail. Include: main subjects, actions, text visible, colors, and any important context. Be thorough but concise."},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            )
            
            response = await llm.ainvoke([message])
            return response.content.strip()
            
        except ImportError:
            raise ValueError("langchain-openai not installed")
    
    def _recursive_chunk(
        self,
        text: str,
        filename: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> list[DocumentChunk]:
        """
        Recursive character text splitting.
        
        Splits on paragraph boundaries, then sentences, then characters.
        """
        if not text.strip():
            return []
        
        # Clean text
        text = text.strip()
        
        # Split on double newlines (paragraphs) first
        paragraphs = re.split(r"\n\n+", text)
        
        chunks = []
        current_chunk = ""
        chunk_index = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # If adding this paragraph exceeds chunk size
            if len(current_chunk) + len(para) + 2 > chunk_size:
                if current_chunk:
                    chunks.append(DocumentChunk(
                        text=current_chunk.strip(),
                        chunk_index=chunk_index,
                        chunk_type="paragraph",
                        heading_context=f"From: {filename}",
                    ))
                    chunk_index += 1
                    
                    # Keep overlap
                    overlap_text = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else ""
                    current_chunk = overlap_text + " " + para
                else:
                    current_chunk = para
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
        
        # Add final chunk
        if current_chunk.strip():
            chunks.append(DocumentChunk(
                text=current_chunk.strip(),
                chunk_index=chunk_index,
                chunk_type="paragraph",
                heading_context=f"From: {filename}",
            ))
        
        return chunks
    
    def _semantic_chunk_markdown(self, text: str, filename: str) -> list[DocumentChunk]:
        """
        Semantic chunking for Markdown based on headers.
        
        Preserves document structure and heading context.
        """
        chunks = []
        
        # Split by headers (## or #)
        header_pattern = r"^(#{1,6})\s+(.+)$"
        lines = text.split("\n")
        
        current_heading = ""
        current_content = []
        chunk_index = 0
        
        for line in lines:
            header_match = re.match(header_pattern, line)
            
            if header_match:
                # Save previous chunk
                if current_content:
                    content_text = "\n".join(current_content).strip()
                    if content_text:
                        chunks.append(DocumentChunk(
                            text=content_text,
                            chunk_index=chunk_index,
                            chunk_type="text",
                            heading_context=current_heading or f"From: {filename}",
                        ))
                        chunk_index += 1
                    current_content = []
                
                # Update current heading
                current_heading = header_match.group(2).strip()
            else:
                current_content.append(line)
        
        # Add final chunk
        if current_content:
            content_text = "\n".join(current_content).strip()
            if content_text:
                chunks.append(DocumentChunk(
                    text=content_text,
                    chunk_index=chunk_index,
                    chunk_type="text",
                    heading_context=current_heading or f"From: {filename}",
                ))
        
        return chunks
    
    async def close(self):
        """Close HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


# Global service instance
document_processor = DocumentProcessor()

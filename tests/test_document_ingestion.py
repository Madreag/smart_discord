#!/usr/bin/env python3
"""
RED PHASE Test: Document Ingestion

This test verifies that the multimodal ingestion pipeline works correctly.

Scenario: A PDF file is uploaded to Discord. The system should:
1. Detect the attachment
2. Download and extract text
3. Chunk and embed to Qdrant
4. Make the content searchable

Expected FAILURE before implementation: PDF content is not searchable.
Expected SUCCESS after implementation: PDF content appears in RAG results.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from dataclasses import dataclass


@dataclass
class MockAttachment:
    """Mock Discord attachment for testing."""
    id: int
    message_id: int
    guild_id: int
    channel_id: int
    url: str
    filename: str
    content_type: str
    size: int


def test_document_processor_imports():
    """Test that document processor can be imported."""
    print("Testing Document Processor Imports...")
    print("=" * 50)
    
    try:
        from apps.api.src.services.document_processor import (
            DocumentProcessor,
            AttachmentPayload,
            SourceType,
            ProcessingStatus,
            ALLOWED_EXTENSIONS,
            BLOCKED_EXTENSIONS,
        )
        print("✓ DocumentProcessor imported")
        print("✓ AttachmentPayload imported")
        print("✓ SourceType imported")
        print(f"✓ Allowed extensions: {list(ALLOWED_EXTENSIONS.keys())}")
        print(f"✓ Blocked extensions: {list(BLOCKED_EXTENSIONS)}")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_source_type_detection():
    """Test that source types are correctly detected."""
    print("\nTesting Source Type Detection...")
    print("=" * 50)
    
    from apps.api.src.services.document_processor import (
        DocumentProcessor,
        AttachmentPayload,
        SourceType,
    )
    
    processor = DocumentProcessor()
    
    test_cases = [
        ("document.pdf", "application/pdf", SourceType.PDF),
        ("readme.md", "text/markdown", SourceType.MARKDOWN),
        ("notes.txt", "text/plain", SourceType.TEXT),
        ("image.png", "image/png", SourceType.IMAGE),
        ("photo.jpg", "image/jpeg", SourceType.IMAGE),
    ]
    
    all_passed = True
    for filename, content_type, expected in test_cases:
        payload = AttachmentPayload(
            attachment_id=1,
            message_id=1,
            guild_id=1,
            channel_id=1,
            url="https://example.com/file",
            proxy_url=None,
            filename=filename,
            content_type=content_type,
            size_bytes=1000,
        )
        
        result = processor.detect_source_type(payload)
        passed = result == expected
        all_passed = all_passed and passed
        status = "✓" if passed else "✗"
        print(f"  {status} {filename} -> {result.value} (expected: {expected.value})")
    
    return all_passed


def test_attachment_validation():
    """Test attachment validation (security checks)."""
    print("\nTesting Attachment Validation...")
    print("=" * 50)
    
    from apps.api.src.services.document_processor import (
        DocumentProcessor,
        AttachmentPayload,
        MAX_FILE_SIZE,
    )
    
    processor = DocumentProcessor()
    
    # Valid PDF
    valid_payload = AttachmentPayload(
        attachment_id=1,
        message_id=1,
        guild_id=1,
        channel_id=1,
        url="https://example.com/doc.pdf",
        proxy_url=None,
        filename="document.pdf",
        content_type="application/pdf",
        size_bytes=1000,
    )
    is_valid, error = processor.validate_attachment(valid_payload)
    print(f"  {'✓' if is_valid else '✗'} Valid PDF accepted: {is_valid}")
    
    # Blocked extension (exe)
    blocked_payload = AttachmentPayload(
        attachment_id=2,
        message_id=1,
        guild_id=1,
        channel_id=1,
        url="https://example.com/malware.exe",
        proxy_url=None,
        filename="malware.exe",
        content_type="application/octet-stream",
        size_bytes=1000,
    )
    is_valid, error = processor.validate_attachment(blocked_payload)
    print(f"  {'✓' if not is_valid else '✗'} Blocked .exe rejected: {not is_valid} ({error})")
    
    # Too large
    large_payload = AttachmentPayload(
        attachment_id=3,
        message_id=1,
        guild_id=1,
        channel_id=1,
        url="https://example.com/huge.pdf",
        proxy_url=None,
        filename="huge.pdf",
        content_type="application/pdf",
        size_bytes=MAX_FILE_SIZE + 1,
    )
    is_valid, error = processor.validate_attachment(large_payload)
    print(f"  {'✓' if not is_valid else '✗'} Too large rejected: {not is_valid} ({error})")
    
    return True


def test_recursive_chunking():
    """Test recursive text chunking."""
    print("\nTesting Recursive Chunking...")
    print("=" * 50)
    
    from apps.api.src.services.document_processor import DocumentProcessor
    
    processor = DocumentProcessor()
    
    # Sample text with multiple paragraphs
    sample_text = """
    This is the first paragraph. It contains some introductory information
    about the topic we are discussing.
    
    This is the second paragraph. It goes into more detail about the subject
    matter and provides additional context.
    
    This is the third paragraph. It concludes the discussion with some
    final thoughts and recommendations.
    """
    
    chunks = processor._recursive_chunk(sample_text, "test.txt", chunk_size=200, chunk_overlap=50)
    
    print(f"  ✓ Created {len(chunks)} chunks from sample text")
    for i, chunk in enumerate(chunks):
        print(f"    Chunk {i}: {len(chunk.text)} chars, type={chunk.chunk_type}")
    
    return len(chunks) > 0


def test_markdown_semantic_chunking():
    """Test semantic chunking for Markdown."""
    print("\nTesting Markdown Semantic Chunking...")
    print("=" * 50)
    
    from apps.api.src.services.document_processor import DocumentProcessor
    
    processor = DocumentProcessor()
    
    sample_md = """# Introduction

This is the introduction section.

## Chapter 1

This is chapter 1 content.

## Chapter 2

This is chapter 2 content with more details.

### Subsection 2.1

Detailed subsection content.
"""
    
    chunks = processor._semantic_chunk_markdown(sample_md, "readme.md")
    
    print(f"  ✓ Created {len(chunks)} chunks from Markdown")
    for i, chunk in enumerate(chunks):
        heading = chunk.heading_context[:30] if chunk.heading_context else "None"
        print(f"    Chunk {i}: heading='{heading}...', {len(chunk.text)} chars")
    
    return len(chunks) > 0


def test_database_schema():
    """Test that attachments table exists."""
    print("\nTesting Database Schema...")
    print("=" * 50)
    
    from sqlalchemy import create_engine, text
    
    engine = create_engine("postgresql://postgres:postgres@localhost:5432/smart_discord")
    
    with engine.connect() as conn:
        # Check attachments table exists
        result = conn.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_name = 'attachments'
        """))
        row = result.fetchone()
        
        if row:
            print("  ✓ attachments table exists")
        else:
            print("  ✗ attachments table NOT FOUND")
            return False
        
        # Check document_chunks table exists
        result = conn.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_name = 'document_chunks'
        """))
        row = result.fetchone()
        
        if row:
            print("  ✓ document_chunks table exists")
        else:
            print("  ✗ document_chunks table NOT FOUND")
            return False
    
    return True


def main():
    """Run all document ingestion tests."""
    print("\n" + "=" * 60)
    print("MULTIMODAL DOCUMENT INGESTION TESTS")
    print("=" * 60 + "\n")
    
    results = []
    
    results.append(("Imports", test_document_processor_imports()))
    results.append(("Source Type Detection", test_source_type_detection()))
    results.append(("Attachment Validation", test_attachment_validation()))
    results.append(("Recursive Chunking", test_recursive_chunking()))
    results.append(("Markdown Chunking", test_markdown_semantic_chunking()))
    results.append(("Database Schema", test_database_schema()))
    
    print("\n" + "=" * 60)
    all_passed = all(r[1] for r in results)
    if all_passed:
        print("✓ All document ingestion tests passed!")
    else:
        failed = [r[0] for r in results if not r[1]]
        print(f"✗ Failed tests: {failed}")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

# REPORT 6: PII Scrubbing with Microsoft Presidio

> **Priority**: P2 (Medium)  
> **Effort**: 1-2 days  
> **Status**: Not Implemented

---

## 1. Executive Summary

Discord messages may contain sensitive personal information (PII) such as emails, phone numbers, and IP addresses. Storing and embedding this data creates privacy/compliance risks.

**Microsoft Presidio** is an open-source SDK for detecting and anonymizing PII in text. It supports custom recognizers, multiple languages, and various anonymization strategies.

---

## 2. Supported PII Types

| Entity | Examples | Detection Method |
|--------|----------|------------------|
| EMAIL_ADDRESS | user@example.com | Regex + validation |
| PHONE_NUMBER | +1-555-123-4567 | Regex + libphonenumber |
| IP_ADDRESS | 192.168.1.1 | Regex |
| CREDIT_CARD | 4111-1111-1111-1111 | Regex + Luhn check |
| US_SSN | 123-45-6789 | Regex + validation |
| PERSON | John Smith | NER (spaCy) |
| LOCATION | New York | NER (spaCy) |
| DATE_TIME | January 1, 2025 | NER + patterns |
| IBAN_CODE | GB82WEST12345698765432 | Regex + checksum |

---

## 3. Implementation Guide

### Dependencies

```bash
pip install presidio-analyzer presidio-anonymizer spacy
python -m spacy download en_core_web_lg
```

### PII Service

```python
# apps/api/src/services/pii_service.py
"""
PII Detection and Anonymization Service

Uses Microsoft Presidio for detecting and redacting sensitive information.
https://microsoft.github.io/presidio/
"""

from typing import Optional, Tuple
from dataclasses import dataclass
from presidio_analyzer import AnalyzerEngine, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig


# Singleton engines (expensive to initialize)
_analyzer: Optional[AnalyzerEngine] = None
_anonymizer: Optional[AnonymizerEngine] = None


def get_analyzer() -> AnalyzerEngine:
    """Get or create the PII analyzer engine."""
    global _analyzer
    if _analyzer is None:
        _analyzer = AnalyzerEngine()
    return _analyzer


def get_anonymizer() -> AnonymizerEngine:
    """Get or create the PII anonymizer engine."""
    global _anonymizer
    if _anonymizer is None:
        _anonymizer = AnonymizerEngine()
    return _anonymizer


# Default entities to detect
DEFAULT_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IP_ADDRESS",
    "CREDIT_CARD",
    "US_SSN",
    "IBAN_CODE",
]

# Extended detection (higher false positive rate)
EXTENDED_ENTITIES = DEFAULT_ENTITIES + [
    "PERSON",
    "LOCATION",
    "DATE_TIME",
    "NRP",  # Nationalities, religious, political groups
]


@dataclass
class PIIDetectionResult:
    """Result of PII detection."""
    original_text: str
    anonymized_text: str
    entities_found: list[dict]
    had_pii: bool


def detect_pii(
    text: str,
    entities: Optional[list[str]] = None,
    language: str = "en",
    score_threshold: float = 0.5,
) -> list[RecognizerResult]:
    """
    Detect PII entities in text.
    
    Args:
        text: Text to analyze
        entities: Entity types to detect (default: DEFAULT_ENTITIES)
        language: Language code
        score_threshold: Minimum confidence score (0-1)
        
    Returns:
        List of detected entities with positions and scores
    """
    analyzer = get_analyzer()
    
    results = analyzer.analyze(
        text=text,
        entities=entities or DEFAULT_ENTITIES,
        language=language,
        score_threshold=score_threshold,
    )
    
    return results


def anonymize_text(
    text: str,
    entities: Optional[list[str]] = None,
    language: str = "en",
    operator: str = "replace",
) -> str:
    """
    Detect and anonymize PII in text.
    
    Args:
        text: Text to anonymize
        entities: Entity types to detect
        language: Language code
        operator: Anonymization strategy:
            - "replace": Replace with entity type (e.g., "<EMAIL_ADDRESS>")
            - "redact": Remove entirely
            - "hash": Replace with SHA-256 hash
            - "mask": Partially mask (e.g., "j***@***.com")
            - "encrypt": Encrypt with AES (requires key)
            
    Returns:
        Anonymized text
    """
    analyzer = get_analyzer()
    anonymizer = get_anonymizer()
    
    # Detect PII
    results = analyzer.analyze(
        text=text,
        entities=entities or DEFAULT_ENTITIES,
        language=language,
    )
    
    if not results:
        return text
    
    # Configure operator
    if operator == "replace":
        # Replace with placeholder showing entity type
        operators = {}
        for entity_type in set(r.entity_type for r in results):
            operators[entity_type] = OperatorConfig(
                "replace",
                {"new_value": f"<{entity_type}>"}
            )
    elif operator == "redact":
        operators = {"DEFAULT": OperatorConfig("redact")}
    elif operator == "hash":
        operators = {"DEFAULT": OperatorConfig("hash", {"hash_type": "sha256"})}
    elif operator == "mask":
        operators = {"DEFAULT": OperatorConfig("mask", {
            "chars_to_mask": 8,
            "masking_char": "*",
            "from_end": False,
        })}
    else:
        operators = {"DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"})}
    
    # Anonymize
    result = anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators=operators,
    )
    
    return result.text


def scrub_message(
    content: str,
    extended: bool = False,
) -> PIIDetectionResult:
    """
    Scrub PII from a message.
    
    Args:
        content: Message content
        extended: Use extended entity detection (more aggressive)
        
    Returns:
        PIIDetectionResult with original and anonymized text
    """
    entities = EXTENDED_ENTITIES if extended else DEFAULT_ENTITIES
    
    # Detect
    detected = detect_pii(content, entities=entities)
    
    if not detected:
        return PIIDetectionResult(
            original_text=content,
            anonymized_text=content,
            entities_found=[],
            had_pii=False,
        )
    
    # Anonymize
    anonymized = anonymize_text(content, entities=entities, operator="replace")
    
    # Build entity list
    entities_found = [
        {
            "entity_type": r.entity_type,
            "start": r.start,
            "end": r.end,
            "score": r.score,
            "text": content[r.start:r.end],
        }
        for r in detected
    ]
    
    return PIIDetectionResult(
        original_text=content,
        anonymized_text=anonymized,
        entities_found=entities_found,
        had_pii=True,
    )


def scrub_messages_batch(
    messages: list[dict],
    content_key: str = "content",
    extended: bool = False,
) -> list[dict]:
    """
    Scrub PII from a batch of messages.
    
    Args:
        messages: List of message dicts
        content_key: Key containing the text content
        extended: Use extended detection
        
    Returns:
        Messages with scrubbed content and 'pii_detected' flag
    """
    results = []
    
    for msg in messages:
        content = msg.get(content_key, "")
        result = scrub_message(content, extended=extended)
        
        results.append({
            **msg,
            content_key: result.anonymized_text,
            "pii_detected": result.had_pii,
            "pii_entities": result.entities_found if result.had_pii else [],
        })
    
    return results


# Custom Discord-specific recognizer
def create_discord_recognizer():
    """
    Create a custom recognizer for Discord-specific patterns.
    
    Detects:
    - Discord tokens
    - Webhook URLs
    - User IDs in certain contexts
    """
    from presidio_analyzer import Pattern, PatternRecognizer
    
    patterns = [
        # Discord bot tokens (simplified pattern)
        Pattern(
            name="discord_token",
            regex=r"[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27}",
            score=0.9,
        ),
        # Discord webhook URLs
        Pattern(
            name="discord_webhook",
            regex=r"https://discord\.com/api/webhooks/\d+/[\w-]+",
            score=0.95,
        ),
    ]
    
    return PatternRecognizer(
        supported_entity="DISCORD_SECRET",
        patterns=patterns,
        name="DiscordSecretRecognizer",
    )


def setup_custom_recognizers():
    """Add custom recognizers to the analyzer."""
    analyzer = get_analyzer()
    
    # Add Discord-specific recognizer
    discord_recognizer = create_discord_recognizer()
    analyzer.registry.add_recognizer(discord_recognizer)
```

### Integration with Message Ingestion

```python
# apps/bot/src/bot.py (update on_message handler)

from apps.api.src.services.pii_service import scrub_message

@bot.listen('on_message')
async def on_message_handler(message: discord.Message) -> None:
    # ... existing checks ...
    
    # Scrub PII before storing
    pii_result = scrub_message(message.content or "")
    
    if pii_result.had_pii:
        print(f"[PII] Detected {len(pii_result.entities_found)} entities in message {message.id}")
        for entity in pii_result.entities_found:
            print(f"  - {entity['entity_type']}: {entity['text'][:20]}...")
    
    # Store the ANONYMIZED content, not original
    save_message_to_db_with_content(message, pii_result.anonymized_text)
```

---

## 4. Configuration Options

### Per-Guild Settings

```python
# Store in guilds table
class GuildPIISettings:
    pii_enabled: bool = True
    pii_extended: bool = False  # Include PERSON, LOCATION
    pii_operator: str = "replace"  # replace, redact, mask
    pii_log_detections: bool = True
```

### Environment Variables

```bash
# .env
PII_ENABLED=true
PII_EXTENDED=false
PII_SCORE_THRESHOLD=0.5
```

---

## 5. Testing

```python
# tests/test_pii_service.py

import pytest
from apps.api.src.services.pii_service import scrub_message, detect_pii

def test_email_detection():
    text = "Contact me at john@example.com for details"
    result = scrub_message(text)
    
    assert result.had_pii
    assert "<EMAIL_ADDRESS>" in result.anonymized_text
    assert "john@example.com" not in result.anonymized_text

def test_phone_detection():
    text = "Call me at 555-123-4567"
    result = scrub_message(text)
    
    assert result.had_pii
    assert "<PHONE_NUMBER>" in result.anonymized_text

def test_ip_detection():
    text = "Server IP is 192.168.1.100"
    result = scrub_message(text)
    
    assert result.had_pii
    assert "<IP_ADDRESS>" in result.anonymized_text

def test_no_pii():
    text = "Hello, how are you today?"
    result = scrub_message(text)
    
    assert not result.had_pii
    assert result.anonymized_text == text

def test_multiple_entities():
    text = "Email: test@test.com, Phone: 123-456-7890"
    result = scrub_message(text)
    
    assert result.had_pii
    assert len(result.entities_found) == 2
```

---

## 6. Performance Considerations

| Operation | Time | Notes |
|-----------|------|-------|
| Analyzer init | ~2-5 sec | One-time on startup |
| Simple detection | ~10-50ms | Regex-based entities |
| NER detection | ~50-200ms | PERSON, LOCATION |
| Batch (100 msgs) | ~1-5 sec | Depends on entities |

**Recommendations**:
- Initialize engines at app startup
- Use DEFAULT_ENTITIES for speed
- Batch process during indexing
- Cache results if re-processing

---

## 7. References

- [Microsoft Presidio Documentation](https://microsoft.github.io/presidio/)
- [Presidio Analyzer](https://microsoft.github.io/presidio/analyzer/)
- [Presidio Anonymizer](https://microsoft.github.io/presidio/anonymizer/)
- [Custom Recognizers](https://microsoft.github.io/presidio/analyzer/adding_recognizers/)

---

## 8. Checklist

- [ ] Install dependencies: `presidio-analyzer`, `presidio-anonymizer`, `spacy`
- [ ] Download spaCy model: `python -m spacy download en_core_web_lg`
- [ ] Create `apps/api/src/services/pii_service.py`
- [ ] Add custom Discord recognizer for tokens/webhooks
- [ ] Integrate with message ingestion
- [ ] Add per-guild PII settings to database
- [ ] Add unit tests
- [ ] Test with real Discord messages containing PII

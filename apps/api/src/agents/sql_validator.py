"""
SQL Security Validator

CRITICAL SECURITY: This validator ensures that only SELECT queries are executed.
Any attempt to run INSERT, UPDATE, DELETE, DROP, or other mutating statements
will be rejected.

This is a defense-in-depth measure on top of using a read-only database replica.
"""

import re
from typing import Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of SQL validation."""
    is_valid: bool
    error: Optional[str] = None
    sanitized_sql: Optional[str] = None


# Forbidden SQL keywords that indicate mutation
FORBIDDEN_KEYWORDS: set[str] = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "TRUNCATE",
    "REPLACE",
    "MERGE",
    "UPSERT",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "CALL",
    "SET",
    "LOCK",
    "UNLOCK",
}

# Patterns that might indicate SQL injection attempts
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r";\s*(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)", re.IGNORECASE),
    re.compile(r"--.*$", re.MULTILINE),  # SQL comments (potential injection)
    re.compile(r"/\*.*?\*/", re.DOTALL),  # Block comments
    re.compile(r"UNION\s+ALL\s+SELECT", re.IGNORECASE),  # Union injection
    re.compile(r"INTO\s+OUTFILE", re.IGNORECASE),  # File write attempt
    re.compile(r"INTO\s+DUMPFILE", re.IGNORECASE),  # File write attempt
    re.compile(r"LOAD_FILE", re.IGNORECASE),  # File read attempt
]


def validate_sql(sql: str) -> ValidationResult:
    """
    Validate that SQL is a safe SELECT query.
    
    SECURITY INVARIANT: Only SELECT statements are allowed.
    
    Args:
        sql: The SQL query to validate
        
    Returns:
        ValidationResult with is_valid=True if safe, False otherwise
    """
    if not sql or not sql.strip():
        return ValidationResult(
            is_valid=False,
            error="Empty SQL query"
        )
    
    # Normalize whitespace and strip
    normalized = " ".join(sql.split()).strip()
    
    # Check if query starts with SELECT (case-insensitive)
    if not normalized.upper().startswith("SELECT"):
        return ValidationResult(
            is_valid=False,
            error=f"Query must start with SELECT. Got: {normalized[:50]}..."
        )
    
    # Check for forbidden keywords
    upper_sql = normalized.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        # Look for keyword as a whole word (not part of column name)
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, upper_sql):
            return ValidationResult(
                is_valid=False,
                error=f"Forbidden keyword detected: {keyword}"
            )
    
    # Check for injection patterns
    for pattern in INJECTION_PATTERNS:
        if pattern.search(normalized):
            return ValidationResult(
                is_valid=False,
                error=f"Potential SQL injection pattern detected"
            )
    
    # Check for multiple statements (semicolon followed by more SQL)
    if ";" in normalized:
        # Allow trailing semicolon, but not multiple statements
        parts = [p.strip() for p in normalized.split(";") if p.strip()]
        if len(parts) > 1:
            return ValidationResult(
                is_valid=False,
                error="Multiple SQL statements not allowed"
            )
    
    return ValidationResult(
        is_valid=True,
        sanitized_sql=normalized.rstrip(";")  # Remove trailing semicolon
    )


def validate_and_enforce_guild_filter(sql: str, guild_id: int) -> ValidationResult:
    """
    Validate SQL and ensure it filters by guild_id for multi-tenant isolation.
    
    SECURITY INVARIANT: All queries MUST filter by guild_id to prevent
    cross-tenant data access.
    
    Args:
        sql: The SQL query to validate
        guild_id: The guild_id that must be present in WHERE clause
        
    Returns:
        ValidationResult with modified SQL if needed
    """
    base_result = validate_sql(sql)
    if not base_result.is_valid:
        return base_result
    
    sanitized = base_result.sanitized_sql
    assert sanitized is not None
    
    # Check if guild_id filter is present
    guild_id_pattern = re.compile(
        rf"\bguild_id\s*=\s*{guild_id}\b|\bguild_id\s*=\s*\${{\s*guild_id\s*}}\b",
        re.IGNORECASE
    )
    
    if not guild_id_pattern.search(sanitized):
        # Try to inject guild_id filter
        if "WHERE" in sanitized.upper():
            # Add to existing WHERE clause
            where_idx = sanitized.upper().index("WHERE")
            before_where = sanitized[:where_idx + 5]  # Include "WHERE"
            after_where = sanitized[where_idx + 5:]
            modified = f"{before_where} guild_id = {guild_id} AND{after_where}"
        else:
            # Check for GROUP BY, ORDER BY, LIMIT to insert WHERE before them
            upper = sanitized.upper()
            insert_before = None
            for clause in ["GROUP BY", "ORDER BY", "LIMIT", "HAVING"]:
                if clause in upper:
                    idx = upper.index(clause)
                    if insert_before is None or idx < insert_before:
                        insert_before = idx
            
            if insert_before:
                before = sanitized[:insert_before].rstrip()
                after = sanitized[insert_before:]
                modified = f"{before} WHERE guild_id = {guild_id} {after}"
            else:
                modified = f"{sanitized} WHERE guild_id = {guild_id}"
        
        return ValidationResult(
            is_valid=True,
            sanitized_sql=modified
        )
    
    return ValidationResult(
        is_valid=True,
        sanitized_sql=sanitized
    )

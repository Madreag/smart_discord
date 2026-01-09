"""
Test SQL Validator Security

CRITICAL: These tests verify that the SQL validator correctly:
1. Rejects all non-SELECT statements
2. Enforces guild_id filtering for multi-tenant isolation
3. Detects SQL injection attempts
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apps.api.src.agents.sql_validator import (
    validate_sql,
    validate_and_enforce_guild_filter,
    ValidationResult,
)


def test_valid_select_queries() -> tuple[int, int, list[str]]:
    """Test that valid SELECT queries pass validation."""
    test_cases = [
        "SELECT * FROM messages WHERE guild_id = 123",
        "SELECT COUNT(*) FROM messages",
        "SELECT u.username, COUNT(m.id) FROM messages m JOIN users u ON m.author_id = u.id GROUP BY u.id",
        "SELECT id, content FROM messages ORDER BY message_timestamp DESC LIMIT 10",
    ]
    
    passed = 0
    failures = []
    
    for sql in test_cases:
        result = validate_sql(sql)
        if result.is_valid:
            passed += 1
            print(f"✓ PASS: Valid SELECT accepted")
        else:
            msg = f"✗ FAIL: Valid SELECT rejected: {sql[:50]}... Error: {result.error}"
            print(msg)
            failures.append(msg)
    
    return (passed, len(test_cases), failures)


def test_reject_mutations() -> tuple[int, int, list[str]]:
    """Test that mutation statements are rejected."""
    test_cases = [
        ("INSERT INTO messages VALUES (1, 2, 3)", "INSERT"),
        ("UPDATE messages SET content = 'hacked'", "UPDATE"),
        ("DELETE FROM messages WHERE id = 1", "DELETE"),
        ("DROP TABLE messages", "DROP"),
        ("CREATE TABLE evil (id INT)", "CREATE"),
        ("ALTER TABLE messages ADD COLUMN hacked TEXT", "ALTER"),
        ("TRUNCATE messages", "TRUNCATE"),
    ]
    
    passed = 0
    failures = []
    
    for sql, keyword in test_cases:
        result = validate_sql(sql)
        if not result.is_valid:
            passed += 1
            print(f"✓ PASS: {keyword} rejected")
        else:
            msg = f"✗ FAIL: {keyword} was NOT rejected: {sql}"
            print(msg)
            failures.append(msg)
    
    return (passed, len(test_cases), failures)


def test_reject_injection_attempts() -> tuple[int, int, list[str]]:
    """Test that SQL injection attempts are rejected."""
    test_cases = [
        "SELECT * FROM messages; DROP TABLE messages",
        "SELECT * FROM messages; DELETE FROM messages",
        "SELECT * FROM messages UNION ALL SELECT * FROM users",
        "SELECT * FROM messages INTO OUTFILE '/etc/passwd'",
    ]
    
    passed = 0
    failures = []
    
    for sql in test_cases:
        result = validate_sql(sql)
        if not result.is_valid:
            passed += 1
            print(f"✓ PASS: Injection attempt rejected")
        else:
            msg = f"✗ FAIL: Injection NOT rejected: {sql[:50]}..."
            print(msg)
            failures.append(msg)
    
    return (passed, len(test_cases), failures)


def test_guild_id_enforcement() -> tuple[int, int, list[str]]:
    """Test that guild_id filter is enforced."""
    guild_id = 123456789
    
    test_cases = [
        # (input_sql, should_contain_guild_id)
        ("SELECT * FROM messages", True),
        ("SELECT COUNT(*) FROM messages GROUP BY author_id", True),
        ("SELECT * FROM messages WHERE guild_id = 123456789", True),
        ("SELECT * FROM messages ORDER BY id", True),
    ]
    
    passed = 0
    failures = []
    
    for sql, _ in test_cases:
        result = validate_and_enforce_guild_filter(sql, guild_id)
        if result.is_valid and str(guild_id) in (result.sanitized_sql or ""):
            passed += 1
            print(f"✓ PASS: guild_id enforced")
        else:
            msg = f"✗ FAIL: guild_id NOT enforced: {result.sanitized_sql}"
            print(msg)
            failures.append(msg)
    
    return (passed, len(test_cases), failures)


def main() -> int:
    """Run all SQL validator tests."""
    print("=" * 60)
    print("SQL Validator Security Tests")
    print("=" * 60)
    
    total_passed = 0
    total_tests = 0
    all_failures = []
    
    print("\n--- Valid SELECT Queries ---")
    p, t, f = test_valid_select_queries()
    total_passed += p
    total_tests += t
    all_failures.extend(f)
    
    print("\n--- Reject Mutation Statements ---")
    p, t, f = test_reject_mutations()
    total_passed += p
    total_tests += t
    all_failures.extend(f)
    
    print("\n--- Reject Injection Attempts ---")
    p, t, f = test_reject_injection_attempts()
    total_passed += p
    total_tests += t
    all_failures.extend(f)
    
    print("\n--- Guild ID Enforcement ---")
    p, t, f = test_guild_id_enforcement()
    total_passed += p
    total_tests += t
    all_failures.extend(f)
    
    print()
    print("=" * 60)
    print(f"Results: {total_passed}/{total_tests} passed")
    print("=" * 60)
    
    if total_passed == total_tests:
        print("✓ ALL SECURITY TESTS PASSED")
        return 0
    else:
        print("✗ SECURITY TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())

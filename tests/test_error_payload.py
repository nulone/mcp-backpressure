"""
Tests for OverloadError JSON-RPC payload structure.

Verifies error serialization, required fields, and reason values.
"""

import json

import pytest

from mcp_backpressure import OverloadError


def test_error_is_json_serializable():
    """
    Test that OverloadError.to_json_rpc() produces JSON-serializable output.

    Verifies that the error can be serialized to JSON without errors.
    """
    error = OverloadError(
        reason="queue_full",
        active=5,
        max_concurrent=5,
        queued=10,
        queue_size=10,
        queue_timeout_ms=30000,
        code=-32001,
        message="SERVER_OVERLOADED",
        retry_after_ms=1000,
    )

    json_rpc = error.to_json_rpc()

    # Should be JSON serializable
    try:
        serialized = json.dumps(json_rpc)
        assert isinstance(serialized, str)
    except (TypeError, ValueError) as e:
        pytest.fail(f"Error payload not JSON serializable: {e}")

    # Verify round-trip
    deserialized = json.loads(serialized)
    assert deserialized["code"] == -32001
    assert deserialized["message"] == "SERVER_OVERLOADED"
    assert deserialized["data"]["reason"] == "queue_full"
    assert deserialized["data"]["active"] == 5
    assert deserialized["data"]["queued"] == 10


def test_error_has_required_fields():
    """
    Test that OverloadError payload has all required JSON-RPC fields.

    Required fields (per DESIGN.md):
    - code: int
    - message: str
    - data: dict with:
      - reason: str
      - active: int
      - queued: int
      - max_concurrent: int
      - queue_size: int
      - queue_timeout_ms: int
      - retry_after_ms: int
    """
    error = OverloadError(
        reason="concurrency_limit",
        active=5,
        max_concurrent=5,
        queued=0,
        queue_size=0,
        queue_timeout_ms=30000,
        code=-32001,
        message="SERVER_OVERLOADED",
        retry_after_ms=1000,
    )

    json_rpc = error.to_json_rpc()

    # Check top-level fields
    assert "code" in json_rpc, "Missing 'code' field"
    assert "message" in json_rpc, "Missing 'message' field"
    assert "data" in json_rpc, "Missing 'data' field"

    # Check types
    assert isinstance(json_rpc["code"], int), "code must be int"
    assert isinstance(json_rpc["message"], str), "message must be str"
    assert isinstance(json_rpc["data"], dict), "data must be dict"

    # Check data fields
    data = json_rpc["data"]
    required_data_fields = [
        "reason",
        "active",
        "queued",
        "max_concurrent",
        "queue_size",
        "queue_timeout_ms",
        "retry_after_ms",
    ]

    for field in required_data_fields:
        assert field in data, f"Missing required data field: {field}"

    # Check data field types
    assert isinstance(data["reason"], str), "reason must be str"
    assert isinstance(data["active"], int), "active must be int"
    assert isinstance(data["queued"], int), "queued must be int"
    assert isinstance(data["max_concurrent"], int), "max_concurrent must be int"
    assert isinstance(data["queue_size"], int), "queue_size must be int"
    assert isinstance(data["queue_timeout_ms"], int), "queue_timeout_ms must be int"
    assert isinstance(data["retry_after_ms"], int), "retry_after_ms must be int"

    # Check values
    assert json_rpc["code"] == -32001
    assert json_rpc["message"] == "SERVER_OVERLOADED"
    assert data["reason"] == "concurrency_limit"
    assert data["active"] == 5
    assert data["queued"] == 0
    assert data["max_concurrent"] == 5
    assert data["queue_size"] == 0
    assert data["queue_timeout_ms"] == 30000
    assert data["retry_after_ms"] == 1000


def test_reason_values():
    """
    Test that OverloadError supports all three valid reason values.

    Valid reasons (per DESIGN.md):
    - 'concurrency_limit': max_concurrent reached, no queue
    - 'queue_full': queue is at capacity
    - 'queue_timeout': request timed out while waiting in queue
    """
    valid_reasons = ["concurrency_limit", "queue_full", "queue_timeout"]

    for reason in valid_reasons:
        error = OverloadError(
            reason=reason,
            active=5,
            max_concurrent=5,
            queued=10,
            queue_size=10,
            queue_timeout_ms=30000,
        )

        assert error.reason == reason
        json_rpc = error.to_json_rpc()
        assert json_rpc["data"]["reason"] == reason


def test_error_data_property():
    """
    Test that error.data property returns correct structure.
    """
    error = OverloadError(
        reason="queue_timeout",
        active=3,
        max_concurrent=5,
        queued=7,
        queue_size=10,
        queue_timeout_ms=15000,
        retry_after_ms=2000,
    )

    data = error.data

    assert data["reason"] == "queue_timeout"
    assert data["active"] == 3
    assert data["queued"] == 7
    assert data["max_concurrent"] == 5
    assert data["queue_size"] == 10
    assert data["queue_timeout_ms"] == 15000
    assert data["retry_after_ms"] == 2000


def test_error_with_custom_code():
    """
    Test that custom error codes are respected.
    """
    custom_code = -32099

    error = OverloadError(
        reason="queue_full",
        active=5,
        max_concurrent=5,
        code=custom_code,
    )

    assert error.code == custom_code
    json_rpc = error.to_json_rpc()
    assert json_rpc["code"] == custom_code


def test_error_with_custom_message():
    """
    Test that custom error messages are respected.
    """
    custom_message = "CUSTOM_OVERLOAD_MESSAGE"

    error = OverloadError(
        reason="concurrency_limit",
        active=10,
        max_concurrent=10,
        message=custom_message,
    )

    assert error.message == custom_message
    json_rpc = error.to_json_rpc()
    assert json_rpc["message"] == custom_message


def test_error_default_values():
    """
    Test that OverloadError uses correct defaults for optional fields.
    """
    error = OverloadError(
        reason="concurrency_limit",
        active=5,
        max_concurrent=5,
    )

    # Check defaults
    assert error.code == -32001
    assert error.message == "SERVER_OVERLOADED"
    assert error.queued == 0
    assert error.queue_size == 0
    assert error.queue_timeout_ms == 0
    assert error.retry_after_ms == 1000


def test_error_string_representation():
    """
    Test that OverloadError has useful string representation.
    """
    error = OverloadError(
        reason="queue_full",
        active=5,
        max_concurrent=5,
    )

    error_str = str(error)
    assert "SERVER_OVERLOADED" in error_str
    assert "queue_full" in error_str


def test_error_complete_payload_example():
    """
    Test complete error payload matches DESIGN.md example.

    Example from DESIGN.md:
    {
      "code": -32001,
      "message": "SERVER_OVERLOADED",
      "data": {
        "reason": "queue_full | queue_timeout | concurrency_limit",
        "active": 5,
        "queued": 10,
        "max_concurrent": 5,
        "queue_size": 10,
        "queue_timeout_ms": 30000,
        "retry_after_ms": 1000
      }
    }
    """
    error = OverloadError(
        reason="queue_full",
        active=5,
        max_concurrent=5,
        queued=10,
        queue_size=10,
        queue_timeout_ms=30000,
        retry_after_ms=1000,
        code=-32001,
        message="SERVER_OVERLOADED",
    )

    json_rpc = error.to_json_rpc()

    # Match DESIGN.md structure
    assert json_rpc == {
        "code": -32001,
        "message": "SERVER_OVERLOADED",
        "data": {
            "reason": "queue_full",
            "active": 5,
            "queued": 10,
            "max_concurrent": 5,
            "queue_size": 10,
            "queue_timeout_ms": 30000,
            "retry_after_ms": 1000,
        },
    }


def test_all_reason_values_in_payload():
    """
    Test payload for each of the three reason values.
    """
    test_cases = [
        {
            "reason": "concurrency_limit",
            "active": 5,
            "queued": 0,
            "max_concurrent": 5,
            "queue_size": 0,
        },
        {
            "reason": "queue_full",
            "active": 5,
            "queued": 10,
            "max_concurrent": 5,
            "queue_size": 10,
        },
        {
            "reason": "queue_timeout",
            "active": 5,
            "queued": 10,
            "max_concurrent": 5,
            "queue_size": 10,
        },
    ]

    for case in test_cases:
        error = OverloadError(**case)
        json_rpc = error.to_json_rpc()

        assert json_rpc["data"]["reason"] == case["reason"]
        assert json_rpc["code"] == -32001
        assert json_rpc["message"] == "SERVER_OVERLOADED"

        # Verify serializable
        serialized = json.dumps(json_rpc)
        assert isinstance(serialized, str)

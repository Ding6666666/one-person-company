import json

import pytest
from dsh_company.dsh_gateway.control_requests import (
    ApprovalControlRequest,
    DelegationControlRequest,
    is_control_request_candidate,
    parse_control_request,
)


def test_parses_complete_delegation_request_only() -> None:
    parsed = parse_control_request(
        json.dumps(
            {
                "kind": "delegation",
                "target_employee_id": " emp-b ",
                "objective": " 事实核查 ",
                "acceptance_criteria": [" 列出来源 "],
                "required_actions": [" workspace.read "],
                "resource_values": [" ws-1 "],
                "reason": " 需要独立核查 ",
            }
        )
    )

    assert isinstance(parsed, DelegationControlRequest)
    assert parsed.target_employee_id == "emp-b"
    assert parsed.acceptance_criteria == ("列出来源",)
    assert parsed.required_actions == ("workspace.read",)
    assert parsed.resource_values == ("ws-1",)


def test_parses_complete_approval_request() -> None:
    parsed = parse_control_request(
        '{"kind":"approval","action":"workspace.write",'
        '"resources":[" repo-a "],"reason":" update release notes "}'
    )

    assert isinstance(parsed, ApprovalControlRequest)
    assert parsed.action == "workspace.write"
    assert parsed.resources == ("repo-a",)
    assert parsed.reason == "update release notes"


@pytest.mark.parametrize(
    "raw",
    [
        '{"kind":"delegation"}',
        'prefix {"kind":"delegation"}',
        '{"kind":"approval","action":"unknown.action","resources":[],"reason":"x"}',
        '{"kind":"approval","action":"workspace.write","resources":[],"reason":"x"}',
        '{"kind":"approval","action":"workspace.write","resources":["ws"],"reason":"x","extra":true}',
        '[{"kind":"approval"}]',
        '{} trailing',
    ],
)
def test_rejects_partial_embedded_unknown_or_non_object_requests(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_control_request(raw)


def test_rejects_more_than_32_kib() -> None:
    with pytest.raises(ValueError, match="32 KiB"):
        parse_control_request(" " * (32 * 1024 + 1))


@pytest.mark.parametrize(
    "field_value",
    [" ", "x" * 501],
)
def test_rejects_blank_or_unbounded_reason(field_value: str) -> None:
    raw = json.dumps(
        {
            "kind": "approval",
            "action": "workspace.write",
            "resources": ["repo-a"],
            "reason": field_value,
        }
    )
    with pytest.raises(ValueError):
        parse_control_request(raw)


@pytest.mark.parametrize(
    "raw",
    [
        'The field "kind" needs "approval" from a reviewer.',
        'Compare "kind" with either "delegation" or another category.',
        'Normal prose mentions "approval" before it later mentions "kind".',
    ],
)
def test_normal_prose_is_not_a_control_request_candidate(raw: str) -> None:
    assert is_control_request_candidate(raw) is False


@pytest.mark.parametrize(
    "raw",
    [
        '{"kind":"approval"}',
        'prefix {"kind" : "delegation"}',
        'prefix {"kind"\n:\n"approval"}',
    ],
)
def test_discriminator_key_value_shape_is_a_control_candidate(raw: str) -> None:
    assert is_control_request_candidate(raw) is True

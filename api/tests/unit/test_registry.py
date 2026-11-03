"""Tool registry (step 3.4): strict schemas (snapshot), ordering, permission gates, error
wrapping, parallel execution order, manifest. DB-backed behaviour: tests/integration/
test_tools_admissions.py."""

import datetime as dt
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.agent.registry import Registry, Tool, ToolContext, ToolError, ToolRuntime, strict_schema
from app.agent.tools import build_registry
from app.agent.tools.leads import normalize_pk_phone

SNAPSHOT = Path(__file__).parent / "snapshots" / "tool_schemas.json"


def ctx(verified: bool = False) -> ToolContext:
    return ToolContext(
        institution_id=uuid.uuid4(),
        contact_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        channel="widget",
        verified=verified,
        institution_type="school",
        timezone="Asia/Karachi",
        now=dt.datetime(2026, 11, 3, 5, 0, tzinfo=dt.UTC),
    )


RUNTIME = ToolRuntime(sessionmaker=None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_session(_sm: Any, _inst: uuid.UUID) -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr("app.agent.registry.tenant_session", fake_session)


def _walk_objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for v in node.values():
            found.extend(_walk_objects(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_walk_objects(v))
    return found


def test_every_tool_schema_is_strict() -> None:
    reg = build_registry()
    for module in ("admissions", "fees", "general"):
        defs = reg.definitions(module)
        assert [d["name"] for d in defs] == sorted(d["name"] for d in defs)
        for d in defs:
            assert d["strict"] is True
            assert len(d["description"]) > 40
            for obj in _walk_objects(d["input_schema"]):
                assert obj["additionalProperties"] is False, d["name"]
                assert obj["required"] == list(obj.get("properties", {})), d["name"]


def test_tool_schema_snapshot() -> None:
    reg = build_registry()
    current = {
        "admissions": reg.definitions("admissions"),
        "fees": reg.definitions("fees"),
        "permissions": {t["name"]: t["annotations"] for t in reg.manifest()["tools"]},
    }
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(current, indent=1, ensure_ascii=False) + "\n")
    expected = json.loads(SNAPSHOT.read_text())
    assert current == expected, "tool schemas changed — a release: UPDATE_SNAPSHOTS=1 + evals"


def test_module_subsets() -> None:
    reg = build_registry()
    adm = {t.name for t in reg.list_tools("admissions")}
    fees = {t.name for t in reg.list_tools("fees")}
    assert {"book_visit", "save_lead", "get_fee_table", "handoff_to_human"} <= adm
    assert not adm & {"verify_parent", "get_fee_status"}
    assert {"verify_parent", "get_fee_status", "get_fee_table", "handoff_to_human"} <= fees
    assert "book_visit" not in fees
    assert {t.name for t in reg.list_tools("general")} == adm


def test_optional_fields_become_required_nullable() -> None:
    class In(BaseModel):
        a: str
        b: int | None = None

    schema = strict_schema(In)
    assert schema["required"] == ["a", "b"]
    assert {"type": "null"} in schema["properties"]["b"]["anyOf"]


class EchoIn(BaseModel):
    text: str


class EchoOut(BaseModel):
    text: str


def _registry() -> Registry:
    async def echo(args: EchoIn, c: ToolContext, s: Any, r: ToolRuntime) -> EchoOut:
        if args.text == "boom":
            raise RuntimeError("secret internal detail")
        if args.text == "expected":
            raise ToolError("Ask the contact for their class.")
        return EchoOut(text=args.text.upper())

    reg = Registry()
    reg.register(Tool("echo", "Echo tool for tests, uppercases text.", EchoIn, EchoOut, echo))
    reg.register(
        Tool("secret", "Verified only.", EchoIn, EchoOut, echo, permission="verified_parent")
    )
    reg.register(Tool("staffy", "Staff only.", EchoIn, EchoOut, echo, permission="staff"))
    return reg


async def test_execute_success_and_error_wrapping() -> None:
    reg = _registry()
    ok = await reg.execute("echo", {"text": "hi"}, ctx(), RUNTIME, tool_use_id="t1")
    assert ok.block() == {"type": "tool_result", "tool_use_id": "t1", "content": '{"text":"HI"}'}
    bad = await reg.execute("echo", {"txt": "hi"}, ctx(), RUNTIME, tool_use_id="t2")
    assert bad.is_error and "Invalid input" in bad.content and bad.block()["is_error"] is True
    expected = await reg.execute("echo", {"text": "expected"}, ctx(), RUNTIME)
    assert expected.is_error and expected.content == "Ask the contact for their class."
    boom = await reg.execute("echo", {"text": "boom"}, ctx(), RUNTIME)
    assert boom.is_error and "secret" not in boom.content
    unknown = await reg.execute("nope", {}, ctx(), RUNTIME)
    assert unknown.is_error


async def test_permission_gates() -> None:
    reg = _registry()
    denied = await reg.execute("secret", {"text": "x"}, ctx(verified=False), RUNTIME)
    assert denied.is_error and "verify_parent" in denied.content
    allowed = await reg.execute("secret", {"text": "x"}, ctx(verified=True), RUNTIME)
    assert not allowed.is_error
    staff = await reg.execute("staffy", {"text": "x"}, ctx(verified=True), RUNTIME)
    assert staff.is_error


async def test_module_restriction_and_fee_stubs() -> None:
    reg = build_registry()
    wrong = await reg.execute("book_visit", {}, ctx(), RUNTIME, module="fees")
    assert wrong.is_error and "Unknown tool" in wrong.content
    gated = await reg.execute("get_fee_status", {"student_ref": "x"}, ctx(), RUNTIME)
    assert gated.is_error and "verify_parent" in gated.content
    stub = await reg.execute(
        "verify_parent",
        {"student_name": "Ali", "class_or_roll": "5", "phone_last4": None},
        ctx(),
        RUNTIME,
    )
    assert stub.is_error and "handoff_to_human" in stub.content


async def test_execute_all_keeps_order() -> None:
    reg = _registry()
    out = await reg.execute_all(
        [("a", "echo", {"text": "one"}), ("b", "secret", {"text": "two"}), ("c", "echo", {})],
        ctx(),
        RUNTIME,
    )
    assert [o.tool_use_id for o in out] == ["a", "b", "c"]
    assert [o.is_error for o in out] == [False, True, True]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0300-1234567", "+923001234567"),
        ("+92 321 7654321", "+923217654321"),
        ("923001234567", "+923001234567"),
        ("0092 300 1234567", "+923001234567"),
        ("042 35751100", "+924235751100"),
        ("12345", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_pk_phone(raw: str | None, expected: str | None) -> None:
    assert normalize_pk_phone(raw) == expected


def test_manifest_shape() -> None:
    m = build_registry().manifest()
    names = [t["name"] for t in m["tools"]]
    assert names == sorted(names) and len(names) == 18
    book = next(t for t in m["tools"] if t["name"] == "book_visit")
    assert book["annotations"]["sideEffect"] == "write"
    assert book["annotations"]["readOnlyHint"] is False

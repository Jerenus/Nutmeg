from __future__ import annotations

import base64
import json

import pytest
from pydantic import ValidationError

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.product.operator_tokens import (
    OperatorCommandKind,
    OperatorSnapshotTokenCodec,
    OperatorSnapshotTokenError,
    OperatorSnapshotTokenPayloadV1,
)

KEY = b"operator-token-test-key-at-least-32-bytes"


def _payload(**updates: object) -> OperatorSnapshotTokenPayloadV1:
    values: dict[str, object] = {
        "task_snapshot_hash": "a" * 64,
        "work_item_id": "zucai:26116:snapshot:sale_wave:all",
        "command_kind": OperatorCommandKind.FREEZE_EVIDENCE,
        "dependency_revision_ids": ["rev-1", "rev-2"],
    }
    values.update(updates)
    return OperatorSnapshotTokenPayloadV1(**values)


def _verify(codec: OperatorSnapshotTokenCodec, token: str, **updates: object):
    values = {
        "expected_command_kind": OperatorCommandKind.FREEZE_EVIDENCE,
        "current_task_snapshot_hash": "a" * 64,
        "current_work_item_id": "zucai:26116:snapshot:sale_wave:all",
        "current_dependency_revision_ids": ["rev-1", "rev-2"],
    }
    values.update(updates)
    return codec.verify(token, **values)


def test_snapshot_token_round_trips_canonical_two_frame_wire_format() -> None:
    codec = OperatorSnapshotTokenCodec(KEY)

    token = codec.encode(_payload())

    assert token.count(".") == 1
    assert "=" not in token
    assert codec.decode(token) == _payload()
    assert _verify(codec, token) == _payload()


@pytest.mark.parametrize(
    "dependencies",
    [["rev-2", "rev-1"], ["rev-1", "rev-1"]],
)
def test_snapshot_payload_rejects_unsorted_or_duplicate_dependencies(
    dependencies: list[str],
) -> None:
    with pytest.raises(ValidationError):
        _payload(dependency_revision_ids=dependencies)


def test_snapshot_payload_rejects_unknown_command_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _payload(command_kind="automatic_bet")
    with pytest.raises(ValidationError):
        _payload(secret="not-allowed")


@pytest.mark.parametrize("part", [0, 1])
def test_one_byte_payload_or_signature_tampering_is_invalid(part: int) -> None:
    codec = OperatorSnapshotTokenCodec(KEY)
    frames = codec.encode(_payload()).split(".")
    frames[part] = ("A" if frames[part][0] != "A" else "B") + frames[part][1:]

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        codec.decode(".".join(frames))

    assert caught.value.code == "invalid_request"


def test_wrong_key_and_cross_command_replay_are_invalid() -> None:
    token = OperatorSnapshotTokenCodec(KEY).encode(_payload())

    with pytest.raises(OperatorSnapshotTokenError) as wrong_key:
        OperatorSnapshotTokenCodec(b"different-token-key-at-least-32-bytes").decode(token)
    with pytest.raises(OperatorSnapshotTokenError) as wrong_command:
        _verify(
            OperatorSnapshotTokenCodec(KEY),
            token,
            expected_command_kind=OperatorCommandKind.SELECT_CANDIDATE,
        )

    assert wrong_key.value.code == "invalid_request"
    assert wrong_command.value.code == "invalid_request"


@pytest.mark.parametrize(
    "updates",
    [
        {"current_task_snapshot_hash": "b" * 64},
        {"current_work_item_id": "other-work-item"},
        {"current_dependency_revision_ids": ["rev-1", "rev-3"]},
        {"current_dependency_revision_ids": ["rev-1", "rev-2", "rev-3"]},
    ],
)
def test_current_snapshot_or_dependency_change_is_stale(updates: dict[str, object]) -> None:
    codec = OperatorSnapshotTokenCodec(KEY)
    token = codec.encode(_payload())

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        _verify(codec, token, **updates)

    assert caught.value.code == "task_snapshot_changed"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda token: token + "=",
        lambda token: token + " ",
        lambda token: token.replace("-", "+") if "-" in token else "+" + token[1:],
        lambda token: token.replace("_", "/") if "_" in token else "/" + token[1:],
        lambda token: token + ".extra",
        lambda token: token.replace(".", "", 1),
    ],
)
def test_noncanonical_token_frames_are_rejected(mutate) -> None:
    codec = OperatorSnapshotTokenCodec(KEY)

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        codec.decode(mutate(codec.encode(_payload())))

    assert caught.value.code == "invalid_request"


def test_alternate_json_encoding_is_rejected_even_with_valid_signature() -> None:
    codec = OperatorSnapshotTokenCodec(KEY)
    document = _payload().model_dump(mode="json")
    alternate = json.dumps(document, indent=2).encode()
    canonical_segment = base64.urlsafe_b64encode(alternate).decode().rstrip("=")
    canonical_token = codec.encode(_payload())
    signature_segment = canonical_token.split(".", 1)[1]

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        codec.decode(f"{canonical_segment}.{signature_segment}")

    assert caught.value.code == "invalid_request"
    assert canonical_json(document).encode() != alternate


def test_token_errors_and_repr_never_expose_secret_or_payload() -> None:
    codec = OperatorSnapshotTokenCodec(KEY)
    token = codec.encode(_payload())

    with pytest.raises(OperatorSnapshotTokenError) as caught:
        codec.decode(token + "x")

    rendered = repr(codec) + repr(caught.value) + str(caught.value)
    assert KEY.decode() not in rendered
    assert "zucai:26116" not in rendered
    assert token not in rendered

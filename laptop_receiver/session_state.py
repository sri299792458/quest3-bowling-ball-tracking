from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


SESSION_STATE_SCHEMA_VERSION = "quest_bowling_session_state_v1"
SESSION_STATE_FILENAME = "session_state.json"

TRANSPORT_OFFLINE = "Offline"
TRANSPORT_DISCOVERING_LAPTOP = "DiscoveringLaptop"
TRANSPORT_CONNECTING = "Connecting"
TRANSPORT_STREAMING = "Streaming"
TRANSPORT_DEGRADED = "Degraded"
TRANSPORT_ENDING = "Ending"
TRANSPORT_ENDED = "Ended"
TRANSPORT_FAILED = "Failed"

LANE_UNKNOWN = "Unknown"
LANE_SELECTING_LEFT_FOUL_LINE = "SelectingLeftFoulLine"
LANE_SELECTING_RIGHT_FOUL_LINE = "SelectingRightFoulLine"
LANE_SELECTION_READY = "SelectionReady"
LANE_REQUEST_QUEUED = "RequestQueued"
LANE_SOLVING = "Solving"
LANE_CANDIDATE_RECEIVED = "CandidateReceived"
LANE_CONFIRMED = "Confirmed"
LANE_REJECTED = "Rejected"
LANE_FAILED = "Failed"
LANE_RELOCK_REQUIRED = "RelockRequired"

SHOT_DISABLED_UNTIL_LANE_CONFIRMED = "DisabledUntilLaneConfirmed"
SHOT_ARMED = "Armed"
SHOT_START_CANDIDATE = "StartCandidate"
SHOT_OPEN = "Open"
SHOT_END_CANDIDATE = "EndCandidate"
SHOT_WINDOW_COMPLETE = "WindowComplete"
SHOT_ANALYZING = "Analyzing"
SHOT_RESULT_READY = "ResultReady"
SHOT_RESULT_FAILED = "ResultFailed"

REPLAY_EMPTY = "Empty"
REPLAY_HAS_RESULTS = "HasResults"
REPLAY_PLAYING = "Playing"
REPLAY_COMPLETE = "Complete"
REPLAY_UNAVAILABLE = "Unavailable"


def now_unix_ms() -> int:
    return int(time.time() * 1000)


def session_state_path(session_dir: Path | str) -> Path:
    return Path(session_dir).expanduser().resolve() / SESSION_STATE_FILENAME


def default_session_state(
    session_dir: Path | str,
    *,
    session_id: str = "",
    stream_id: str = "",
) -> dict[str, Any]:
    root = Path(session_dir).expanduser().resolve()
    created_unix_ms = now_unix_ms()
    return {
        "schemaVersion": SESSION_STATE_SCHEMA_VERSION,
        "sessionId": session_id or "",
        "streamId": stream_id or "",
        "sessionDir": str(root),
        "createdUnixMs": created_unix_ms,
        "updatedUnixMs": created_unix_ms,
        "transport": {
            "state": TRANSPORT_CONNECTING,
            "mediaSessionStartSeen": False,
            "metadataSessionStartSeen": False,
            "codecConfigSeen": False,
            "sampleCount": 0,
            "keyframeCount": 0,
            "metadataMessageCount": 0,
            "outboundResultCount": 0,
            "firstPtsUs": None,
            "lastPtsUs": None,
            "lastFrameSeq": None,
        },
        "lane": {
            "state": LANE_UNKNOWN,
            "activeRequestId": "",
            "candidateRequestId": "",
            "confirmedRequestId": "",
            "candidateResultPath": "",
            "confirmedResultPath": "",
            "lastFailureReason": "",
        },
        "shot": {
            "state": SHOT_DISABLED_UNTIL_LANE_CONFIRMED,
            "activeLaneLockRequestId": "",
            "candidateStartFrameSeq": None,
            "openFrameSeqStart": None,
            "openFrameSeqEnd": None,
            "openWindowId": "",
            "latestWindowId": "",
            "completedWindowCount": 0,
            "processedWindowCount": 0,
            "latestResultPath": "",
            "lastFailureReason": "",
            "lastReason": "",
        },
        "replay": {
            "state": REPLAY_EMPTY,
            "successfulShotCount": 0,
            "latestWindowId": "",
        },
        "diagnostics": {
            "lastEvent": "session_state_created",
            "lastError": "",
        },
    }


def load_session_state(session_dir: Path | str) -> dict[str, Any]:
    path = session_state_path(session_dir)
    if not path.exists():
        return default_session_state(session_dir)

    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schemaVersion") != SESSION_STATE_SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported session_state schemaVersion {state.get('schemaVersion')!r}.")
    _ensure_sections(state)
    return state


def write_session_state(session_dir: Path | str, state: dict[str, Any]) -> Path:
    path = session_state_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updatedUnixMs"] = now_unix_ms()
    _ensure_sections(state)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path


def update_session_state(
    session_dir: Path | str,
    *,
    session_id: str | None = None,
    stream_id: str | None = None,
    transport: dict[str, Any] | None = None,
    lane: dict[str, Any] | None = None,
    shot: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = load_session_state(session_dir)
    if session_id is not None and session_id:
        state["sessionId"] = session_id
    if stream_id is not None and stream_id:
        state["streamId"] = stream_id

    for section_name, values in (
        ("transport", transport),
        ("lane", lane),
        ("shot", shot),
        ("replay", replay),
        ("diagnostics", diagnostics),
    ):
        if values:
            state.setdefault(section_name, {}).update(values)

    write_session_state(session_dir, state)
    return state


def mark_transport(
    session_dir: Path | str,
    state: str,
    *,
    session_id: str = "",
    stream_id: str = "",
    **fields: Any,
) -> dict[str, Any]:
    return update_session_state(
        session_dir,
        session_id=session_id,
        stream_id=stream_id,
        transport={"state": state, **fields},
        diagnostics={"lastEvent": f"transport:{state}"},
    )


def mark_lane(session_dir: Path | str, state: str, **fields: Any) -> dict[str, Any]:
    return update_session_state(
        session_dir,
        lane={"state": state, **fields},
        diagnostics={"lastEvent": f"lane:{state}"},
    )


def mark_shot(session_dir: Path | str, state: str, **fields: Any) -> dict[str, Any]:
    return update_session_state(
        session_dir,
        shot={"state": state, **fields},
        diagnostics={"lastEvent": f"shot:{state}"},
    )


def mark_replay(session_dir: Path | str, state: str, **fields: Any) -> dict[str, Any]:
    return update_session_state(
        session_dir,
        replay={"state": state, **fields},
        diagnostics={"lastEvent": f"replay:{state}"},
    )


def _ensure_sections(state: dict[str, Any]) -> None:
    state.setdefault("transport", {})
    state.setdefault("lane", {})
    state.setdefault("shot", {})
    state.setdefault("replay", {})
    state.setdefault("diagnostics", {})
    state["transport"].setdefault("state", TRANSPORT_CONNECTING)
    state["lane"].setdefault("state", LANE_UNKNOWN)
    state["shot"].setdefault("state", SHOT_DISABLED_UNTIL_LANE_CONFIRMED)
    state["shot"].setdefault("activeLaneLockRequestId", "")
    state["shot"].setdefault("candidateStartFrameSeq", None)
    state["shot"].setdefault("openFrameSeqStart", None)
    state["shot"].setdefault("openFrameSeqEnd", None)
    state["shot"].setdefault("openWindowId", "")
    state["shot"].setdefault("latestWindowId", "")
    state["shot"].setdefault("completedWindowCount", 0)
    state["shot"].setdefault("processedWindowCount", 0)
    state["shot"].setdefault("latestResultPath", "")
    state["shot"].setdefault("lastFailureReason", "")
    state["shot"].setdefault("lastReason", "")
    state["replay"].setdefault("state", REPLAY_EMPTY)

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SESSION_STATE_SCHEMA_VERSION = "quest_bowling_session_state_v1"
SESSION_STATE_FILENAME = "session_state.json"
SESSION_STATE_LOCK_FILENAME = ".session_state.lock"
STATE_FILE_RETRY_COUNT = 8
STATE_FILE_RETRY_DELAY_SECONDS = 0.025

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


def session_state_lock_path(session_dir: Path | str) -> Path:
    return Path(session_dir).expanduser().resolve() / SESSION_STATE_LOCK_FILENAME


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
            "sessionEndSeen": False,
            "lastFrameSeq": None,
            "lastFramePtsUs": None,
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
    with _session_state_lock(session_dir):
        return _load_session_state_unlocked(session_dir)


def _load_session_state_unlocked(session_dir: Path | str) -> dict[str, Any]:
    path = session_state_path(session_dir)
    if not path.exists():
        return default_session_state(session_dir)

    for attempt in range(STATE_FILE_RETRY_COUNT):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            break
        except PermissionError:
            if attempt + 1 >= STATE_FILE_RETRY_COUNT:
                raise
            _sleep_for_state_file_retry(attempt)

    if state.get("schemaVersion") != SESSION_STATE_SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported session_state schemaVersion {state.get('schemaVersion')!r}.")
    _ensure_sections(state)
    return state


def write_session_state(session_dir: Path | str, state: dict[str, Any]) -> Path:
    with _session_state_lock(session_dir):
        return _write_session_state_unlocked(session_dir, state)


def _write_session_state_unlocked(session_dir: Path | str, state: dict[str, Any]) -> Path:
    path = session_state_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updatedUnixMs"] = now_unix_ms()
    _ensure_sections(state)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    for attempt in range(STATE_FILE_RETRY_COUNT):
        try:
            tmp_path.replace(path)
            return path
        except PermissionError:
            if attempt + 1 >= STATE_FILE_RETRY_COUNT:
                raise
            _sleep_for_state_file_retry(attempt)
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
    with _session_state_lock(session_dir):
        state = _load_session_state_unlocked(session_dir)
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

        _write_session_state_unlocked(session_dir, state)
        return state


def increment_replay_successful_shot_count(session_dir: Path | str, *, latest_window_id: str) -> dict[str, Any]:
    with _session_state_lock(session_dir):
        state = _load_session_state_unlocked(session_dir)
        replay_state = state.setdefault("replay", {})
        replay_state["state"] = REPLAY_HAS_RESULTS
        replay_state["latestWindowId"] = str(latest_window_id)
        replay_state["successfulShotCount"] = int(replay_state.get("successfulShotCount") or 0) + 1
        diagnostics = state.setdefault("diagnostics", {})
        diagnostics["lastEvent"] = f"replay:{REPLAY_HAS_RESULTS}"
        _write_session_state_unlocked(session_dir, state)
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


def _sleep_for_state_file_retry(attempt: int) -> None:
    time.sleep(STATE_FILE_RETRY_DELAY_SECONDS * float(attempt + 1))


@contextmanager
def _session_state_lock(session_dir: Path | str) -> Iterator[None]:
    lock_path = session_state_lock_path(session_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _ensure_sections(state: dict[str, Any]) -> None:
    state.setdefault("transport", {})
    state.setdefault("lane", {})
    state.setdefault("shot", {})
    state.setdefault("replay", {})
    state.setdefault("diagnostics", {})
    state["transport"].setdefault("state", TRANSPORT_CONNECTING)
    state["transport"].setdefault("mediaSessionStartSeen", False)
    state["transport"].setdefault("metadataSessionStartSeen", False)
    state["transport"].setdefault("codecConfigSeen", False)
    state["transport"].setdefault("sessionEndSeen", False)
    state["transport"].setdefault("lastFrameSeq", None)
    state["transport"].setdefault("lastFramePtsUs", None)
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

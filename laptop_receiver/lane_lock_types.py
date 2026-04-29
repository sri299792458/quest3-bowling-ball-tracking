from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


@dataclass(frozen=True)
class Vector2:
    x: float
    y: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "Vector2":
        source = payload or {}
        return cls(
            x=_float(source.get("x")),
            y=_float(source.get("y")),
        )

    def to_dict(self) -> dict[str, float]:
        return {"x": float(self.x), "y": float(self.y)}


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "Vector3":
        source = payload or {}
        return cls(
            x=_float(source.get("x")),
            y=_float(source.get("y")),
            z=_float(source.get("z")),
        )

    def to_dict(self) -> dict[str, float]:
        return {"x": float(self.x), "y": float(self.y), "z": float(self.z)}


@dataclass(frozen=True)
class Quaternion:
    x: float
    y: float
    z: float
    w: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "Quaternion":
        source = payload or {}
        return cls(
            x=_float(source.get("x")),
            y=_float(source.get("y")),
            z=_float(source.get("z")),
            w=_float(source.get("w"), 1.0),
        )

    def to_dict(self) -> dict[str, float]:
        return {"x": float(self.x), "y": float(self.y), "z": float(self.z), "w": float(self.w)}


@dataclass(frozen=True)
class Pose3D:
    position: Vector3
    rotation: Quaternion

    @classmethod
    def from_position_rotation(
        cls,
        position_payload: Mapping[str, Any] | None,
        rotation_payload: Mapping[str, Any] | None,
    ) -> "Pose3D":
        return cls(
            position=Vector3.from_mapping(position_payload),
            rotation=Quaternion.from_mapping(rotation_payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position.to_dict(),
            "rotation": self.rotation.to_dict(),
        }


@dataclass(frozen=True)
class CameraIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    @classmethod
    def from_session_metadata(cls, session_metadata: Mapping[str, Any]) -> "CameraIntrinsics":
        width = _int(session_metadata.get("actualWidth") or session_metadata.get("requestedWidth"))
        height = _int(session_metadata.get("actualHeight") or session_metadata.get("requestedHeight"))
        sensor_width = _int(session_metadata.get("sensorWidth"), width)
        sensor_height = _int(session_metadata.get("sensorHeight"), height)
        fx = _float(session_metadata.get("fx"))
        fy = _float(session_metadata.get("fy"))
        cx = _float(session_metadata.get("cx"))
        cy = _float(session_metadata.get("cy"))

        if width > 0 and height > 0 and sensor_width > 0 and sensor_height > 0:
            scale_x = float(width) / float(sensor_width)
            scale_y = float(height) / float(sensor_height)
            max_scale = max(scale_x, scale_y)
            if max_scale > 0.0:
                crop_scale_x = scale_x / max_scale
                crop_scale_y = scale_y / max_scale
                crop_x = float(sensor_width) * (1.0 - crop_scale_x) * 0.5
                crop_y = float(sensor_height) * (1.0 - crop_scale_y) * 0.5
                crop_width = float(sensor_width) * crop_scale_x
                crop_height = float(sensor_height) * crop_scale_y
                if crop_width > 0.0 and crop_height > 0.0:
                    x_scale = float(width) / crop_width
                    y_scale = float(height) / crop_height
                    fx *= x_scale
                    fy *= y_scale
                    cx = (cx - crop_x) * x_scale
                    # Meta's passthrough intrinsics use a bottom-left viewport/sensor Y axis.
                    # Our decoded OpenCV frames use top-left image coordinates.
                    cy = float(height) - (cy - crop_y) * y_scale

        return cls(
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            width=width,
            height=height,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrameCameraState:
    frame_seq: int
    camera_timestamp_us: int
    pts_us: int
    width: int
    height: int
    camera_pose_world: Pose3D
    head_pose_world: Pose3D
    lane_lock_state: int

    @classmethod
    def from_frame_metadata(cls, payload: Mapping[str, Any]) -> "FrameCameraState":
        return cls(
            frame_seq=_int(payload.get("frameSeq")),
            camera_timestamp_us=_int(payload.get("cameraTimestampUs")),
            pts_us=_int(payload.get("ptsUs")),
            width=_int(payload.get("width")),
            height=_int(payload.get("height")),
            camera_pose_world=Pose3D.from_position_rotation(
                payload.get("cameraPosition"),
                payload.get("cameraRotation"),
            ),
            head_pose_world=Pose3D.from_position_rotation(
                payload.get("headPosition"),
                payload.get("headRotation"),
            ),
            lane_lock_state=_int(payload.get("laneLockState")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frameSeq": self.frame_seq,
            "cameraTimestampUs": self.camera_timestamp_us,
            "ptsUs": self.pts_us,
            "width": self.width,
            "height": self.height,
            "cameraPoseWorld": self.camera_pose_world.to_dict(),
            "headPoseWorld": self.head_pose_world.to_dict(),
            "laneLockState": self.lane_lock_state,
        }

@dataclass(frozen=True)
class LaneLockConfidenceBreakdown:
    edge_fit: float
    selection_agreement: float
    marking_agreement: float
    temporal_stability: float
    candidate_margin: float
    visible_extent: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "LaneLockConfidenceBreakdown":
        source = payload or {}
        return cls(
            edge_fit=_float(source.get("edgeFit")),
            selection_agreement=_float(source.get("selectionAgreement")),
            marking_agreement=_float(source.get("markingAgreement")),
            temporal_stability=_float(source.get("temporalStability")),
            candidate_margin=_float(source.get("candidateMargin")),
            visible_extent=_float(source.get("visibleExtent")),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "edgeFit": self.edge_fit,
            "selectionAgreement": self.selection_agreement,
            "markingAgreement": self.marking_agreement,
            "temporalStability": self.temporal_stability,
            "candidateMargin": self.candidate_margin,
            "visibleExtent": self.visible_extent,
        }


@dataclass(frozen=True)
class ReleaseCorridor:
    s_start_meters: float
    s_end_meters: float
    half_width_meters: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ReleaseCorridor":
        source = payload or {}
        return cls(
            s_start_meters=_float(source.get("sStartMeters")),
            s_end_meters=_float(source.get("sEndMeters")),
            half_width_meters=_float(source.get("halfWidthMeters")),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "sStartMeters": self.s_start_meters,
            "sEndMeters": self.s_end_meters,
            "halfWidthMeters": self.half_width_meters,
        }


@dataclass(frozen=True)
class ReprojectionMetrics:
    mean_error_px: float
    p95_error_px: float
    runner_up_margin: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ReprojectionMetrics":
        source = payload or {}
        return cls(
            mean_error_px=_float(source.get("meanErrorPx")),
            p95_error_px=_float(source.get("p95ErrorPx")),
            runner_up_margin=_float(source.get("runnerUpMargin")),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "meanErrorPx": self.mean_error_px,
            "p95ErrorPx": self.p95_error_px,
            "runnerUpMargin": self.runner_up_margin,
        }


@dataclass(frozen=True)
class SourceFrameRange:
    start: int
    end: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "SourceFrameRange":
        source = payload or {}
        return cls(
            start=_int(source.get("start")),
            end=_int(source.get("end")),
        )

    def to_dict(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}


@dataclass(frozen=True)
class LaneLockResult:
    schema_version: str
    session_id: str
    request_id: str
    success: bool
    failure_reason: str
    confidence: float
    confidence_breakdown: LaneLockConfidenceBreakdown
    lock_state: str
    requires_confirmation: bool
    user_confirmed: bool
    preview_frame_seq: int
    lane_origin_world: Vector3
    lane_rotation_world: Quaternion
    lane_width_meters: float
    lane_length_meters: float
    floor_plane_point_world: Vector3
    floor_plane_normal_world: Vector3
    visible_downlane_meters: float
    release_corridor: ReleaseCorridor
    reprojection_metrics: ReprojectionMetrics
    source_frame_range: SourceFrameRange

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LaneLockResult":
        schema_version = _str(payload.get("schemaVersion"))
        if schema_version != "lane_lock_result":
            raise ValueError(f"Unsupported lane-lock result schemaVersion {schema_version!r}.")
        return cls(
            schema_version=schema_version,
            session_id=_str(payload.get("sessionId")),
            request_id=_str(payload.get("requestId")),
            success=bool(payload.get("success")),
            failure_reason=_str(payload.get("failureReason")),
            confidence=_float(payload.get("confidence")),
            confidence_breakdown=LaneLockConfidenceBreakdown.from_dict(payload.get("confidenceBreakdown")),
            lock_state=_str(payload.get("lockState"), "candidate_ready"),
            requires_confirmation=bool(payload.get("requiresConfirmation", True)),
            user_confirmed=bool(payload.get("userConfirmed", False)),
            preview_frame_seq=_int(payload.get("previewFrameSeq")),
            lane_origin_world=Vector3.from_mapping(payload.get("laneOriginWorld")),
            lane_rotation_world=Quaternion.from_mapping(payload.get("laneRotationWorld")),
            lane_width_meters=_float(payload.get("laneWidthMeters")),
            lane_length_meters=_float(payload.get("laneLengthMeters")),
            floor_plane_point_world=Vector3.from_mapping(payload.get("floorPlanePointWorld")),
            floor_plane_normal_world=Vector3.from_mapping(payload.get("floorPlaneNormalWorld")),
            visible_downlane_meters=_float(payload.get("visibleDownlaneMeters")),
            release_corridor=ReleaseCorridor.from_dict(payload.get("releaseCorridor")),
            reprojection_metrics=ReprojectionMetrics.from_dict(payload.get("reprojectionMetrics")),
            source_frame_range=SourceFrameRange.from_dict(payload.get("sourceFrameRange")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sessionId": self.session_id,
            "requestId": self.request_id,
            "success": self.success,
            "failureReason": self.failure_reason,
            "confidence": self.confidence,
            "confidenceBreakdown": self.confidence_breakdown.to_dict(),
            "lockState": self.lock_state,
            "requiresConfirmation": self.requires_confirmation,
            "userConfirmed": self.user_confirmed,
            "previewFrameSeq": self.preview_frame_seq,
            "laneOriginWorld": self.lane_origin_world.to_dict(),
            "laneRotationWorld": self.lane_rotation_world.to_dict(),
            "laneWidthMeters": self.lane_width_meters,
            "laneLengthMeters": self.lane_length_meters,
            "floorPlanePointWorld": self.floor_plane_point_world.to_dict(),
            "floorPlaneNormalWorld": self.floor_plane_normal_world.to_dict(),
            "visibleDownlaneMeters": self.visible_downlane_meters,
            "releaseCorridor": self.release_corridor.to_dict(),
            "reprojectionMetrics": self.reprojection_metrics.to_dict(),
            "sourceFrameRange": self.source_frame_range.to_dict(),
        }


@dataclass(frozen=True)
class LanePoint:
    x_meters: float
    s_meters: float
    h_meters: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "LanePoint":
        source = payload or {}
        return cls(
            x_meters=_float(source.get("xMeters")),
            s_meters=_float(source.get("sMeters")),
            h_meters=_float(source.get("hMeters")),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "xMeters": self.x_meters,
            "sMeters": self.s_meters,
            "hMeters": self.h_meters,
        }


@dataclass(frozen=True)
class LaneSpaceBallPoint:
    schema_version: str
    session_id: str
    shot_id: str
    frame_seq: int
    camera_timestamp_us: int
    pts_us: int
    image_point_px: Vector2
    point_definition: str
    world_point: Vector3
    lane_point: LanePoint
    is_on_locked_lane: bool
    projection_confidence: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LaneSpaceBallPoint":
        schema_version = _str(payload.get("schemaVersion"))
        if schema_version != "lane_space_ball_point":
            raise ValueError(f"Unsupported lane-space ball point schemaVersion {schema_version!r}.")
        return cls(
            schema_version=schema_version,
            session_id=_str(payload.get("sessionId")),
            shot_id=_str(payload.get("shotId")),
            frame_seq=_int(payload.get("frameSeq")),
            camera_timestamp_us=_int(payload.get("cameraTimestampUs")),
            pts_us=_int(payload.get("ptsUs")),
            image_point_px=Vector2.from_mapping(payload.get("imagePointPx")),
            point_definition=_str(payload.get("pointDefinition")),
            world_point=Vector3.from_mapping(payload.get("worldPoint")),
            lane_point=LanePoint.from_dict(payload.get("lanePoint")),
            is_on_locked_lane=bool(payload.get("isOnLockedLane")),
            projection_confidence=_float(payload.get("projectionConfidence")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sessionId": self.session_id,
            "shotId": self.shot_id,
            "frameSeq": self.frame_seq,
            "cameraTimestampUs": self.camera_timestamp_us,
            "ptsUs": self.pts_us,
            "imagePointPx": self.image_point_px.to_dict(),
            "pointDefinition": self.point_definition,
            "worldPoint": self.world_point.to_dict(),
            "lanePoint": self.lane_point.to_dict(),
            "isOnLockedLane": self.is_on_locked_lane,
            "projectionConfidence": self.projection_confidence,
        }

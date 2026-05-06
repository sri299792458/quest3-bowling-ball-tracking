using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace QuestBowlingStandalone.QuestApp
{
    public sealed class StandaloneQuestLaneLockResultRenderer : MonoBehaviour
    {
        [Header("Result Source")]
        [SerializeField] private Transform visualizationRoot;

        [Header("Lane Shape")]
        [SerializeField] private bool renderVisibleDownlaneOnly = false;
        [SerializeField] private bool renderSurface = true;
        [SerializeField] private bool clearOnFailedLaneResult = true;
        [SerializeField] private float verticalOffsetMeters = 0.025f;
        [SerializeField] private float lineWidthMeters = 0.025f;
        [SerializeField] private float releaseLineWidthMeters = 0.02f;
        [SerializeField] private float minimumRenderLengthMeters = 1.0f;

        [Header("Colors")]
        [SerializeField] private Color laneSurfaceColor = new Color(0.0f, 0.9f, 0.35f, 0.18f);
        [SerializeField] private Color outlineColor = new Color(0.0f, 1.0f, 0.45f, 1.0f);
        [SerializeField] private Color foulLineColor = new Color(0.25f, 0.75f, 1.0f, 1.0f);
        [SerializeField] private Color centerLineColor = new Color(1.0f, 1.0f, 1.0f, 0.85f);
        [SerializeField] private Color releaseCorridorColor = new Color(1.0f, 0.78f, 0.12f, 1.0f);

        [Header("Diagnostics")]
        [SerializeField] private bool verboseLogging;

        private GameObject _surfaceObject;
        private MeshFilter _surfaceMeshFilter;
        private MeshRenderer _surfaceMeshRenderer;
        private Mesh _surfaceMesh;
        private LineRenderer _outlineRenderer;
        private LineRenderer _foulLineRenderer;
        private LineRenderer _centerLineRenderer;
        private LineRenderer _releaseCorridorRenderer;
        private Material _surfaceMaterial;
        private Material _outlineMaterial;
        private Material _foulLineMaterial;
        private Material _centerLineMaterial;
        private Material _releaseCorridorMaterial;

        public string LastStatus { get; private set; } = string.Empty;
        public bool HasLaneVisualization { get; private set; }

        private void Awake()
        {
            EnsureRenderObjects();
            ClearVisualization("lane_result_renderer_ready");
        }

        private void OnDestroy()
        {
            DestroyIfNeeded(_surfaceMaterial);
            DestroyIfNeeded(_outlineMaterial);
            DestroyIfNeeded(_foulLineMaterial);
            DestroyIfNeeded(_centerLineMaterial);
            DestroyIfNeeded(_releaseCorridorMaterial);
            DestroyIfNeeded(_surfaceMesh);
        }

        public void RenderLaneLockResult(StandaloneLaneLockResult result)
        {
            if (result == null)
            {
                ClearVisualization("lane_lock_result_missing");
                return;
            }

            if (!result.success)
            {
                if (clearOnFailedLaneResult)
                {
                    ClearVisualization(result.failureReason);
                }

                SetStatus("lane_lock_result_failed:" + (result.failureReason ?? string.Empty));
                return;
            }

            if (result.laneWidthMeters <= 0.0f || result.laneLengthMeters <= 0.0f)
            {
                ClearVisualization("lane_lock_result_invalid_dimensions");
                return;
            }

            EnsureRenderObjects();

            var laneLength = ComputeRenderLength(result);
            var halfWidth = Mathf.Max(0.01f, result.laneWidthMeters * 0.5f);
            var lift = Mathf.Max(0.0f, verticalOffsetMeters);

            var leftFoul = LaneWorldPoint(result, -halfWidth, 0.0f, lift);
            var rightFoul = LaneWorldPoint(result, halfWidth, 0.0f, lift);
            var leftFar = LaneWorldPoint(result, -halfWidth, laneLength, lift);
            var rightFar = LaneWorldPoint(result, halfWidth, laneLength, lift);
            var centerFoul = LaneWorldPoint(result, 0.0f, 0.0f, lift + 0.002f);
            var centerFar = LaneWorldPoint(result, 0.0f, laneLength, lift + 0.002f);

            UpdateSurface(leftFoul, rightFoul, leftFar, rightFar);
            UpdateLine(_outlineRenderer, new[] { leftFoul, rightFoul, rightFar, leftFar, leftFoul }, outlineColor, lineWidthMeters);
            UpdateLine(_foulLineRenderer, new[] { leftFoul, rightFoul }, foulLineColor, lineWidthMeters * 1.35f);
            UpdateLine(_centerLineRenderer, new[] { centerFoul, centerFar }, centerLineColor, Mathf.Max(0.008f, lineWidthMeters * 0.55f));
            UpdateReleaseCorridor(result, laneLength, lift + 0.004f);

            HasLaneVisualization = true;
            SetStatus($"lane_lock_visualized requestId={result.requestId} confidence={result.confidence:0.000}");
        }

        public void ClearVisualization(string reason)
        {
            HasLaneVisualization = false;

            if (_surfaceObject != null)
            {
                _surfaceObject.SetActive(false);
            }

            ClearLine(_outlineRenderer);
            ClearLine(_foulLineRenderer);
            ClearLine(_centerLineRenderer);
            ClearLine(_releaseCorridorRenderer);
            SetStatus(string.IsNullOrWhiteSpace(reason) ? "lane_visualization_cleared" : reason);
        }

        private void EnsureRenderObjects()
        {
            var parent = visualizationRoot != null ? visualizationRoot : transform;

            if (_surfaceObject == null)
            {
                _surfaceObject = new GameObject("StandaloneLaneLockSurface");
                _surfaceObject.transform.SetParent(parent, false);
                _surfaceMeshFilter = _surfaceObject.AddComponent<MeshFilter>();
                _surfaceMeshRenderer = _surfaceObject.AddComponent<MeshRenderer>();
                _surfaceMesh = new Mesh { name = "StandaloneLaneLockSurfaceMesh" };
                _surfaceMeshFilter.sharedMesh = _surfaceMesh;
            }

            if (_surfaceMaterial == null)
            {
                _surfaceMaterial = CreateColorMaterial("StandaloneLaneLockSurfaceMaterial", laneSurfaceColor, true);
            }

            _surfaceMaterial.color = laneSurfaceColor;
            _surfaceMeshRenderer.sharedMaterial = _surfaceMaterial;

            _outlineRenderer = EnsureLineRenderer(
                _outlineRenderer,
                "StandaloneLaneLockOutline",
                parent,
                ref _outlineMaterial,
                outlineColor);
            _foulLineRenderer = EnsureLineRenderer(
                _foulLineRenderer,
                "StandaloneLaneLockFoulLine",
                parent,
                ref _foulLineMaterial,
                foulLineColor);
            _centerLineRenderer = EnsureLineRenderer(
                _centerLineRenderer,
                "StandaloneLaneLockCenterLine",
                parent,
                ref _centerLineMaterial,
                centerLineColor);
            _releaseCorridorRenderer = EnsureLineRenderer(
                _releaseCorridorRenderer,
                "StandaloneLaneLockReleaseCorridor",
                parent,
                ref _releaseCorridorMaterial,
                releaseCorridorColor);
        }

        private LineRenderer EnsureLineRenderer(
            LineRenderer renderer,
            string objectName,
            Transform parent,
            ref Material material,
            Color color)
        {
            if (renderer == null)
            {
                var lineObject = new GameObject(objectName);
                lineObject.transform.SetParent(parent, false);
                renderer = lineObject.AddComponent<LineRenderer>();
                renderer.useWorldSpace = true;
                renderer.numCornerVertices = 4;
                renderer.numCapVertices = 4;
                renderer.textureMode = LineTextureMode.Stretch;
                renderer.loop = false;
            }

            if (material == null)
            {
                material = CreateColorMaterial(objectName + "Material", color, false);
            }

            material.color = color;
            renderer.sharedMaterial = material;
            renderer.startColor = color;
            renderer.endColor = color;
            return renderer;
        }

        private void UpdateSurface(Vector3 leftFoul, Vector3 rightFoul, Vector3 leftFar, Vector3 rightFar)
        {
            if (_surfaceObject == null || _surfaceMesh == null)
            {
                return;
            }

            _surfaceObject.SetActive(renderSurface);
            if (!renderSurface)
            {
                return;
            }

            _surfaceMesh.Clear();
            var meshTransform = _surfaceObject.transform;
            _surfaceMesh.vertices = new[]
            {
                meshTransform.InverseTransformPoint(leftFoul),
                meshTransform.InverseTransformPoint(rightFoul),
                meshTransform.InverseTransformPoint(leftFar),
                meshTransform.InverseTransformPoint(rightFar),
            };
            _surfaceMesh.triangles = new[] { 0, 2, 1, 1, 2, 3 };
            _surfaceMesh.RecalculateBounds();
        }

        private void UpdateReleaseCorridor(StandaloneLaneLockResult result, float laneLength, float lift)
        {
            if (result.releaseCorridor == null)
            {
                ClearLine(_releaseCorridorRenderer);
                return;
            }

            var sStart = Mathf.Clamp(result.releaseCorridor.sStartMeters, 0.0f, laneLength);
            var sEnd = Mathf.Clamp(result.releaseCorridor.sEndMeters, sStart, laneLength);
            var halfWidth = Mathf.Clamp(
                result.releaseCorridor.halfWidthMeters,
                0.01f,
                Mathf.Max(0.01f, result.laneWidthMeters * 0.5f));

            if (sEnd <= sStart + 0.01f)
            {
                ClearLine(_releaseCorridorRenderer);
                return;
            }

            var leftStart = LaneWorldPoint(result, -halfWidth, sStart, lift);
            var rightStart = LaneWorldPoint(result, halfWidth, sStart, lift);
            var rightEnd = LaneWorldPoint(result, halfWidth, sEnd, lift);
            var leftEnd = LaneWorldPoint(result, -halfWidth, sEnd, lift);
            UpdateLine(
                _releaseCorridorRenderer,
                new[] { leftStart, rightStart, rightEnd, leftEnd, leftStart },
                releaseCorridorColor,
                releaseLineWidthMeters);
        }

        private void UpdateLine(LineRenderer renderer, Vector3[] positions, Color color, float width)
        {
            if (renderer == null)
            {
                return;
            }

            renderer.enabled = positions != null && positions.Length >= 2;
            if (!renderer.enabled)
            {
                renderer.positionCount = 0;
                return;
            }

            var safeWidth = Mathf.Max(0.004f, width);
            renderer.startWidth = safeWidth;
            renderer.endWidth = safeWidth;
            renderer.startColor = color;
            renderer.endColor = color;
            if (renderer.sharedMaterial != null)
            {
                renderer.sharedMaterial.color = color;
            }

            renderer.positionCount = positions.Length;
            renderer.SetPositions(positions);
        }

        private void ClearLine(LineRenderer renderer)
        {
            if (renderer == null)
            {
                return;
            }

            renderer.positionCount = 0;
            renderer.enabled = false;
        }

        private float ComputeRenderLength(StandaloneLaneLockResult result)
        {
            var laneLength = Mathf.Max(minimumRenderLengthMeters, result.laneLengthMeters);
            if (renderVisibleDownlaneOnly && result.visibleDownlaneMeters > 0.0f)
            {
                laneLength = Mathf.Min(laneLength, Mathf.Max(minimumRenderLengthMeters, result.visibleDownlaneMeters));
            }

            return laneLength;
        }

        private Vector3 LaneWorldPoint(StandaloneLaneLockResult result, float xMeters, float sMeters, float liftMeters)
        {
            var rotation = NormalizeRotation(result.laneRotationWorld);
            return result.laneOriginWorld + rotation * new Vector3(xMeters, liftMeters, sMeters);
        }

        private Quaternion NormalizeRotation(Quaternion rotation)
        {
            var magnitude = Mathf.Sqrt(
                rotation.x * rotation.x
                + rotation.y * rotation.y
                + rotation.z * rotation.z
                + rotation.w * rotation.w);
            if (magnitude <= 0.0001f)
            {
                return Quaternion.identity;
            }

            return new Quaternion(
                rotation.x / magnitude,
                rotation.y / magnitude,
                rotation.z / magnitude,
                rotation.w / magnitude);
        }

        private Material CreateColorMaterial(string materialName, Color color, bool transparent)
        {
            var shader = transparent ? Shader.Find("Sprites/Default") : Shader.Find("Unlit/Color");
            if (shader == null)
            {
                shader = transparent ? Shader.Find("Unlit/Color") : Shader.Find("Sprites/Default");
            }

            var material = new Material(shader)
            {
                name = materialName,
                color = color,
            };

            if (transparent)
            {
                material.SetInt("_SrcBlend", (int)BlendMode.SrcAlpha);
                material.SetInt("_DstBlend", (int)BlendMode.OneMinusSrcAlpha);
                material.SetInt("_ZWrite", 0);
                material.SetInt("_Cull", (int)CullMode.Off);
                material.DisableKeyword("_ALPHATEST_ON");
                material.EnableKeyword("_ALPHABLEND_ON");
                material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
                material.renderQueue = (int)RenderQueue.Transparent;
            }

            return material;
        }

        private void DestroyIfNeeded(UnityEngine.Object target)
        {
            if (target == null)
            {
                return;
            }

            Destroy(target);
        }

        private void SetStatus(string status)
        {
            LastStatus = status ?? string.Empty;
            DebugLog(LastStatus);
        }

        private void DebugLog(string message)
        {
            if (!verboseLogging)
            {
                return;
            }

            Debug.Log($"[StandaloneQuestLaneLockResultRenderer] {message}");
        }
    }
}

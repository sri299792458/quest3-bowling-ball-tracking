// Copyright (c) Meta Platforms, Inc. and affiliates.

using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using Meta.XR;
using Meta.XR.Samples;
using Unity.Collections;
using Unity.InferenceEngine;
using UnityEngine;

namespace PassthroughCameraSamples.MultiObjectDetection
{
    [MetaCodeSample("PassthroughCameraApiSamples-MultiObjectDetection")]
    public class SentisInferenceRunManager : MonoBehaviour
    {
        private const string LogPrefix = "[SentisInferenceRunManager]";

        [SerializeField] private PassthroughCameraAccess m_cameraAccess;
        [SerializeField] private DetectionUiMenuManager m_uiMenuManager;
        [SerializeField] private DetectionManager m_detectionManager;

        [Header("Sentis Model config")]
        [SerializeField] private BackendType m_backend = BackendType.CPU;
        [SerializeField] private ModelAsset m_sentisModel;
        [SerializeField] private TextAsset m_labelsAsset;
        [SerializeField, Range(0, 1)] private float m_iouThreshold = 0.6f;
        [SerializeField, Range(0, 1)] private float m_scoreThreshold = 0.23f;

        [Header("UI display references")]
        [SerializeField] private SentisInferenceUiManager m_uiInference;

        [Header("[Editor Only] Convert to Sentis")]
        public ModelAsset OnnxModel;
        [Space(40)]

        private Worker m_engine;
        private Vector2Int m_inputSize;
        private readonly List<(int classId, Vector4 boundingBox)> m_detections = new List<(int classId, Vector4 boundingBox)>();
        private string[] m_labels;
        private string m_lastDebugStatus;
        private string m_lastDebugDetail;
        private float m_lastDebugLogTime;

        private void Awake()
        {
            var model = ModelLoader.Load(m_sentisModel);
            var inputShape = model.inputs[0].shape;
            m_inputSize = new Vector2Int(inputShape.Get(2), inputShape.Get(3));
            m_engine = new Worker(model, m_backend);
            m_labels = m_labelsAsset != null ? m_labelsAsset.text.Split('\n') : System.Array.Empty<string>();
            ReportDebug("model-ready", $"backend={m_backend} input={m_inputSize.x}x{m_inputSize.y} model={(m_sentisModel != null ? m_sentisModel.name : "null")}");
        }

        private IEnumerator Start()
        {
            m_uiInference.SetLabels(m_labelsAsset);
            ReportDebug("paused", "waiting for A or pinch to start inference");

            while (true)
            {
                while (m_uiMenuManager.IsPaused)
                {
                    ReportDebug("paused", "waiting for A or pinch to start inference");
                    yield return null;
                }
                yield return RunInference();
            }
        }

        private void OnDestroy()
        {
            m_engine.PeekOutput(0)?.CompleteAllPendingOperations();
            m_engine.PeekOutput(1)?.CompleteAllPendingOperations();
            m_engine.PeekOutput(2)?.CompleteAllPendingOperations();
            m_engine.Dispose();
        }

        internal static void PreloadModel(ModelAsset modelAsset)
        {
            // Load model
            var model = ModelLoader.Load(modelAsset);
            var inputShape = model.inputs[0].shape;

            // Create engine to run model
            using var worker = new Worker(model, BackendType.CPU);

            // Run inference with an empty image to load the model in the memory. The first inference blocks the main thread for a long time, so we're doing it on the app launch
            Texture tempTexture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            var textureTransform = new TextureTransform().SetDimensions(tempTexture.width, tempTexture.height, 3);
            using var input = new Tensor<float>(new TensorShape(1, 3, inputShape.Get(2), inputShape.Get(3)));
            TextureConverter.ToTensor(tempTexture, input, textureTransform);
            worker.Schedule(input);

            // Complete the inference immediately and destroy the temporary texture
            worker.PeekOutput(0).CompleteAllPendingOperations();
            worker.PeekOutput(1).CompleteAllPendingOperations();
            worker.PeekOutput(2).CompleteAllPendingOperations();
            Destroy(tempTexture);
        }

        private IEnumerator RunInference()
        {
            if (!m_cameraAccess.IsPlaying)
            {
                ReportDebug("camera-wait", "PassthroughCameraAccess.IsPlaying is false");
                yield break;
            }

            [DllImport("OVRPlugin", CallingConvention = CallingConvention.Cdecl)]
            static extern OVRPlugin.Result ovrp_GetNodePoseStateAtTime(double time, OVRPlugin.Node nodeId, out OVRPlugin.PoseStatef nodePoseState);
            if (!ovrp_GetNodePoseStateAtTime(OVRPlugin.GetTimeInSeconds(), OVRPlugin.Node.Head, out _).IsSuccess())
            {
                ReportDebug("pose-error", "OVR head pose not available for camera pose");
                Debug.Log("ovrp_GetNodePoseStateAtTime failed, which means 'm_cameraAccess.GetCameraPose()' is not reliable, skipping.");
                yield break;
            }

            Pose cachedCameraPose;
            try
            {
                cachedCameraPose = m_cameraAccess.GetCameraPose();
            }
            catch (System.Exception ex)
            {
                ReportException("get-camera-pose", ex);
                yield break;
            }

            // Update Capture data
            Texture targetTexture;
            try
            {
                targetTexture = m_cameraAccess.GetTexture();
            }
            catch (System.Exception ex)
            {
                ReportException("get-texture", ex);
                yield break;
            }

            if (targetTexture == null)
            {
                ReportDebug("camera-wait", "Passthrough texture is null");
                yield break;
            }

            // Convert the texture to a Tensor and schedule the inference
            var textureTransform = new TextureTransform().SetDimensions(targetTexture.width, targetTexture.height, 3);
            using var input = new Tensor<float>(new TensorShape(1, 3, m_inputSize.x, m_inputSize.y));
            try
            {
                TextureConverter.ToTensor(targetTexture, input, textureTransform);
            }
            catch (System.Exception ex)
            {
                ReportException("to-tensor", ex);
                yield break;
            }

            // Schedule all model layers
            try
            {
                m_engine.Schedule(input);
            }
            catch (System.Exception ex)
            {
                ReportException("schedule", ex);
                yield break;
            }

            // Get the results. ReadbackAndCloneAsync waits for all layers to complete before returning the result
            Tensor<float> boxesOutput;
            try
            {
                boxesOutput = m_engine.PeekOutput(0) as Tensor<float>;
            }
            catch (System.Exception ex)
            {
                ReportException("peek-boxes", ex);
                yield break;
            }

            if (boxesOutput == null)
            {
                ReportDebug("inference-error", "boxes output is null or has unexpected type");
                yield break;
            }

            var boxesAwaiter = boxesOutput.ReadbackAndCloneAsync().GetAwaiter();
            while (!boxesAwaiter.IsCompleted)
            {
                yield return null;
            }

            Tensor<float> boxes;
            try
            {
                boxes = boxesAwaiter.GetResult();
            }
            catch (System.Exception ex)
            {
                ReportException("readback-boxes", ex);
                yield break;
            }

            using (boxes)
            {
            if (boxes.shape[0] == 0)
            {
                ReportDebug("inference-empty", $"boxes=0 texture={targetTexture.width}x{targetTexture.height}");
                yield break;
            }

            Tensor<int> classIdsOutput;
            try
            {
                classIdsOutput = m_engine.PeekOutput(1) as Tensor<int>;
            }
            catch (System.Exception ex)
            {
                ReportException("peek-classids", ex);
                yield break;
            }

            if (classIdsOutput == null)
            {
                ReportDebug("inference-error", "classIDs output is null or has unexpected type");
                yield break;
            }

            var classIDsAwaiter = classIdsOutput.ReadbackAndCloneAsync().GetAwaiter();
            while (!classIDsAwaiter.IsCompleted)
            {
                yield return null;
            }

            Tensor<int> classIDs;
            try
            {
                classIDs = classIDsAwaiter.GetResult();
            }
            catch (System.Exception ex)
            {
                ReportException("readback-classids", ex);
                yield break;
            }

            using (classIDs)
            {
            if (classIDs.shape[0] == 0)
            {
                ReportDebug("inference-error", $"classIDs=0 boxes={boxes.shape[0]}");
                Debug.LogError("classIDs.shape[0] == 0");
                yield break;
            }

            Tensor<float> scoresOutput;
            try
            {
                scoresOutput = m_engine.PeekOutput(2) as Tensor<float>;
            }
            catch (System.Exception ex)
            {
                ReportException("peek-scores", ex);
                yield break;
            }

            if (scoresOutput == null)
            {
                ReportDebug("inference-error", "scores output is null or has unexpected type");
                yield break;
            }

            var scoresAwaiter = scoresOutput.ReadbackAndCloneAsync().GetAwaiter();
            while (!scoresAwaiter.IsCompleted)
            {
                yield return null;
            }

            Tensor<float> scores;
            try
            {
                scores = scoresAwaiter.GetResult();
            }
            catch (System.Exception ex)
            {
                ReportException("readback-scores", ex);
                yield break;
            }

            using (scores)
            {
            if (scores.shape[0] == 0)
            {
                ReportDebug("inference-error", $"scores=0 boxes={boxes.shape[0]} classIDs={classIDs.shape[0]}");
                Debug.LogError("scores.shape[0] == 0");
                yield break;
            }

            try
            {
                NonMaxSuppression(m_detections, boxes, classIDs, scores, m_iouThreshold, m_scoreThreshold);
            }
            catch (System.Exception ex)
            {
                ReportException("nms", ex);
                yield break;
            }

            if (m_detections.Count == 0)
            {
                ReportDebug("no-detections", $"boxes={boxes.shape[0]} classIDs={classIDs.shape[0]} scores={scores.shape[0]} kept=0 tex={targetTexture.width}x{targetTexture.height}");
                yield break;
            }

            // Checking if spatial anchor is tracked ensures bounding boxes are placed at correct world space positIons.
            if (!m_cameraAccess.IsPlaying || m_detectionManager.m_spatialAnchor == null || !m_detectionManager.m_spatialAnchor.IsTracked)
            {
                ReportDebug("anchor-wait", $"kept={m_detections.Count} labels={DescribeDetections()} anchor={DescribeAnchorState()}");
                yield break;
            }

            // Update UI.
            ReportDebug("drawing", $"kept={m_detections.Count} labels={DescribeDetections()} anchor={DescribeAnchorState()}");
            try
            {
                m_uiInference.DrawUIBoxes(m_detections, m_inputSize, cachedCameraPose);
            }
            catch (System.Exception ex)
            {
                ReportException("draw-ui", ex);
                yield break;
            }
            }
            }
            }
        }

        private string DescribeAnchorState()
        {
            if (m_detectionManager == null)
            {
                return "manager-null";
            }

            if (m_detectionManager.m_spatialAnchor == null)
            {
                return "missing";
            }

            return $"tracked={m_detectionManager.m_spatialAnchor.IsTracked} localized={m_detectionManager.m_spatialAnchor.Localized}";
        }

        private string DescribeDetections(int maxCount = 3)
        {
            if (m_detections.Count == 0)
            {
                return "none";
            }

            var count = Mathf.Min(maxCount, m_detections.Count);
            var labels = new string[count];
            for (var i = 0; i < count; i++)
            {
                labels[i] = GetLabel(m_detections[i].classId);
            }

            return string.Join(", ", labels);
        }

        private string GetLabel(int classId)
        {
            if (m_labels == null || classId < 0 || classId >= m_labels.Length)
            {
                return $"class:{classId}";
            }

            return m_labels[classId].Replace(" ", "_");
        }

        private void ReportDebug(string status, string detail)
        {
            m_uiMenuManager?.SetDebugStatus(status, detail);

            var shouldLog = status != m_lastDebugStatus || detail != m_lastDebugDetail || Time.unscaledTime - m_lastDebugLogTime > 2f;
            if (!shouldLog)
            {
                return;
            }

            m_lastDebugStatus = status;
            m_lastDebugDetail = detail;
            m_lastDebugLogTime = Time.unscaledTime;
            Debug.Log($"{LogPrefix} {status} :: {detail}");
        }

        private void ReportException(string step, System.Exception exception)
        {
            var detail = $"{step} :: {exception.GetType().Name}: {exception.Message}";
            ReportDebug("exception", detail);
            Debug.LogError($"{LogPrefix} {detail}");
            Debug.LogException(exception);
        }

        private static void NonMaxSuppression(List<(int classId, Vector4 boundingBox)> outDetections, Tensor<float> boxes, Tensor<int> classIDs, Tensor<float> scores, float iouThreshold, float scoreThreshold)
        {
            outDetections.Clear();

            // Filter by score threshold first
            List<int> filteredIndices = new List<int>();
            NativeArray<float>.ReadOnly scoresArray = scores.AsReadOnlyNativeArray();
            for (int i = 0; i < scoresArray.Length; i++)
            {
                if (scoresArray[i] >= scoreThreshold)
                {
                    filteredIndices.Add(i);
                }
            }

            if (filteredIndices.Count == 0)
            {
                return;
            }

            // Sort filtered indices by scores in descending order
            filteredIndices.Sort((a, b) => scoresArray[b].CompareTo(scoresArray[a]));

            // Apply NMS algorithm
            bool[] suppressed = new bool[filteredIndices.Count];
            for (int i = 0; i < filteredIndices.Count; i++)
            {
                if (suppressed[i])
                    continue;

                int idx = filteredIndices[i];

                // Add this detection to results
                outDetections.Add((classIDs[idx], GetBox(idx)));

                // Suppress overlapping boxes regardless of class
                for (int j = i + 1; j < filteredIndices.Count; j++)
                {
                    if (suppressed[j])
                        continue;

                    int jdx = filteredIndices[j];

                    float iou = CalculateIoU(GetBox(idx), GetBox(jdx));
                    if (iou > iouThreshold)
                    {
                        suppressed[j] = true;
                    }
                }
            }

            Vector4 GetBox(int i) => new Vector4(boxes[i, 0], boxes[i, 1], boxes[i, 2], boxes[i, 3]);
        }

        internal static float CalculateIoU(Vector4 boxA, Vector4 boxB)
        {
            // Boxes are in format (topLeftX, topLeftY, bottomRightX, bottomRightY)
            // Calculate intersection coordinates
            float x1 = Mathf.Max(boxA.x, boxB.x);
            float y1 = Mathf.Max(boxA.y, boxB.y);
            float x2 = Mathf.Min(boxA.z, boxB.z);
            float y2 = Mathf.Min(boxA.w, boxB.w);

            // Calculate intersection area
            float intersectionWidth = Mathf.Max(0, x2 - x1);
            float intersectionHeight = Mathf.Max(0, y2 - y1);
            float intersectionArea = intersectionWidth * intersectionHeight;

            // Calculate individual box areas
            float boxAArea = (boxA.z - boxA.x) * (boxA.w - boxA.y);
            float boxBArea = (boxB.z - boxB.x) * (boxB.w - boxB.y);

            // Calculate union area
            float unionArea = boxAArea + boxBArea - intersectionArea;

            // Return IoU (Intersection over Union)
            if (unionArea == 0)
                return 0;

            return intersectionArea / unionArea;
        }
    }
}

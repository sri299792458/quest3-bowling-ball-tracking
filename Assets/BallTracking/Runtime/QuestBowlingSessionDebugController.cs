using System;
using BallTracking.Runtime.Transport;
using UnityEngine;

namespace BallTracking.Runtime
{
    public sealed class QuestBowlingSessionDebugController : MonoBehaviour
    {
        [SerializeField] private QuestBowlingStreamClient streamClient;
        [SerializeField] private Transform laneReference;
        [SerializeField] private float laneWidthMeters = 1.0541f;
        [SerializeField] private float laneLengthMeters = 18.288f;
        [SerializeField] private bool sendCalibrationOnStart = true;
        [SerializeField] private bool verboseLogging = true;

        private string _currentShotId;
        private bool _shotActive;

        public void ConfigureForRuntime(QuestBowlingStreamClient client, Transform laneTransform)
        {
            streamClient = client;
            laneReference = laneTransform;
        }

        private void Start()
        {
            Debug.Log("[QuestBowlingSessionDebugController] Start");
            streamClient?.ShowLocalStatus("controller_ready", "X start | Y end | L-stick calibrate");
            if (sendCalibrationOnStart)
            {
                SendLaneCalibration();
            }
        }

        private void Update()
        {
            if (streamClient == null)
            {
                return;
            }

            var startPressed =
                OVRInput.GetDown(OVRInput.Button.Three, OVRInput.Controller.LTouch) ||
                OVRInput.GetDown(OVRInput.RawButton.X);
            if (startPressed)
            {
                StartShot();
            }

            var endPressed =
                OVRInput.GetDown(OVRInput.Button.Four, OVRInput.Controller.LTouch) ||
                OVRInput.GetDown(OVRInput.RawButton.Y);
            if (endPressed)
            {
                EndShot();
            }

            var calibratePressed =
                OVRInput.GetDown(OVRInput.Button.PrimaryThumbstick, OVRInput.Controller.LTouch) ||
                OVRInput.GetDown(OVRInput.RawButton.LThumbstick);
            if (calibratePressed)
            {
                SendLaneCalibration();
            }
        }

        public void SendLaneCalibration()
        {
            if (streamClient == null || laneReference == null)
            {
                return;
            }

            streamClient.SetLaneCalibration(
                new Pose(laneReference.position, laneReference.rotation),
                laneWidthMeters,
                laneLengthMeters);
            streamClient.ShowLocalStatus("local_calibration", "lane calibration updated");

            if (verboseLogging)
            {
                Debug.Log("[QuestBowlingSessionDebugController] Sent lane calibration.");
            }
        }

        public void StartShot()
        {
            if (_shotActive || streamClient == null)
            {
                return;
            }

            _currentShotId = $"shot_{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}";
            streamClient.SetShotId(_currentShotId);
            var sent = streamClient.SendShotMarker(BowlingShotMarkerType.ShotStarted);
            if (!sent)
            {
                streamClient.ShowLocalStatus("local_start_dropped", _currentShotId);
                return;
            }

            _shotActive = true;
            streamClient.ShowLocalStatus("local_start_sent", _currentShotId);

            if (verboseLogging)
            {
                Debug.Log($"[QuestBowlingSessionDebugController] Started shot {_currentShotId}.");
            }
        }

        public void EndShot()
        {
            if (!_shotActive || streamClient == null)
            {
                return;
            }

            var sent = streamClient.SendShotMarker(BowlingShotMarkerType.ShotEnded);
            if (!sent)
            {
                streamClient.ShowLocalStatus("local_end_dropped", _currentShotId);
                return;
            }

            _shotActive = false;
            streamClient.ShowLocalStatus("local_end_sent", _currentShotId);

            if (verboseLogging)
            {
                Debug.Log($"[QuestBowlingSessionDebugController] Ended shot {_currentShotId}.");
            }
        }
    }
}

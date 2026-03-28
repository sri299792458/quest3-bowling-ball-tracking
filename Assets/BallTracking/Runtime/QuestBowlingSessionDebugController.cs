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

            if (OVRInput.GetDown(OVRInput.Button.Three, OVRInput.Controller.LTouch))
            {
                StartShot();
            }

            if (OVRInput.GetDown(OVRInput.Button.Four, OVRInput.Controller.LTouch))
            {
                EndShot();
            }

            if (OVRInput.GetDown(OVRInput.Button.Start))
            {
                SendLaneCalibration();
            }

            if (OVRInput.GetDown(OVRInput.Button.PrimaryThumbstick, OVRInput.Controller.LTouch))
            {
                streamClient.SendShotMarker(BowlingShotMarkerType.TrackerReset);
                _shotActive = false;
                if (verboseLogging)
                {
                    Debug.Log("[QuestBowlingSessionDebugController] Sent tracker reset.");
                }
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
            streamClient.SendShotMarker(BowlingShotMarkerType.ShotStarted);
            _shotActive = true;

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

            streamClient.SendShotMarker(BowlingShotMarkerType.ShotEnded);
            _shotActive = false;

            if (verboseLogging)
            {
                Debug.Log($"[QuestBowlingSessionDebugController] Ended shot {_currentShotId}.");
            }
        }
    }
}

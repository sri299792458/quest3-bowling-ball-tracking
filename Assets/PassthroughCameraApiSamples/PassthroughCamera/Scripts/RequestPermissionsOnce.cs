// Copyright (c) Meta Platforms, Inc. and affiliates.

using UnityEngine;
using UnityEngine.SceneManagement;

namespace PassthroughCameraSamples
{
    internal static class RequestPermissionsOnce
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void AfterSceneLoad()
        {
            bool permissionsRequestedOnce = false;

            void TryRequestPermissions(Scene scene)
            {
                if (permissionsRequestedOnce || scene.name == "StartScene")
                {
                    return;
                }

                var missingPermissions = new System.Collections.Generic.List<OVRPermissionsRequester.Permission>(2);
                if (!OVRPermissionsRequester.IsPermissionGranted(OVRPermissionsRequester.Permission.Scene))
                {
                    missingPermissions.Add(OVRPermissionsRequester.Permission.Scene);
                }

                if (!OVRPermissionsRequester.IsPermissionGranted(OVRPermissionsRequester.Permission.PassthroughCameraAccess))
                {
                    missingPermissions.Add(OVRPermissionsRequester.Permission.PassthroughCameraAccess);
                }

                if (missingPermissions.Count == 0)
                {
                    permissionsRequestedOnce = true;
                    return;
                }

                permissionsRequestedOnce = true;
                OVRPermissionsRequester.Request(missingPermissions.ToArray());
            }

            SceneManager.sceneLoaded += (scene, _) => TryRequestPermissions(scene);
            TryRequestPermissions(SceneManager.GetActiveScene());
        }
    }
}

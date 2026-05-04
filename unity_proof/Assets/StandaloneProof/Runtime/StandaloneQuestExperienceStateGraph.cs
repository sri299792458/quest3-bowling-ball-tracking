namespace QuestBowlingStandalone.QuestApp
{
    public enum StandaloneQuestExperienceBlocker
    {
        None,
        ReviewOpen,
        ReplayPlaying,
        LaneUiMissing,
        LaneNotLocked,
        SessionNotActive,
        MediaNotReady,
        MetadataDisconnected,
        ResultsDisconnected,
        PipelineBusy,
    }

    public readonly struct StandaloneQuestExperienceStateInput
    {
        public StandaloneQuestExperienceStateInput(
            bool sessionActive,
            bool mediaReady,
            string mediaReason,
            bool metadataConnected,
            bool resultsConnected,
            bool pipelineReady,
            string pipelineReason,
            bool replayPlaying,
            bool reviewOpen,
            int successfulShotCount,
            bool laneCoordinatorPresent,
            StandaloneQuestLaneLockUiState laneState,
            string laneBlockerLabel)
        {
            SessionActive = sessionActive;
            MediaReady = mediaReady;
            MediaReason = mediaReason ?? string.Empty;
            MetadataConnected = metadataConnected;
            ResultsConnected = resultsConnected;
            PipelineReady = pipelineReady;
            PipelineReason = pipelineReason ?? string.Empty;
            ReplayPlaying = replayPlaying;
            ReviewOpen = reviewOpen;
            SuccessfulShotCount = successfulShotCount;
            LaneCoordinatorPresent = laneCoordinatorPresent;
            LaneState = laneState;
            LaneBlockerLabel = laneBlockerLabel ?? string.Empty;
        }

        public bool SessionActive { get; }
        public bool MediaReady { get; }
        public string MediaReason { get; }
        public bool MetadataConnected { get; }
        public bool ResultsConnected { get; }
        public bool PipelineReady { get; }
        public string PipelineReason { get; }
        public bool ReplayPlaying { get; }
        public bool ReviewOpen { get; }
        public int SuccessfulShotCount { get; }
        public bool LaneCoordinatorPresent { get; }
        public StandaloneQuestLaneLockUiState LaneState { get; }
        public string LaneBlockerLabel { get; }
    }

    public readonly struct StandaloneQuestExperienceState
    {
        public StandaloneQuestExperienceState(
            bool shotReady,
            string displayText,
            string reasonCode,
            string blockerLabel,
            StandaloneQuestExperienceBlocker blocker,
            bool hasSuccessfulShots,
            bool shotRailVisible,
            bool reviewButtonVisible)
        {
            ShotReady = shotReady;
            DisplayText = displayText ?? string.Empty;
            ReasonCode = reasonCode ?? string.Empty;
            BlockerLabel = blockerLabel ?? string.Empty;
            Blocker = blocker;
            HasSuccessfulShots = hasSuccessfulShots;
            ShotRailVisible = shotRailVisible;
            ReviewButtonVisible = reviewButtonVisible;
        }

        public bool ShotReady { get; }
        public string DisplayText { get; }
        public string ReasonCode { get; }
        public string BlockerLabel { get; }
        public StandaloneQuestExperienceBlocker Blocker { get; }
        public bool HasSuccessfulShots { get; }
        public bool ShotRailVisible { get; }
        public bool ReviewButtonVisible { get; }
    }

    public static class StandaloneQuestExperienceStateGraph
    {
        public const string ShotReadyText = "Shot Ready";
        public const string ShotNotReadyHeader = "Shot Not Ready";

        public static StandaloneQuestExperienceState Resolve(StandaloneQuestExperienceStateInput input)
        {
            var hasShots = input.SuccessfulShotCount > 0;

            if (!input.SessionActive)
            {
                return Block(
                    StandaloneQuestExperienceBlocker.SessionNotActive,
                    "session_not_active",
                    "Laptop Connecting",
                    hasShots,
                    showShotSurfaces: false);
            }

            if (!input.MediaReady)
            {
                return Block(
                    StandaloneQuestExperienceBlocker.MediaNotReady,
                    CleanReason(input.MediaReason, "media_not_ready"),
                    "Media Stream Not Ready",
                    hasShots,
                    showShotSurfaces: false);
            }

            if (!input.MetadataConnected)
            {
                return Block(
                    StandaloneQuestExperienceBlocker.MetadataDisconnected,
                    "metadata_not_connected",
                    "Metadata Reconnecting",
                    hasShots,
                    showShotSurfaces: false);
            }

            if (!input.ResultsConnected)
            {
                return Block(
                    StandaloneQuestExperienceBlocker.ResultsDisconnected,
                    "results_not_connected",
                    "Results Reconnecting",
                    hasShots,
                    showShotSurfaces: false);
            }

            if (input.ReviewOpen)
            {
                return Block(
                    StandaloneQuestExperienceBlocker.ReviewOpen,
                    "review_open",
                    "Review Open",
                    hasShots);
            }

            if (input.ReplayPlaying)
            {
                return Block(
                    StandaloneQuestExperienceBlocker.ReplayPlaying,
                    "replay_playing",
                    "Replay Playing",
                    hasShots);
            }

            if (!input.LaneCoordinatorPresent)
            {
                return Block(
                    StandaloneQuestExperienceBlocker.LaneUiMissing,
                    "lane_coordinator_missing",
                    "Lane UI Missing",
                    hasShots);
            }

            if (input.LaneState != StandaloneQuestLaneLockUiState.Locked)
            {
                var label = CleanLabel(input.LaneBlockerLabel, "Place Lane");
                return Block(
                    StandaloneQuestExperienceBlocker.LaneNotLocked,
                    "lane_not_locked:" + input.LaneState,
                    label,
                    hasShots);
            }

            if (!input.PipelineReady)
            {
                var pipelineReason = CleanReason(input.PipelineReason, "pipeline_busy");
                return Block(
                    StandaloneQuestExperienceBlocker.PipelineBusy,
                    pipelineReason,
                    PipelineBlockerLabel(pipelineReason),
                    hasShots);
            }

            return new StandaloneQuestExperienceState(
                shotReady: true,
                displayText: ShotReadyText,
                reasonCode: "shot_ready",
                blockerLabel: string.Empty,
                blocker: StandaloneQuestExperienceBlocker.None,
                hasSuccessfulShots: hasShots,
                shotRailVisible: hasShots,
                reviewButtonVisible: hasShots);
        }

        public static bool Validate(StandaloneQuestExperienceState state, out string error)
        {
            error = string.Empty;

            if (state.ShotReady && state.Blocker != StandaloneQuestExperienceBlocker.None)
            {
                error = "shot_ready_has_blocker";
                return false;
            }

            if (!state.ShotReady && state.Blocker == StandaloneQuestExperienceBlocker.None)
            {
                error = "blocked_state_missing_blocker";
                return false;
            }

            if (state.ShotReady && state.DisplayText != ShotReadyText)
            {
                error = "shot_ready_display_mismatch";
                return false;
            }

            if (!state.ShotReady && !state.DisplayText.StartsWith(ShotNotReadyHeader))
            {
                error = "blocked_state_display_mismatch";
                return false;
            }

            if (state.ShotRailVisible != state.ReviewButtonVisible)
            {
                error = "shot_surfaces_visibility_mismatch";
                return false;
            }

            if (!state.HasSuccessfulShots && (state.ShotRailVisible || state.ReviewButtonVisible))
            {
                error = "shot_surfaces_visible_without_shots";
                return false;
            }

            return true;
        }

        public static bool Validate(
            StandaloneQuestExperienceStateInput input,
            StandaloneQuestExperienceState state,
            out string error)
        {
            if (!Validate(state, out error))
            {
                return false;
            }

            if (!input.SessionActive && state.Blocker != StandaloneQuestExperienceBlocker.SessionNotActive)
            {
                error = "session_not_active_must_block_first";
                return false;
            }

            if (input.SessionActive && !input.MediaReady && state.Blocker != StandaloneQuestExperienceBlocker.MediaNotReady)
            {
                error = "media_not_ready_must_block_before_lane";
                return false;
            }

            if (input.SessionActive
                && input.MediaReady
                && !input.MetadataConnected
                && state.Blocker != StandaloneQuestExperienceBlocker.MetadataDisconnected)
            {
                error = "metadata_not_connected_must_block_before_lane";
                return false;
            }

            if (input.SessionActive
                && input.MediaReady
                && input.MetadataConnected
                && !input.ResultsConnected
                && state.Blocker != StandaloneQuestExperienceBlocker.ResultsDisconnected)
            {
                error = "results_not_connected_must_block_before_lane";
                return false;
            }

            return true;
        }

        private static StandaloneQuestExperienceState Block(
            StandaloneQuestExperienceBlocker blocker,
            string reasonCode,
            string blockerLabel,
            bool hasShots,
            bool showShotSurfaces = true)
        {
            var label = CleanLabel(blockerLabel, "Not Ready");
            var surfacesVisible = hasShots && showShotSurfaces;
            return new StandaloneQuestExperienceState(
                shotReady: false,
                displayText: ShotNotReadyHeader + "\n" + label,
                reasonCode: CleanReason(reasonCode, "not_ready"),
                blockerLabel: label,
                blocker: blocker,
                hasSuccessfulShots: hasShots,
                shotRailVisible: surfacesVisible,
                reviewButtonVisible: surfacesVisible);
        }

        private static string PipelineBlockerLabel(string reason)
        {
            var cleanReason = CleanReason(reason, "pipeline_busy");
            return cleanReason == "pipeline_status_missing" || cleanReason == "pipeline_starting"
                ? "Laptop Preparing"
                : "Processing Shot";
        }

        private static string CleanLabel(string value, string fallback)
        {
            return string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
        }

        private static string CleanReason(string value, string fallback)
        {
            return string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
        }
    }
}

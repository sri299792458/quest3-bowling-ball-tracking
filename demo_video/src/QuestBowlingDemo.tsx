import {
  AbsoluteFill,
  Audio,
  Img,
  Loop,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

const FPS = 30;
const accent = "#8fd6aa";
const blue = "#2f91c4";
const gold = "#d39a34";
const ink = "#f5f6f0";
const muted = "#a9b7af";
const paper = "#050706";
const panelBorder = "rgba(143,214,170,0.24)";

const seconds = (value: number) => Math.round(value * FPS);

const clips = {
  laneLock: "video/lane_lock_process.mp4",
  laneLockPinch: "video/lane_lock_pinch_hold.mp4",
  laneLockRelock: "video/lane_lock_relock_process_crop.mp4",
  liveThrow: "video/live_throw_replay.mp4",
  throwReplaySideBySide: "video/throw_replay_side_by_side.mp4",
  yoloSlide: "video/yolo_seed_slide_clip.mp4",
  samTrack: "video/sam2_detection_track_shot2.mp4",
  review: "video/review_panel_clip_trimmed.mp4",
  notReady: "video/not_ready_processing_clip.mp4",
} as const;

const narrationCues = [
  { start: 0.8, file: "01_title.mp3" },
  { start: 10.6, file: "02_motivation.mp3" },
  { start: 28.5, file: "03_lane_setup.mp3" },
  { start: 44.6, file: "04_pipeline.mp3" },
  { start: 68.6, file: "05_field_trials.mp3" },
  { start: 86.6, file: "06_session_review.mp3" },
  { start: 104.6, file: "07_limitation.mp3" },
  { start: 124.4, file: "08_acknowledgements.mp3" },
] as const;

const fade = (frame: number, duration = 18) =>
  interpolate(frame, [0, duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

const sceneFrame = (absoluteFrame: number, start: number) =>
  Math.max(0, absoluteFrame - start);

const VideoBox = ({
  src,
  trimStart = 0,
  label,
  loopDurationSeconds,
  fit = "cover",
  objectPosition = "center",
}: {
  src: string;
  trimStart?: number;
  label?: string;
  loopDurationSeconds?: number;
  fit?: "cover" | "contain";
  objectPosition?: string;
}) => (
  <div
    style={{
      position: "relative",
      overflow: "hidden",
      width: "100%",
      height: "100%",
      background: "#10130f",
    }}
  >
    {loopDurationSeconds ? (
      <Loop durationInFrames={seconds(loopDurationSeconds)}>
        <OffthreadVideo
          src={staticFile(src)}
          trimBefore={seconds(trimStart)}
          muted
          style={{ width: "100%", height: "100%", objectFit: fit, objectPosition }}
        />
      </Loop>
    ) : (
      <OffthreadVideo
        src={staticFile(src)}
        trimBefore={seconds(trimStart)}
        muted
        style={{ width: "100%", height: "100%", objectFit: fit, objectPosition }}
      />
    )}
    {label ? <div className="video-label">{label}</div> : null}
  </div>
);

const Eyebrow = ({ children }: { children: React.ReactNode }) => (
  <div
    style={{
      letterSpacing: 8,
      textTransform: "uppercase",
      color: accent,
      fontSize: 20,
      fontWeight: 600,
    }}
  >
    {children}
  </div>
);

const BigTitle = ({ children }: { children: React.ReactNode }) => (
  <div
    style={{
      color: ink,
      fontSize: 80,
      fontWeight: 800,
      lineHeight: 0.98,
      maxWidth: 950,
    }}
  >
    {children}
  </div>
);

const Caption = ({
  children,
  tone = "light",
}: {
  children: React.ReactNode;
  tone?: "dark" | "light";
}) => (
  <div
    style={{
      color: tone === "light" ? "rgba(245,246,240,0.9)" : "#15171b",
      fontSize: 34,
      lineHeight: 1.25,
      maxWidth: 980,
      textShadow: tone === "light" ? "0 2px 14px rgba(0,0,0,0.55)" : "none",
    }}
  >
    {children}
  </div>
);

const Pill = ({
  children,
  color = accent,
}: {
  children: React.ReactNode;
  color?: string;
}) => (
  <div
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 10,
      border: `1px solid ${color}`,
      color,
      padding: "10px 16px",
      borderRadius: 999,
      fontSize: 22,
      fontWeight: 700,
      background: "rgba(7,18,11,0.68)",
    }}
  >
    {children}
  </div>
);

const VideoPanel = ({
  src,
  aspectRatio = "16 / 9",
  objectPosition = "center",
}: {
  src: string;
  aspectRatio?: string;
  objectPosition?: string;
}) => (
  <div
    style={{
      position: "relative",
      overflow: "hidden",
      width: "100%",
      aspectRatio,
      alignSelf: "center",
      background: "#10130f",
      boxShadow: "0 28px 90px rgba(0, 0, 0, 0.42)",
      border: `1px solid ${panelBorder}`,
    }}
  >
    <VideoBox src={src} fit="cover" objectPosition={objectPosition} />
  </div>
);

const ImagePanel = ({
  src,
  className,
  objectPosition = "center",
}: {
  src: string;
  className?: string;
  objectPosition?: string;
}) => (
  <div className={className ?? "media-frame"}>
    <Img
      src={staticFile(src)}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        objectPosition,
      }}
    />
  </div>
);

const SceneShell = ({
  children,
  pad = "64px 76px",
}: {
  children: React.ReactNode;
  pad?: string;
}) => (
  <AbsoluteFill
    style={{
      background:
        "radial-gradient(circle at 72% 18%, rgba(31,95,61,0.24), transparent 34%), linear-gradient(135deg, #050706 0%, #08100b 50%, #10130f 100%)",
      padding: pad,
    }}
  >
    {children}
  </AbsoluteFill>
);

const TitleScene = () => {
  const frame = useCurrentFrame();
  const opacity = fade(frame);
  return (
    <AbsoluteFill style={{ background: "#050706", opacity }}>
      <Img
        src={staticFile("images/trajectory_hook_shot.png")}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          filter: "brightness(0.74) contrast(1.14) saturate(1.1)",
        }}
      />
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(90deg, rgba(5,7,6,0.92) 0%, rgba(5,7,6,0.66) 40%, rgba(5,7,6,0.14) 78%, rgba(5,7,6,0.02) 100%)",
        }}
      />
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(0deg, rgba(5,7,6,0.72) 0%, rgba(5,7,6,0.18) 42%, rgba(5,7,6,0) 100%)",
        }}
      />
      <AbsoluteFill style={{ padding: "78px 88px", justifyContent: "space-between" }}>
        <div
          style={{
            width: "fit-content",
            padding: "12px 18px",
            color: "#d7eee1",
            border: "1px solid rgba(215,238,225,0.28)",
            background: "rgba(5,12,8,0.42)",
            fontSize: 23,
            fontWeight: 720,
            letterSpacing: 6,
            textTransform: "uppercase",
          }}
        >
          CSCI 5629 Course Project
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            gap: 72,
          }}
        >
          <div style={{ maxWidth: 1030 }}>
            <div style={{ color: "white", fontSize: 118, fontWeight: 900, lineHeight: 0.9 }}>
              Quest 3 Bowling
              <br />
              Training Aid
            </div>
            <div
              style={{
                width: 210,
                height: 7,
                background: "#8fd6aa",
                marginTop: 34,
                marginBottom: 30,
              }}
            />
            <div style={{ color: "#d7eee1", fontSize: 42, lineHeight: 1.15, maxWidth: 910 }}>
              Live lane-anchored replay with YOLO, SAM2, and mixed-reality feedback.
            </div>
            <div style={{ color: "rgba(255,255,255,0.82)", fontSize: 28, marginTop: 26 }}>
              Cale Rudolph | Srinivas Kantha Reddy | Apurv Kushwaha
            </div>
          </div>
          <div
            style={{
              display: "grid",
              gap: 12,
              minWidth: 255,
              marginBottom: 12,
            }}
          >
            {["Lane lock", "Live tracking", "VR replay"].map((item) => (
              <div
                key={item}
                style={{
                  color: "white",
                  fontSize: 24,
                  fontWeight: 800,
                  letterSpacing: 3,
                  textTransform: "uppercase",
                  padding: "16px 18px",
                  background: "rgba(7,18,11,0.64)",
                  border: "1px solid rgba(143,214,170,0.34)",
                  textAlign: "center",
                }}
              >
                {item}
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const ProblemScene = () => (
  <SceneShell pad="58px 72px">
    <div style={{ display: "grid", gridTemplateColumns: "0.62fr 1.38fr", gap: 44, height: "100%" }}>
      <div style={{ alignSelf: "center" }}>
        <Eyebrow>Motivation</Eyebrow>
        <div style={{ height: 28 }} />
        <BigTitle>Scoreboards show pins. They do not show the shot.</BigTitle>
        <div style={{ height: 34 }} />
        <Caption>
          The goal was immediate coaching feedback: path, speed, breakpoint, entry board, and a replay
          anchored to the physical lane.
        </Caption>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateRows: "1fr auto",
          gap: 22,
          alignSelf: "center",
        }}
      >
        <VideoPanel
          src={clips.throwReplaySideBySide}
          aspectRatio="1920 / 860"
          objectPosition="top"
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
          {["Path", "Speed", "Breakpoint"].map((item) => (
            <div className="motivation-chip" key={item}>
              {item}
            </div>
          ))}
        </div>
      </div>
    </div>
  </SceneShell>
);

const UserFlowScene = () => {
  const steps = [
    "Laptop receiver starts",
    "Quest streams H.264 + metadata",
    "Bowler pinch-aligns the lane",
    "Pipeline publishes Shot Ready",
  ];
  return (
    <SceneShell pad="56px 70px">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "0.52fr 1.18fr",
          gap: 38,
          height: "100%",
          alignItems: "stretch",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <div>
            <Eyebrow>Interaction Flow</Eyebrow>
            <div style={{ height: 22 }} />
            <div style={{ color: ink, fontSize: 68, fontWeight: 850, lineHeight: 0.98 }}>
              Place the real lane before the system trusts a shot.
            </div>
            <div style={{ height: 26 }} />
            <Caption>
              The bowler aligns the lane in-headset, confirms it, and waits for a single clear
              readiness state.
            </Caption>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12 }}>
            {steps.map((step, index) => (
              <div className="step-card light-step-card" key={step}>
                <div className="step-index">{String(index + 1).padStart(2, "0")}</div>
                <div>{step}</div>
              </div>
            ))}
          </div>
        </div>
        <VideoPanel src={clips.laneLockRelock} />
      </div>
    </SceneShell>
  );
};

const ReviewScene = () => (
  <SceneShell pad="58px 72px">
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "0.48fr 1.26fr",
        gap: 40,
        height: "100%",
      }}
    >
      <div style={{ alignSelf: "center" }}>
        <Eyebrow>Session Review</Eyebrow>
        <div style={{ height: 24 }} />
        <div style={{ color: ink, fontSize: 72, fontWeight: 850, lineHeight: 1 }}>
          Every replay becomes a coaching record.
        </div>
        <div style={{ height: 28 }} />
        <Caption>
          The headset keeps previous shots available for comparison: speed, entry board, entry
          angle, and breakpoint.
        </Caption>
      </div>
      <VideoPanel src={clips.review} aspectRatio="1920 / 820" />
    </div>
  </SceneShell>
  );

const PipelineScene = () => {
  const items: Array<
    | { title: string; body: string; image: string; videoSrc?: never }
    | { title: string; body: string; videoSrc: string; videoLoopSeconds?: number; image?: never }
  > = [
    { title: "YOLO seed", body: "Find a lane-valid ball candidate.", image: "images/yolo_seed_detection_frame.png" },
    {
      title: "SAM2 camera track",
      body: "Propagate the mask through live frames.",
      videoSrc: clips.samTrack,
      videoLoopSeconds: 2.47,
    },
    { title: "Lane replay", body: "Project masks into lane space and return stats.", image: "images/trajectory_hook_shot.png" },
  ];
  return (
    <SceneShell pad="58px 70px">
      <Eyebrow>Vision Pipeline</Eyebrow>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: 22 }}>
        <BigTitle>YOLO starts it. SAM2 follows it. Geometry makes it useful.</BigTitle>
        <Pill>1280 x 960 live H.264</Pill>
      </div>
      <div style={{ height: 46 }} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 26 }}>
        {items.map((item, index) => (
          <div className="pipeline-card" key={item.title}>
            <div className="pipeline-number">{String(index + 1).padStart(2, "0")}</div>
            {item.videoSrc ? (
              <div className="pipeline-image">
                <VideoBox src={item.videoSrc} loopDurationSeconds={item.videoLoopSeconds} />
              </div>
            ) : (
              <Img src={staticFile(item.image ?? "")} className="pipeline-image" />
            )}
            <div style={{ fontSize: 32, fontWeight: 800, marginTop: 24 }}>{item.title}</div>
            <div style={{ color: muted, fontSize: 24, lineHeight: 1.25, marginTop: 10 }}>{item.body}</div>
          </div>
        ))}
      </div>
    </SceneShell>
  );
};

const ResultsScene = () => {
  const shots = [
    { label: "Straight", image: "images/trajectory_straight_shot.png", color: accent },
    { label: "Hook", image: "images/trajectory_hook_shot.png", color: blue },
    { label: "Gutter / edge", image: "images/trajectory_gutter_shot.png", color: gold },
  ];
  return (
    <SceneShell pad="58px 70px">
      <Eyebrow>Field Trials</Eyebrow>
      <div style={{ height: 20 }} />
      <BigTitle>Three shot shapes from the same live runtime.</BigTitle>
      <div style={{ height: 34 }} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 28 }}>
        {shots.map((shot) => (
          <div className="shot-card" key={shot.label}>
            <ImagePanel src={shot.image} className="shot-image-frame" />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 18 }}>
              <div style={{ fontSize: 31, fontWeight: 800, color: shot.color }}>{shot.label}</div>
              <div style={{ fontSize: 20, color: muted, letterSpacing: 4 }}>REPLAY OK</div>
            </div>
          </div>
        ))}
      </div>
    </SceneShell>
  );
};

const LimitationScene = () => (
  <SceneShell pad="58px 70px">
    <div style={{ display: "grid", gridTemplateColumns: "0.76fr 1.24fr", gap: 50, height: "100%" }}>
      <div style={{ alignSelf: "center" }}>
        <Eyebrow>Limitation</Eyebrow>
        <div style={{ height: 30 }} />
        <BigTitle>The final 15 feet amplify pixel error.</BigTitle>
        <div style={{ height: 28 }} />
        <Caption>
          In our six-shot session, the ball mask radius fell to about 9 px at 45-60 ft. A 3 px SAM2 drift
          can project to roughly 1.8-2.2 ft and about 2.2 boards.
        </Caption>
      </div>
      <div style={{ alignSelf: "center", display: "grid", gap: 20 }}>
        <div className="limitation-visual-grid">
          <div className="limitation-visual-card">
            <VideoBox
              src={clips.samTrack}
              label="SAM2 track: ball becomes tiny downlane"
              loopDurationSeconds={2.47}
            />
          </div>
          <div className="limitation-visual-card">
            <Img src={staticFile("images/trajectory_hook_shot.png")} className="limitation-image" />
            <div className="video-label">Small pixel error {"->"} large projection error</div>
          </div>
        </div>
        {[
          ["0-30 ft", "1 px maps to about 0.09 ft and 0.27 boards."],
          ["45-60 ft", "1 px maps to about 0.60 ft and 0.72 boards."],
          ["Current mitigation", "Lane-space smoothing helps, but pin-deck stats remain the least reliable."],
        ].map(([title, body]) => (
          <div className="limitation-card" key={title}>
            <div style={{ color: gold, fontSize: 24, fontWeight: 800 }}>{title}</div>
            <div style={{ color: ink, fontSize: 31, lineHeight: 1.22, marginTop: 6 }}>{body}</div>
          </div>
        ))}
      </div>
    </div>
  </SceneShell>
);

const ClosingScene = () => {
  const closingCards = [
    {
      title: "Resources & Thanks",
      color: accent,
      items: [
        "Meta Quest 3 passthrough and APIs.",
        "Unity, OpenCV, YOLO, and SAM2.",
        "Thanks to the instructor, classmates, and Goldy's Gameroom.",
      ],
    },
    {
      title: "Lessons Learned",
      color: gold,
      items: [
        "Real MR testing exposed issues desktop playback missed.",
        "Reliable capture and logs came before reliable tracking.",
        "Lane alignment mattered as much as ball detection.",
      ],
    },
    {
      title: "Future Work",
      color: blue,
      items: [
        "Improve SAM2 reliability in the final 15 feet.",
        "Sync replay with scoring / points-table data.",
        "Add multiplayer and session-sharing workflows.",
      ],
    },
  ];

  return (
    <SceneShell pad="62px 76px">
      <div className="closing-balanced-layout">
        <div className="closing-balanced-header">
          <Eyebrow>Closing</Eyebrow>
        </div>

        <div className="closing-balanced-main">
          <div className="closing-photo-card closing-photo-card-balanced">
            <Img src={staticFile("images/team_acknowledgements_photo.png")} className="closing-team-photo" />
            <div className="closing-photo-caption">Field testing at Goldy's Gameroom</div>
          </div>
          <div className="closing-balanced-cards">
            {closingCards.map((card) => (
              <div className="closing-card closing-balanced-card" key={card.title}>
                <div style={{ color: card.color, fontSize: 23, letterSpacing: 6, fontWeight: 900 }}>
                  {card.title.toUpperCase()}
                </div>
                <div style={{ height: 18 }} />
                {card.items.map((item) => (
                  <div className="closing-line" key={item}>
                    <span className="closing-dot" style={{ color: card.color }} />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </SceneShell>
  );
};

const NarrationTrack = () => (
  <>
    {narrationCues.map((cue) => (
      <Sequence key={cue.file} from={seconds(cue.start)}>
        <Audio src={staticFile(`audio/${cue.file}`)} volume={1} />
      </Sequence>
    ))}
  </>
);

export const QuestBowlingDemo = () => {
  const frame = useCurrentFrame();
  const scenes = [
    { start: 0, duration: 10, component: <TitleScene /> },
    { start: 10, duration: 18, component: <ProblemScene /> },
    { start: 28, duration: 16, component: <UserFlowScene /> },
    { start: 44, duration: 24, component: <PipelineScene /> },
    { start: 68, duration: 18, component: <ResultsScene /> },
    { start: 86, duration: 18, component: <ReviewScene /> },
    { start: 104, duration: 20, component: <LimitationScene /> },
    { start: 124, duration: 10, component: <ClosingScene /> },
  ];

  return (
    <AbsoluteFill style={{ background: paper }}>
      {scenes.map((scene) => (
        <Sequence
          key={scene.start}
          from={seconds(scene.start)}
          durationInFrames={seconds(scene.duration)}
        >
          <div style={{ opacity: fade(sceneFrame(frame, seconds(scene.start)), 14) }}>
            {scene.component}
          </div>
        </Sequence>
      ))}
      <NarrationTrack />
    </AbsoluteFill>
  );
};

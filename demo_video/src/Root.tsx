import "./index.css";
import { Composition } from "remotion";
import { QuestBowlingDemo } from "./QuestBowlingDemo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="QuestBowlingDemo"
        component={QuestBowlingDemo}
        durationInFrames={4020}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};

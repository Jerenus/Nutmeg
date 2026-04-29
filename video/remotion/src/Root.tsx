import React from 'react';
import {AbsoluteFill, Sequence, useVideoConfig} from 'remotion';
import {CaptionTrack} from './components/CaptionTrack';
import {Disclaimer} from './components/Disclaimer';
import {MoodShotLayer} from './components/MoodShotLayer';
import {OpeningHook} from './components/OpeningHook';
import {PitchMap} from './components/PitchMap';
import type {TimelineProps} from './schema';
import {fontStack, palette} from './styles';

export const FootballExplainerV2: React.FC<TimelineProps> = (props) => {
  const {fps} = useVideoConfig();
  const firstBeat = props.tacticalBeats[0];
  const secondBeat = props.tacticalBeats[1] ?? props.tacticalBeats[0];
  const firstMood = props.moodShots[0]?.local_video_path;
  const riskMood = props.moodShots[1]?.local_video_path;
  const closingMood = props.moodShots[2]?.local_video_path;
  return (
    <AbsoluteFill style={{background: palette.navy, color: palette.white, fontFamily: fontStack}}>
      <Sequence from={0} durationInFrames={8 * fps}>
        <MoodShotLayer src={firstMood} />
        <OpeningHook hook={props.selectedHook} />
      </Sequence>
      {firstBeat ? (
        <Sequence from={8 * fps} durationInFrames={17 * fps}>
          <PitchMap beat={firstBeat} />
        </Sequence>
      ) : null}
      {secondBeat ? (
        <Sequence from={25 * fps} durationInFrames={15 * fps}>
          <PitchMap beat={secondBeat} />
        </Sequence>
      ) : null}
      <Sequence from={40 * fps} durationInFrames={12 * fps}>
        <MoodShotLayer src={riskMood} />
        <CaptionTrack text={props.mainContradiction} />
      </Sequence>
      <Sequence from={52 * fps} durationInFrames={8 * fps}>
        <MoodShotLayer src={closingMood} />
        <CaptionTrack text="重点看开局节奏、临场首发和第一粒进球。" />
        <Disclaimer />
      </Sequence>
    </AbsoluteFill>
  );
};

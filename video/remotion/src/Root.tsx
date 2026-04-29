import React from 'react';
import {AbsoluteFill, Sequence, useVideoConfig} from 'remotion';
import {CaptionTrack} from './components/CaptionTrack';
import {Disclaimer} from './components/Disclaimer';
import {MoodShotLayer} from './components/MoodShotLayer';
import {PitchMap} from './components/PitchMap';
import {ScreenCard} from './components/ScreenCard';
import type {TimelineProps} from './schema';
import {fontStack, palette} from './styles';

export const FootballExplainerV2: React.FC<TimelineProps> = (props) => {
  const {fps} = useVideoConfig();
  const firstBeat = props.tacticalBeats[0];
  const secondBeat = props.tacticalBeats[1] ?? props.tacticalBeats[0];
  const firstMood = props.moodShots[0]?.local_video_path;
  const riskMood = props.moodShots[1]?.local_video_path;
  const closingMood = props.moodShots[2]?.local_video_path;
  const segment = (segmentId: string) =>
    props.narrativeSegments.find((item) => item.segment_id === segmentId);
  const sequence = (
    segmentId: string,
    render: (item: TimelineProps['narrativeSegments'][number]) => React.ReactNode,
  ) => {
    const item = segment(segmentId);
    if (!item) {
      return null;
    }
    return (
      <Sequence
        key={item.segment_id}
        from={Math.round(item.start_seconds * fps)}
        durationInFrames={Math.round((item.end_seconds - item.start_seconds) * fps)}
      >
        {render(item)}
      </Sequence>
    );
  };
  return (
    <AbsoluteFill style={{background: palette.navy, color: palette.white, fontFamily: fontStack}}>
      {sequence('hook', (item) => (
        <>
          <MoodShotLayer src={firstMood} />
          <ScreenCard text={item.screen_card_text} eyebrow="一分钟赛前变量" />
          <CaptionTrack text={item.subtitle_text} />
        </>
      ))}
      {firstBeat
        ? sequence('variable', (item) => (
            <>
              <PitchMap beat={firstBeat} />
              <ScreenCard text={item.screen_card_text} eyebrow="01" />
              <CaptionTrack text={item.subtitle_text} />
            </>
          ))
        : null}
      {firstBeat
        ? sequence('why', (item) => (
            <>
              <PitchMap beat={firstBeat} />
              <ScreenCard text={item.screen_card_text} eyebrow="为什么重要" />
              <CaptionTrack text={item.subtitle_text} />
            </>
          ))
        : null}
      {secondBeat
        ? sequence('counter', (item) => (
            <>
              <PitchMap beat={secondBeat} />
              <ScreenCard text={item.screen_card_text} eyebrow="反制路径" />
              <CaptionTrack text={item.subtitle_text} />
            </>
          ))
        : null}
      {sequence('risk', (item) => (
        <>
          <MoodShotLayer src={riskMood} />
          <ScreenCard text={item.screen_card_text} eyebrow="临场信号" />
          <CaptionTrack text={item.subtitle_text} />
        </>
      ))}
      {sequence('closing', (item) => (
        <>
          <MoodShotLayer src={closingMood} />
          <ScreenCard text={item.screen_card_text} eyebrow="最后带走" />
          <CaptionTrack text={item.subtitle_text} />
          <Disclaimer />
        </>
      ))}
    </AbsoluteFill>
  );
};

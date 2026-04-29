import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {FootballExplainerV2} from './Root';
import {TimelineSchema} from './schema';

const defaultProps = {
  compositionId: 'FootballExplainerV2',
  fps: 30,
  width: 1080,
  height: 1920,
  durationSeconds: 60,
  selectedHook: '表面看是主场优势，其实关键是压迫会不会断档。',
  mainContradiction: '巴黎压迫持续性 vs 拜仁支点回撤后的肋部冲刺。',
  voiceoverScript: '这场表面看是主场优势，其实真正决定比赛的是压迫会不会断档。',
  tacticalBeats: [],
  moodShots: [],
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="FootballExplainerV2"
    component={FootballExplainerV2}
    durationInFrames={1800}
    fps={30}
    width={1080}
    height={1920}
    schema={TimelineSchema}
    defaultProps={defaultProps}
  />
);

registerRoot(RemotionRoot);

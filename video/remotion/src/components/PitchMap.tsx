import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import type {TimelineProps} from '../schema';
import {palette} from '../styles';

type Beat = TimelineProps['tacticalBeats'][number];

export const PitchMap: React.FC<{beat: Beat}> = ({beat}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, 45], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 80, top: 260, bottom: 250}}>
      <div style={{fontSize: 48, fontWeight: 900, color: palette.gold}}>{beat.title}</div>
      <div style={{marginTop: 18, fontSize: 34, lineHeight: 1.25, color: palette.white}}>
        {beat.explanation}
      </div>
      <svg
        viewBox="0 0 100 100"
        style={{
          marginTop: 40,
          width: '100%',
          height: 920,
          background: palette.grass,
          borderRadius: 32,
        }}
      >
        <rect
          x="5"
          y="5"
          width="90"
          height="90"
          fill="none"
          stroke={palette.pitchLine}
          strokeWidth="1.2"
        />
        <line x1="5" y1="50" x2="95" y2="50" stroke={palette.pitchLine} strokeWidth="1" />
        <circle cx="50" cy="50" r="9" fill="none" stroke={palette.pitchLine} strokeWidth="1" />
        {beat.arrows.map((arrow, index) => {
          const x2 = arrow.from[0] + (arrow.to[0] - arrow.from[0]) * progress;
          const y2 = arrow.from[1] + (arrow.to[1] - arrow.from[1]) * progress;
          return (
            <line
              key={index}
              x1={arrow.from[0]}
              y1={arrow.from[1]}
              x2={x2}
              y2={y2}
              stroke={arrow.kind === 'press' ? palette.red : palette.cyan}
              strokeWidth="2.2"
              strokeLinecap="round"
            />
          );
        })}
      </svg>
    </div>
  );
};

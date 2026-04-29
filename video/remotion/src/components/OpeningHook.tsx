import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {palette} from '../styles';

export const OpeningHook: React.FC<{hook: string}> = ({hook}) => {
  const frame = useCurrentFrame();
  const y = interpolate(frame, [0, 18], [36, 0], {extrapolateRight: 'clamp'});
  return (
    <div style={{padding: 76, transform: `translateY(${y}px)`}}>
      <div style={{fontSize: 42, color: palette.gold, fontWeight: 900}}>一分钟赛前变量</div>
      <div style={{marginTop: 34, fontSize: 76, lineHeight: 1.1, fontWeight: 950}}>
        {hook}
      </div>
    </div>
  );
};

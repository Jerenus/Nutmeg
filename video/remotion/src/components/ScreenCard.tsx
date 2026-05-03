import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {douyinSafeLayout} from '../safeLayout';
import {palette} from '../styles';

export const ScreenCard: React.FC<{text: string; eyebrow?: string}> = ({text, eyebrow}) => {
  const frame = useCurrentFrame();
  const y = interpolate(frame, [0, 18], [18, 0], {extrapolateRight: 'clamp'});
  const opacity = interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div
      style={{
        position: 'absolute',
        left: douyinSafeLayout.left,
        right: douyinSafeLayout.rightReserve,
        top: douyinSafeLayout.screenCardTop,
        padding: '30px 34px',
        borderRadius: 30,
        background: 'linear-gradient(135deg, rgba(7,17,31,0.88), rgba(16,59,82,0.7))',
        border: '1px solid rgba(246,210,122,0.42)',
        boxShadow: '0 22px 70px rgba(0,0,0,0.34)',
        transform: `translateY(${y}px)`,
        opacity,
      }}
    >
      {eyebrow ? (
        <div style={{fontSize: 28, fontWeight: 900, letterSpacing: 2, color: palette.gold}}>
          {eyebrow}
        </div>
      ) : null}
      <div style={{marginTop: eyebrow ? 14 : 0, fontSize: 58, lineHeight: 1.08, fontWeight: 950}}>
        {text}
      </div>
    </div>
  );
};

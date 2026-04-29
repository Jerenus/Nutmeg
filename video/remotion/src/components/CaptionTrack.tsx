import React from 'react';

export const CaptionTrack: React.FC<{text: string}> = ({text}) => (
  <div
    style={{
      position: 'absolute',
      left: 64,
      right: 64,
      bottom: 120,
      fontSize: 42,
      lineHeight: 1.25,
      fontWeight: 800,
      color: 'white',
      textShadow: '0 4px 18px rgba(0,0,0,0.9)',
    }}
  >
    {text}
  </div>
);

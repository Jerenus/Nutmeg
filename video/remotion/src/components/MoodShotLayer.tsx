import React from 'react';
import {AbsoluteFill, OffthreadVideo} from 'remotion';

export const MoodShotLayer: React.FC<{src?: string | null}> = ({src}) => {
  if (!src) {
    return <AbsoluteFill style={{background: 'linear-gradient(145deg, #07111f, #103b52)'}} />;
  }
  return <OffthreadVideo src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} muted />;
};

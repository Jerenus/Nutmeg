import React from 'react';
import {AbsoluteFill, OffthreadVideo, staticFile} from 'remotion';

export const MoodShotLayer: React.FC<{src?: string | null}> = ({src}) => {
  if (!src) {
    return <AbsoluteFill style={{background: 'linear-gradient(145deg, #07111f, #103b52)'}} />;
  }
  const videoSrc = src.startsWith('http://') || src.startsWith('https://') ? src : staticFile(src);
  return (
    <OffthreadVideo
      src={videoSrc}
      style={{width: '100%', height: '100%', objectFit: 'cover'}}
      muted
    />
  );
};

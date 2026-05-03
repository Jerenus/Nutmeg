import React from 'react';
import {douyinSafeLayout} from '../safeLayout';

export const CaptionTrack: React.FC<{text: string}> = ({text}) => (
  <div
    style={{
      position: 'absolute',
      left: douyinSafeLayout.left,
      right: douyinSafeLayout.rightReserve,
      bottom: douyinSafeLayout.captionBottom,
      fontSize: douyinSafeLayout.captionFontSize,
      lineHeight: 1.25,
      fontWeight: 800,
      color: 'white',
      textShadow: '0 4px 18px rgba(0,0,0,0.9)',
    }}
  >
    {text}
  </div>
);

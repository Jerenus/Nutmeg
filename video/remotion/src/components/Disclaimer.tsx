import React from 'react';
import {douyinSafeLayout} from '../safeLayout';

export const Disclaimer: React.FC = () => (
  <div
    style={{
      position: 'absolute',
      left: douyinSafeLayout.left,
      right: douyinSafeLayout.rightReserve,
      bottom: douyinSafeLayout.disclaimerBottom,
      fontSize: douyinSafeLayout.disclaimerFontSize,
      color: 'rgba(255,255,255,0.78)',
    }}
  >
    赛前数据观察，不构成任何投注建议
  </div>
);

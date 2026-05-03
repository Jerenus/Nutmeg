# Douyin Safe Video Layout Design

## Context

Vertical football analysis videos are published to Douyin. Douyin overlays UI on the bottom and right side: author/caption/music components near the lower screen, action buttons on the right, and app chrome near the top. Current Remotion captions use `bottom: 120` and the disclaimer uses `bottom: 64`, so important text can be covered after upload.

## Decision

Create a fixed Douyin-safe layout for Remotion football videos:

- Keep critical captions out of the bottom app overlay by moving captions to the middle-lower safe zone.
- Reserve right-side space for Douyin action buttons by reducing text width on the right.
- Move the disclaimer out of the bottom strip and into the same safe text column as captions.
- Slightly reduce screen-card width and shift it down from the app top chrome.
- Keep generated Seedance footage unchanged; this is a Remotion layout-only rerender.

## Safe Zone Values

For 1080x1920 output:

- Left margin: 72px
- Right reserved UI area: 220px
- Top safe margin: 150px
- Caption bottom: 560px
- Disclaimer bottom: 500px
- Caption max lines: 2 visually; source text remains unchanged. Values were raised after QC simulation showed the first pass was still too close to the bottom overlay.

## Verification

- Unit/static regression test checks Remotion safe-layout constants and component usage.
- TypeScript typecheck must pass.
- Render 周三009 v7 with existing mood clips and v6 audio.
- ffprobe + ffmpeg decode verify final MP4.
- QC contact sheet samples frames and visually confirms bottom/right app overlay zones no longer cover subtitles or key cards.

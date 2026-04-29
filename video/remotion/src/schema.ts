import {z} from 'zod';

export const TacticalBeatSchema = z.object({
  beat_id: z.string(),
  start_seconds: z.number(),
  end_seconds: z.number(),
  title: z.string(),
  explanation: z.string(),
  home_shape: z.array(z.string()),
  away_shape: z.array(z.string()),
  arrows: z.array(
    z.object({
      from: z.tuple([z.number(), z.number()]),
      to: z.tuple([z.number(), z.number()]),
      kind: z.string(),
    }),
  ),
});

export const MoodShotSchema = z.object({
  task_key: z.string(),
  prompt: z.string(),
  duration: z.number(),
  placement_start_seconds: z.number(),
  placement_end_seconds: z.number(),
  quality_constraints: z.array(z.string()),
  provider_task_id: z.string().nullable().optional(),
  local_video_path: z.string().nullable().optional(),
  status: z.string().optional(),
});

export const NarrativeSegmentSchema = z.object({
  segment_id: z.string(),
  start_seconds: z.number(),
  end_seconds: z.number(),
  scene_type: z.string(),
  voiceover_text: z.string(),
  subtitle_text: z.string(),
  screen_card_text: z.string(),
  visual_intent: z.string(),
  tactical_focus: z.string(),
  transition_to_next: z.string(),
});

export const TimelineSchema = z.object({
  compositionId: z.string(),
  fps: z.number(),
  width: z.number(),
  height: z.number(),
  durationSeconds: z.number(),
  selectedHook: z.string(),
  mainContradiction: z.string(),
  voiceoverScript: z.string(),
  tacticalBeats: z.array(TacticalBeatSchema),
  moodShots: z.array(MoodShotSchema),
  narrativeSegments: z.array(NarrativeSegmentSchema),
});

export type TimelineProps = z.infer<typeof TimelineSchema>;

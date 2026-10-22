-- StepSync: reference dances imported from YouTube, with pose keypoints and motion features.
-- Run once in the Supabase dashboard: SQL Editor > New query > paste > Run.
-- The FastAPI backend writes with the secret key (bypasses RLS); app users can only read their own rows.

create table if not exists public.dance_videos (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid references auth.users (id) on delete set null,
  source_url         text not null,
  youtube_id         text,
  title              text not null,
  filename           text not null,
  duration_seconds   real,
  fps                real,
  width              integer,
  height             integer,
  frame_count        integer,
  frames_with_pose   integer,
  pose_coverage      real,   -- share of frames where a dancer was found, 0 to 1
  avg_motion_energy  real,   -- mean keypoint speed, torso lengths per second
  peak_motion_energy real,
  created_at         timestamptz not null default now()
);

create table if not exists public.pose_frames (
  video_id       uuid not null references public.dance_videos (id) on delete cascade,
  frame_index    integer not null,
  timestamp_ms   integer not null,
  pose_present   boolean not null,
  torso_scale_m  real,
  motion_energy  real,   -- mean keypoint speed in this frame
  joint_angles   jsonb not null default '{}'::jsonb,  -- {"left_knee": 152.3, ...} degrees
  keypoints      jsonb not null default '{}'::jsonb,  -- {"nose": {"x","y","z","visibility","presence","reliable","wx","wy","wz","hx","hy","hz","speed"}, ...}
  primary key (video_id, frame_index)
);

create index if not exists dance_videos_user_id_idx on public.dance_videos (user_id, created_at desc);

alter table public.dance_videos enable row level security;
alter table public.pose_frames enable row level security;

drop policy if exists "Users read their own dance videos" on public.dance_videos;
create policy "Users read their own dance videos" on public.dance_videos
  for select to authenticated using (user_id = auth.uid());

drop policy if exists "Users read frames of their own dance videos" on public.pose_frames;
create policy "Users read frames of their own dance videos" on public.pose_frames
  for select to authenticated using (
    exists (select 1 from public.dance_videos v where v.id = video_id and v.user_id = auth.uid())
  );

-- StepSync: the YouTube upload now writes into the team's tables (dances, steps, keyframes).
-- This replaces the upload's own tables from the two earlier files:
--   dance_videos and dance_steps are dropped (their rows were test uploads; upload again to recreate),
--   pose_frames is recreated to point at dances instead of dance_videos.
-- Run once in the Supabase dashboard: SQL Editor > New query > paste > Run. Safe to run again.

drop table if exists public.dance_steps;
drop table if exists public.pose_frames;
drop table if exists public.dance_videos;

create table public.pose_frames (
  dance_id       uuid not null references public.dances (id) on delete cascade,
  frame_index    integer not null,
  timestamp_ms   integer not null,
  pose_present   boolean not null,
  torso_scale_m  real,
  motion_energy  real,   -- mean keypoint speed in this frame, torso lengths per second
  joint_angles   jsonb not null default '{}'::jsonb,  -- {"left_knee": 152.3, ...} degrees
  keypoints      jsonb not null default '{}'::jsonb,  -- {"nose": {"x","y","z","visibility","reliable","speed", ...}, ...}
  primary key (dance_id, frame_index)
);

grant select, insert, update, delete on public.pose_frames to service_role;
grant select on public.pose_frames to authenticated;
-- The backend writes the team's tables with the secret key too.
grant select, insert, update, delete on public.dances, public.steps, public.keyframes to service_role;

alter table public.pose_frames enable row level security;

drop policy if exists "Users read frames of their own or public dances" on public.pose_frames;
create policy "Users read frames of their own or public dances" on public.pose_frames
  for select to authenticated using (
    exists (select 1 from public.dances d where d.id = dance_id and (d.owner_id = auth.uid() or d.is_public))
  );

notify pgrst, 'reload schema';

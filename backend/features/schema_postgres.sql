-- The pose_features table and view for Supabase/Postgres.
-- video_id is text here; switch it to uuid references reference_videos(id)
-- once Satwik and Aronno settle the video table.
create table if not exists pose_features (
  video_id       text not null,
  frame_index    integer not null,
  timestamp_ms   integer not null,
  frame_status   text not null,          -- OK / LOW_CONFIDENCE / NO_POSE
  feature        text not null,
  value          double precision,       -- null when missing, never 0
  units          text not null,
  status         text not null check (status in ('ok', 'missing')),
  missing_reason text,
  primary key (video_id, frame_index, feature)
);

-- One row per frame, one column per feature (angles, angle velocities, speeds).
create or replace view pose_features_wide as
select video_id, frame_index, timestamp_ms, frame_status,
  max(value) filter (where feature = 'left_elbow_angle') as left_elbow_angle,
  max(value) filter (where feature = 'right_elbow_angle') as right_elbow_angle,
  max(value) filter (where feature = 'left_knee_angle') as left_knee_angle,
  max(value) filter (where feature = 'right_knee_angle') as right_knee_angle,
  max(value) filter (where feature = 'left_shoulder_angle') as left_shoulder_angle,
  max(value) filter (where feature = 'right_shoulder_angle') as right_shoulder_angle,
  max(value) filter (where feature = 'left_hip_angle') as left_hip_angle,
  max(value) filter (where feature = 'right_hip_angle') as right_hip_angle,
  max(value) filter (where feature = 'left_elbow_velocity') as left_elbow_velocity,
  max(value) filter (where feature = 'right_elbow_velocity') as right_elbow_velocity,
  max(value) filter (where feature = 'left_knee_velocity') as left_knee_velocity,
  max(value) filter (where feature = 'right_knee_velocity') as right_knee_velocity,
  max(value) filter (where feature = 'left_shoulder_velocity') as left_shoulder_velocity,
  max(value) filter (where feature = 'right_shoulder_velocity') as right_shoulder_velocity,
  max(value) filter (where feature = 'left_hip_velocity') as left_hip_velocity,
  max(value) filter (where feature = 'right_hip_velocity') as right_hip_velocity,
  max(value) filter (where feature = 'left_wrist_speed') as left_wrist_speed,
  max(value) filter (where feature = 'right_wrist_speed') as right_wrist_speed,
  max(value) filter (where feature = 'left_ankle_speed') as left_ankle_speed,
  max(value) filter (where feature = 'right_ankle_speed') as right_ankle_speed
from pose_features
group by video_id, frame_index, timestamp_ms, frame_status;

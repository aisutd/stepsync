import cv2
import csv
import math
import argparse
from pathlib import Path

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


# -----------------------------
# Configuration
# -----------------------------

LANDMARK_THRESHOLD = 0.50
FRAME_OK_THRESHOLD = 0.75

# The 12 major body joints used to decide whether a frame is reliable.
CORE_LANDMARKS = [
    11, 12,  # shoulders
    13, 14,  # elbows
    15, 16,  # wrists
    23, 24,  # hips
    25, 26,  # knees
    27, 28,  # ankles
]

LANDMARK_NAMES = [
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
]

# MediaPipe's 33-point pose connection structure.
CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7),
    (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10),

    (11, 12),

    (11, 13), (13, 15),
    (15, 17), (15, 19), (15, 21),
    (17, 19),

    (12, 14), (14, 16),
    (16, 18), (16, 20), (16, 22),
    (18, 20),

    (11, 23),
    (12, 24),

    (23, 24),

    (23, 25), (25, 27),
    (27, 29), (29, 31), (27, 31),

    (24, 26), (26, 28),
    (28, 30), (30, 32), (28, 32),
]


def valid_landmark(landmark):
    """Return True when x/y/visibility/presence are usable."""
    values = [
        landmark.x,
        landmark.y,
        landmark.z,
        landmark.visibility,
        landmark.presence,
    ]

    return all(
        value is not None and math.isfinite(value)
        for value in values
    )


def landmark_is_reliable(landmark):
    """Decide whether a landmark should be displayed as reliable."""
    if not valid_landmark(landmark):
        return False

    return (
        landmark.visibility >= LANDMARK_THRESHOLD
        and landmark.presence >= LANDMARK_THRESHOLD
    )


def normalize_world_pose(pose, world_pose):
    """Center world landmarks at the hips and scale by torso length."""
    anchor_indices = (11, 12, 23, 24)

    if (
        world_pose is None
        or len(pose) <= max(anchor_indices)
        or len(world_pose) <= max(anchor_indices)
        or any(not landmark_is_reliable(pose[index]) for index in anchor_indices)
    ):
        return None, None

    world_coordinates = []

    for landmark in world_pose:
        coordinates = (landmark.x, landmark.y, landmark.z)

        if any(
            value is None or not math.isfinite(value)
            for value in coordinates
        ):
            world_coordinates.append(None)
        else:
            world_coordinates.append(coordinates)

    if any(world_coordinates[index] is None for index in anchor_indices):
        return None, None

    hip_center = tuple(
        (world_coordinates[23][axis] + world_coordinates[24][axis]) / 2
        for axis in range(3)
    )
    shoulder_center = tuple(
        (world_coordinates[11][axis] + world_coordinates[12][axis]) / 2
        for axis in range(3)
    )
    torso_scale_m = math.dist(hip_center, shoulder_center)

    if not math.isfinite(torso_scale_m) or torso_scale_m <= 1e-6:
        return None, None

    normalized_coordinates = []

    for coordinates in world_coordinates:
        if coordinates is None:
            normalized_coordinates.append(None)
            continue

        normalized_coordinates.append(tuple(
            (coordinates[axis] - hip_center[axis]) / torso_scale_m
            for axis in range(3)
        ))

    return normalized_coordinates, torso_scale_m


def pixel_position(landmark, width, height):
    """Convert normalized MediaPipe coordinates to image pixels."""
    if not valid_landmark(landmark):
        return None

    x = int(round(landmark.x * width))
    y = int(round(landmark.y * height))

    # Keep drawing coordinates inside the frame.
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))

    return x, y


def write_no_pose_rows(writer, frame_index, timestamp_ms, status):
    """Write blank landmark rows instead of inventing positions."""
    for landmark_id, name in enumerate(LANDMARK_NAMES):
        writer.writerow([
            frame_index,
            timestamp_ms,
            status,
            0,
            landmark_id,
            name,
            *([""] * 13),
        ])


def main(input_video, output_video, output_csv, model_path):
    input_video = Path(input_video)
    output_video = Path(output_video)
    output_csv = Path(output_csv)
    model_path = Path(model_path)

    output_video.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    if not input_video.exists():
        raise FileNotFoundError(f"Input video not found: {input_video}")

    if not model_path.exists():
        raise FileNotFoundError(f"MediaPipe model not found: {model_path}")

    # -----------------------------
    # Open input video
    # -----------------------------

    cap = cv2.VideoCapture(str(input_video))

    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {input_video}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError("Could not determine video dimensions.")

    if fps <= 0:
        cap.release()
        raise RuntimeError(
            "Video does not report a valid FPS. "
            "Use a video with a valid frame rate so timestamps remain aligned."
        )

    # mp4v is widely available with OpenCV.
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    writer = cv2.VideoWriter(
        str(output_video),
        fourcc,
        fps,
        (width, height),
    )

    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Could not create output video.")

    # -----------------------------
    # Create MediaPipe Pose Landmarker
    # -----------------------------

    base_options = python.BaseOptions(
        model_asset_path=str(model_path)
    )

    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.50,
        min_pose_presence_confidence=0.50,
        min_tracking_confidence=0.50,
    )

    # -----------------------------
    # Create CSV output
    # -----------------------------

    with open(output_csv, "w", newline="", encoding="utf-8") as csv_file:

        csv_writer = csv.writer(csv_file)

        csv_writer.writerow([
            "frame_index",
            "timestamp_ms",
            "frame_status",
            "pose_present",
            "landmark_id",
            "landmark_name",
            "x_norm",
            "y_norm",
            "z_relative",
            "visibility",
            "presence",
            "landmark_reliable",
            "world_x",
            "world_y",
            "world_z",
            "hip_relative_x_norm",
            "hip_relative_y_norm",
            "hip_relative_z_norm",
            "torso_scale_m",
        ])

        with vision.PoseLandmarker.create_from_options(options) as landmarker:

            frame_index = 0
            total_frames = 0
            no_pose_frames = 0
            low_confidence_frames = 0

            while True:
                success, frame = cap.read()

                if not success:
                    break

                total_frames += 1

                # Calculate timestamp from frame number and video FPS.
                timestamp_ms = int(round(
                    frame_index * 1000.0 / fps
                ))

                # OpenCV is BGR; MediaPipe expects RGB.
                frame_rgb = cv2.cvtColor(
                    frame,
                    cv2.COLOR_BGR2RGB
                )

                mp_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=frame_rgb,
                )

                # MediaPipe video mode requires monotonically increasing timestamps.
                result = landmarker.detect_for_video(
                    mp_image,
                    timestamp_ms,
                )

                # ------------------------------------
                # No person detected
                # ------------------------------------

                if not result.pose_landmarks:
                    no_pose_frames += 1

                    frame_status = "NO_POSE"

                    write_no_pose_rows(
                        csv_writer,
                        frame_index,
                        timestamp_ms,
                        frame_status,
                    )

                    cv2.putText(
                        frame,
                        "NO POSE DETECTED",
                        (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.0,
                        (0, 0, 255),
                        2,
                    )

                    writer.write(frame)
                    frame_index += 1
                    continue

                # ------------------------------------
                # A pose was detected
                # ------------------------------------

                pose = result.pose_landmarks[0]

                reliable_core = sum(
                    1
                    for idx in CORE_LANDMARKS
                    if idx < len(pose)
                    and landmark_is_reliable(pose[idx])
                )

                frame_reliability = (
                    reliable_core / len(CORE_LANDMARKS)
                )

                if frame_reliability >= FRAME_OK_THRESHOLD:
                    frame_status = "OK"
                else:
                    frame_status = "LOW_CONFIDENCE"
                    low_confidence_frames += 1

                # World coordinates, when available.
                world_pose = None

                if result.pose_world_landmarks:
                    world_pose = result.pose_world_landmarks[0]

                normalized_world_pose, torso_scale_m = normalize_world_pose(
                    pose,
                    world_pose,
                )

                # ------------------------------------
                # Save every landmark
                # ------------------------------------

                for landmark_id, landmark in enumerate(pose):

                    name = LANDMARK_NAMES[landmark_id]

                    reliable = landmark_is_reliable(landmark)

                    world_x = ""
                    world_y = ""
                    world_z = ""
                    hip_relative_x = ""
                    hip_relative_y = ""
                    hip_relative_z = ""

                    if (
                        world_pose is not None
                        and landmark_id < len(world_pose)
                    ):
                        world_landmark = world_pose[landmark_id]

                        if (
                            world_landmark.x is not None
                            and world_landmark.y is not None
                            and world_landmark.z is not None
                        ):
                            world_x = world_landmark.x
                            world_y = world_landmark.y
                            world_z = world_landmark.z

                    if (
                        normalized_world_pose is not None
                        and landmark_id < len(normalized_world_pose)
                    ):
                        normalized_landmark = normalized_world_pose[landmark_id]

                        if normalized_landmark is not None:
                            hip_relative_x, hip_relative_y, hip_relative_z = (
                                normalized_landmark
                            )

                    csv_writer.writerow([
                        frame_index,
                        timestamp_ms,
                        frame_status,
                        1,
                        landmark_id,
                        name,
                        landmark.x,
                        landmark.y,
                        landmark.z,
                        landmark.visibility,
                        landmark.presence,
                        int(reliable),
                        world_x,
                        world_y,
                        world_z,
                        hip_relative_x,
                        hip_relative_y,
                        hip_relative_z,
                        torso_scale_m if torso_scale_m is not None else "",
                    ])

                # ------------------------------------
                # Draw skeleton
                # ------------------------------------

                # Draw connections only when BOTH
                # endpoints are reliable.
                for start_idx, end_idx in CONNECTIONS:

                    if start_idx >= len(pose) or end_idx >= len(pose):
                        continue

                    start = pose[start_idx]
                    end = pose[end_idx]

                    if (
                        not landmark_is_reliable(start)
                        or not landmark_is_reliable(end)
                    ):
                        continue

                    p1 = pixel_position(start, width, height)
                    p2 = pixel_position(end, width, height)

                    if p1 is None or p2 is None:
                        continue

                    cv2.line(
                        frame,
                        p1,
                        p2,
                        (0, 255, 0),
                        2,
                    )

                # Draw reliable joints.
                for landmark in pose:

                    if not landmark_is_reliable(landmark):
                        continue

                    position = pixel_position(
                        landmark,
                        width,
                        height,
                    )

                    if position is None:
                        continue

                    cv2.circle(
                        frame,
                        position,
                        5,
                        (0, 255, 255),
                        -1,
                    )

                # ------------------------------------
                # Frame status overlay
                # ------------------------------------

                status_text = (
                    f"{frame_status} | "
                    f"frame={frame_index} | "
                    f"time={timestamp_ms}ms"
                )

                cv2.putText(
                    frame,
                    status_text,
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (255, 255, 255),
                    2,
                )

                writer.write(frame)

                frame_index += 1

    cap.release()
    writer.release()

    print()
    print("Processing complete.")
    print(f"Input:           {input_video}")
    print(f"Skeleton video:  {output_video}")
    print(f"Pose data:       {output_csv}")
    print(f"Frames:          {total_frames}")
    print(f"No-pose frames:  {no_pose_frames}")
    print(f"Low-confidence:  {low_confidence_frames}")
    print(f"FPS:             {fps}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Extract MediaPipe pose landmarks from a video."
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Input video path",
    )

    parser.add_argument(
        "--output-video",
        default="output/skeleton_preview.mp4",
        help="Output skeleton preview",
    )

    parser.add_argument(
        "--output-csv",
        default="output/pose_data.csv",
        help="Output pose CSV",
    )

    parser.add_argument(
        "--model",
        default="models/pose_landmarker_full.task",
        help="MediaPipe Pose Landmarker model",
    )

    args = parser.parse_args()

    main(
        args.input,
        args.output_video,
        args.output_csv,
        args.model,
    )
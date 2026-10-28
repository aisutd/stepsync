from app.keyframe_identifier import identify_keyframes, group_keyframes


def frame(i, x=0.0, present=True):
    return {"timestamp_ms": i * 100, "pose_present": present,
            "landmarks": [{"landmark_id": j, "x_norm": x, "y_norm": 0.5,
                           "visibility": 0.9, "presence": 0.9} for j in range(11, 17)]}


def test_static_pose_is_sampled_not_every_frame():
    frames = [frame(i) for i in range(100)]
    selected = identify_keyframes(frames)
    assert 2 <= len(selected) < 15
    assert selected[0] == 0
    assert all(frames[b]["timestamp_ms"] - frames[a]["timestamp_ms"] >= 400
               for a, b in zip(selected, selected[1:]))


def test_motion_triggers_keyframe():
    frames = [frame(i, 0.0 if i < 8 else 0.3) for i in range(20)]
    selected = identify_keyframes(frames)
    assert any(i in selected for i in range(8, 13))


def test_missing_poses_not_selected():
    frames = [frame(i, present=False) for i in range(20)]
    assert identify_keyframes(frames) == []


def test_grouping_covers_duration():
    frames = [frame(i) for i in range(130)]
    selected = identify_keyframes(frames)
    groups = group_keyframes(frames, selected, 13000)
    assert groups[0][0] == 0 and groups[-1][1] == 13000
    assert sum(len(g[2]) for g in groups) == len(selected)

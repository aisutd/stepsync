from datetime import datetime, timedelta, timezone
import json
import os
import uuid

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app
from app import session_store
from test_analyze import api


@pytest.fixture
def saved(api, video, tmp_path):
    response = api.post('/analyze', files={name: ('v.mp4', video.read_bytes(), 'video/mp4')
                                         for name in ('reference', 'practice')})
    assert response.status_code == 200, response.text
    summary = response.json()
    folder = tmp_path / 'uploads' / summary['sessionId']
    return summary, folder, json.loads((folder / 'comparison.json').read_text())


def test_summary_omits_bulk_evidence_and_preserves_frontend_contract(api, saved):
    summary, folder, full = saved
    assert not {'frameComparisons', 'diagnostics'} & summary.keys()
    assert 'anchorDiagnostics' not in json.dumps(summary)
    assert 'anchorRejections' not in json.dumps(summary)
    for key in ('sessionId', 'status', 'overallScore', 'movementScore', 'scoreScope', 'scoreAvailable',
                'globalScoreAvailable', 'coverage', 'confidence', 'steps', 'comparisonSegments', 'warnings', 'assessment'):
        assert summary[key] == full[key]
    assert len(json.dumps(summary).encode()) < 100_000
    assert (folder / 'frames.jsonl').is_file()
    assert api.get(summary['links']['summary']).json() == summary
    assert datetime.fromisoformat(summary['expiresAt']) > datetime.fromisoformat(summary['createdAt'])


def test_pages_reassemble_exact_original_records_without_recomputation(api, saved, monkeypatch):
    summary, _, full = saved
    def forbidden(*args, **kwargs):
        pytest.fail('Retrieval must not re-extract or recompute analysis')
    monkeypatch.setattr('app.analysis.compare', forbidden)
    monkeypatch.setattr('app.analysis.validate_video', forbidden)
    restarted = TestClient(create_app(pose_runner=forbidden))
    items, offset = [], 0
    while True:
        response = restarted.get(summary['links']['frames'], params={'offset': offset, 'limit': 7})
        assert response.status_code == 200, response.text
        page = response.json()
        assert page['total'] == len(full['frameComparisons'])
        assert page['offset'] == offset and page['limit'] == 7
        assert page['returned'] == len(page['items']) <= 7
        items.extend(page['items'])
        if not page['hasMore']:
            assert page['nextOffset'] is None
            break
        assert page['nextOffset'] > offset
        offset = page['nextOffset']
    assert items == full['frameComparisons']
    assert restarted.get(summary['links']['summary']).json() == summary


def test_frame_pagination_does_not_parse_full_comparison(api, saved, monkeypatch):
    summary, _, _ = saved
    original = session_store._read
    def bounded(path):
        assert path.name != 'comparison.json'
        return original(path)
    monkeypatch.setattr(session_store, '_read', bounded)
    assert api.get(summary['links']['frames'], params={'limit': 1}).status_code == 200


def test_last_page_and_exact_end_boundary(api, saved):
    summary, _, full = saved
    total = len(full['frameComparisons'])
    last = api.get(summary['links']['frames'], params={'offset': total - 1, 'limit': 100}).json()
    assert last['returned'] == 1 and not last['hasMore'] and last['nextOffset'] is None
    end = api.get(summary['links']['frames'], params={'offset': total}).json()
    assert end['items'] == [] and end['returned'] == 0 and not end['hasMore']
    assert api.get(summary['links']['frames'], params={'offset': total + 1}).status_code == 416


@pytest.mark.parametrize('params', [{'offset': -1}, {'offset': 'bad'}, {'limit': 0}, {'limit': 101}, {'limit': 'bad'}])
def test_page_validation_has_clear_errors(api, params):
    response = api.get('/analyses/' + '0' * 32 + '/frames', params=params)
    assert response.status_code == 422
    assert 'pagination' in response.json()['error']['message']


@pytest.mark.parametrize('suffix', ['', '/frames', '/diagnostics'])
def test_invalid_and_missing_session_ids(api, suffix):
    assert api.get('/analyses/not-a-session' + suffix).status_code == 422
    assert api.get('/analyses/' + 'A' * 32 + suffix).status_code == 422
    assert api.get('/analyses/' + '0' * 32 + suffix).status_code == 404


@pytest.mark.parametrize('suffix', ['', '/frames', '/diagnostics', '/diagnostics?download=true'])
def test_expired_sessions_return_410_without_deleting_artifacts(api, saved, suffix):
    summary, folder, _ = saved
    manifest = folder / 'analysis-manifest.json'
    data = json.loads(manifest.read_text())
    data['expiresAt'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    manifest.write_text(json.dumps(data))
    response = api.get(summary['links']['summary'] + suffix)
    assert response.status_code == 410
    assert 'expired' in response.json()['detail']
    assert (folder / 'comparison.json').is_file()


def test_diagnostics_json_and_download_are_complete_and_identical(api, saved):
    summary, folder, full = saved
    response = api.get(summary['links']['diagnostics'])
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.json() == full
    download = api.get(summary['links']['download'])
    assert download.content == (folder / 'comparison.json').read_bytes()
    assert 'attachment' in download.headers['content-disposition']
    assert summary['sessionId'] in download.headers['content-disposition']


def test_legacy_full_result_is_indexed_without_changing_measurements(api, tmp_path, saved):
    _, _, full = saved
    session_id = uuid.uuid4().hex
    folder = tmp_path / 'uploads' / session_id
    folder.mkdir()
    full = {**full, 'sessionId': session_id}
    path = folder / 'comparison.json'
    path.write_text(json.dumps(full))
    original_bytes, original_mtime = path.read_bytes(), path.stat().st_mtime
    response = api.get(f'/analyses/{session_id}')
    assert response.status_code == 200, response.text
    assert response.json()['assessment']['totalFrames'] == len(full['frameComparisons'])
    assert path.read_bytes() == original_bytes and path.stat().st_mtime == original_mtime
    page = api.get(f'/analyses/{session_id}/frames', params={'limit': 1}).json()
    assert page['items'] == full['frameComparisons'][:1]


def test_expired_legacy_result_is_not_reactivated(api, tmp_path, saved):
    _, _, full = saved
    session_id = uuid.uuid4().hex
    folder = tmp_path / 'uploads' / session_id
    folder.mkdir()
    path = folder / 'comparison.json'
    path.write_text(json.dumps(full))
    old = (datetime.now(timezone.utc) - timedelta(days=8)).timestamp()
    os.utime(path, (old, old))
    assert api.get(f'/analyses/{session_id}').status_code == 410
    assert not (folder / 'analysis-manifest.json').exists()


def test_empty_frames_have_a_valid_empty_page(api, tmp_path, saved):
    _, _, full = saved
    session_id = uuid.uuid4().hex
    folder = tmp_path / 'uploads' / session_id
    session_store.persist_analysis({**full, 'sessionId': session_id, 'frameComparisons': []}, folder, session_id, 3600)
    page = api.get(f'/analyses/{session_id}/frames').json()
    assert page['total'] == 0 and page['items'] == [] and page['nextOffset'] is None


def test_incomplete_frame_file_cannot_cause_infinite_pagination(api, saved):
    summary, folder, _ = saved
    (folder / 'frames.jsonl').write_text('')
    response = api.get(summary['links']['frames'])
    assert response.status_code == 500
    assert 'incomplete' in response.json()['detail']


def test_retention_setting_is_separate_from_comparison_policy(monkeypatch):
    monkeypatch.setenv('STEPSYNC_ANALYSIS_RETENTION_SECONDS', '3600')
    assert Settings.from_env().analysis_retention_seconds == 3600
    with pytest.raises(ValueError):
        Settings(analysis_retention_seconds=0)


def test_rebuilding_views_does_not_extend_a_sessions_original_expiry(api, saved):
    summary, folder, _ = saved
    (folder / 'frames.jsonl').unlink()
    restarted = TestClient(create_app(Settings(analysis_retention_seconds=14 * 24 * 3600)))
    response = restarted.get(summary['links']['summary'])
    assert response.status_code == 200
    assert response.json()['expiresAt'] == summary['expiresAt']


def test_storage_also_rejects_path_like_ids_before_reading(tmp_path):
    from fastapi import HTTPException
    for value in ('../escape', '..', 'a/b', 'a' * 31, 'A' * 32):
        with pytest.raises(HTTPException) as error:
            session_store.load_session(tmp_path, value, 3600)
        assert error.value.status_code == 422

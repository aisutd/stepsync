# StepSync backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`POST /analyze` takes two multipart video fields, `reference` and `practice`,
saves them to `backend/uploads/<session id>/`, and returns a placeholder result.
Swap `placeholder_result` for the real pipeline; the response has to match
`AnalysisResult` in `frontend/src/api/types.ts`.

Interactive docs: http://localhost:8000/docs

"""Additive response contract; legacy frontend fields remain available."""

from pydantic import BaseModel, Field


class StepFeedback(BaseModel):
    id: str
    label: str
    start: float
    end: float
    score: float = Field(ge=0, le=100)
    feedback: str
    evidence: dict = Field(default_factory=dict)


class AssessmentSummary(BaseModel):
    """Counts of original practice frames, not keypoints or source availability."""

    totalFrames: int = Field(ge=0)
    assessedFrames: int = Field(ge=0)
    unassessedFrames: int = Field(ge=0)


class AnalysisBase(BaseModel):
    sessionId: str
    overallScore: float = Field(ge=0, le=100, description=(
        "Legacy alias of movementScore when available, including partial results. "
        "Otherwise zero is a compatibility placeholder. Never interpret without scoreScope and coverage."))
    steps: list[StepFeedback]
    status: str
    scoreAvailable: bool = Field(description="A scoped movement score exists; true for completed OR partial results.")
    coverage: dict
    confidence: float
    alignment: dict
    warnings: list[str]
    movementScore: float | None = Field(default=None, ge=0, le=100)
    reason: str | None = None
    comparisonSegments: list[dict] = Field(default_factory=list)
    scoreScope: str = "none"
    globalScoreAvailable: bool = Field(default=False, description=(
        "Existing analysis-wide eligibility checks passed and a movement score was computed. "
        "Does not require 100% frame or joint coverage and is not a whole-video correctness grade. "
        "The score still uses only assessed observations; always display assessment coverage."))
    assessment: AssessmentSummary | None = None


class AnalysisResult(AnalysisBase):
    """Complete persisted result; served explicitly by the diagnostics endpoint."""

    frameComparisons: list[dict] = Field(default_factory=list)
    diagnostics: dict = Field(default_factory=dict)


class AnalysisSummary(AnalysisBase):
    createdAt: str
    expiresAt: str
    links: dict[str, str]


class FramePage(BaseModel):
    sessionId: str
    total: int
    offset: int
    limit: int
    returned: int
    hasMore: bool
    nextOffset: int | None
    items: list[dict]

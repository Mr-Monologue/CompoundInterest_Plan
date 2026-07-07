# v1.9 DataQualityIssue model
class DataQualityIssue(SQLModel, table=True):
    __tablename__ = "data_quality_issue"
    id: Optional[int] = Field(default=None, primary_key=True)
    issue_type: str = ""
    related_fund_code: str = ""
    related_module: str = ""
    severity: str = "info"
    priority: str = "P3"
    status: str = "OPEN"
    source: str = ""
    evidence_json: str = "{}"
    suggested_fix: str = ""
    fix_attempt_count: int = 0
    last_fix_result: str = ""
    audit_log_json: str = "[]"
    first_seen_at: datetime = Field(default_factory=datetime.now)
    last_seen_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
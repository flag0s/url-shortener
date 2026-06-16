from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class URLRecord:
    code: str
    target_url: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    hit_count: int = 0

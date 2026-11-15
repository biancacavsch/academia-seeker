"""Data models for jobs and academic items (CFPs, events, conferences)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import hashlib


def url_hash_for(url: str) -> str:
    """Hash estável de URL para dedup (normaliza removendo tracking params)."""
    from urllib.parse import urlparse, parse_qs, urlencode
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query, keep_blank_values=True)
    tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_content",
                      "utm_term", "ref", "source", "medium", "campaign", "fbclid", "gclid"}
    filtered = {k: v for k, v in query.items() if k.lower() not in tracking_params}
    normalized = parsed._replace(query=urlencode(filtered, doseq=True)).geturl()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


@dataclass
class BaseItem:
    """Base class for all collectable items."""
    title: str
    source: str
    url: str
    description: str = ""
    category: str = "job"  # job, cfp, event, conference, workshop
    tags: list[str] = field(default_factory=list)
    posted_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    location: str = ""
    language: str = "unknown"
    score: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.posted_at is None:
            self.posted_at = datetime.utcnow()
        if not hasattr(self, '_url_hash') or not self._url_hash:
            self._url_hash = self._compute_hash()

    @property
    def url_hash(self) -> str:
        return getattr(self, '_url_hash', '')

    @url_hash.setter
    def url_hash(self, value: str):
        self._url_hash = value

    def _compute_hash(self) -> str:
        """Hash estável para dedup: normaliza URL removendo query params variáveis."""
        return url_hash_for(self.url)

    def to_dict(self) -> dict:
        return {
            "url_hash": self.url_hash,
            "title": self.title,
            "source": self.source,
            "category": self.category,
            "url": self.url,
            "description": self.description,
            "tags": ",".join(self.tags),
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "deadline_at": self.deadline_at.isoformat() if self.deadline_at else None,
            "location": self.location,
            "language": self.language,
            "score": self.score,
            "matched_keywords": ",".join(self.matched_keywords),
            "raw_data": str(self.raw_data),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BaseItem":
        posted_at = None
        if data.get("posted_at"):
            try:
                posted_at = datetime.fromisoformat(data["posted_at"])
            except Exception:
                pass
        deadline_at = None
        if data.get("deadline_at"):
            try:
                deadline_at = datetime.fromisoformat(data["deadline_at"])
            except Exception:
                pass
        tags = data.get("tags", "").split(",") if data.get("tags") else []
        matched = data.get("matched_keywords", "").split(",") if data.get("matched_keywords") else []
        item = cls(
            title=data["title"],
            source=data["source"],
            category=data.get("category", "job"),
            url=data["url"],
            description=data["description"],
            tags=tags,
            posted_at=posted_at,
            deadline_at=deadline_at,
            location=data.get("location", ""),
            language=data.get("language", "unknown"),
            score=data.get("score", 0.0),
            matched_keywords=matched,
        )
        item.url_hash = data["url_hash"]
        return item


@dataclass
class Job(BaseItem):
    """Job vacancy item."""
    company: str = ""
    remote: bool = True
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_text: str = ""

    def __post_init__(self):
        self.category = "job"
        super().__post_init__()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "company": self.company,
            "remote": int(self.remote),
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_text": self.salary_text,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        posted_at = None
        if data.get("posted_at"):
            try:
                posted_at = datetime.fromisoformat(data["posted_at"])
            except Exception:
                pass
        deadline_at = None
        if data.get("deadline_at"):
            try:
                deadline_at = datetime.fromisoformat(data["deadline_at"])
            except Exception:
                pass
        tags = data.get("tags", "").split(",") if data.get("tags") else []
        matched = data.get("matched_keywords", "").split(",") if data.get("matched_keywords") else []
        job = cls(
            title=data["title"],
            source=data["source"],
            url=data["url"],
            description=data["description"],
            company=data.get("company", ""),
            remote=bool(data.get("remote", True)),
            tags=tags,
            posted_at=posted_at,
            deadline_at=deadline_at,
            location=data.get("location", ""),
            language=data.get("language", "unknown"),
            score=data.get("score", 0.0),
            matched_keywords=matched,
            salary_min=data.get("salary_min"),
            salary_max=data.get("salary_max"),
            salary_text=data.get("salary_text", ""),
        )
        job.url_hash = data["url_hash"]
        return job


@dataclass
class AcademicItem(BaseItem):
    """Academic item: bolsa, publicacao, evento (classificação por trilho)."""
    event_type: str = "cfp"  # cfp, conference, workshop, symposium, summer-school, fellowship, ...
    venue: str = ""  # conference/journal name
    submission_deadline: Optional[datetime] = None
    event_start_date: Optional[datetime] = None
    event_end_date: Optional[datetime] = None
    topics: list[str] = field(default_factory=list)
    is_virtual: bool = False
    travel_grant: bool = False
    track: str = ""  # bolsa | publicacao | evento (derivado de event_type se vazio)
    deadline_status: str = "unknown"  # open | closing_soon | closed | unknown

    # Mapeamento tipo → trilho
    TRACK_MAP = {
        "bolsa": ("fellowship", "grant", "scholarship", "bolsa", "edital",
                  "studentship", "bursary", "stipend"),
        "publicacao": ("cfp", "call", "special-issue", "special_issue", "chapter",
                       "article", "dossier", "dossiê", "dossie"),
        "evento": ("conference", "workshop", "symposium", "summer-school",
                   "seminar", "seminario", "seminário", "event", "evento",
                   "meeting", "congress", "congresso", "congreso", "colloquium",
                   "webinar", "panel"),
    }

    @classmethod
    def track_for(cls, event_type: str, category: str = "") -> str:
        text = f"{event_type} {category}".lower()
        for track, markers in cls.TRACK_MAP.items():
            if any(m in text for m in markers):
                return track
        return "evento"  # padrão conservador: visível, nunca bolsa

    def __post_init__(self):
        if self.category not in ("cfp", "event", "conference", "workshop",
                                 "bolsa", "publicacao", "evento"):
            self.category = "cfp"
        if not self.track:
            self.track = self.track_for(self.event_type, self.category)
        if self.deadline_status not in ("open", "closing_soon", "closed", "unknown"):
            self.deadline_status = "unknown"
        super().__post_init__()

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "event_type": self.event_type,
            "venue": self.venue,
            "submission_deadline": self.submission_deadline.isoformat() if self.submission_deadline else None,
            "event_start_date": self.event_start_date.isoformat() if self.event_start_date else None,
            "event_end_date": self.event_end_date.isoformat() if self.event_end_date else None,
            "topics": ",".join(self.topics),
            "is_virtual": int(self.is_virtual),
            "travel_grant": int(self.travel_grant),
            "track": self.track,
            "deadline_status": self.deadline_status,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AcademicItem":
        posted_at = None
        if data.get("posted_at"):
            try:
                posted_at = datetime.fromisoformat(data["posted_at"])
            except Exception:
                pass
        deadline_at = None
        if data.get("deadline_at"):
            try:
                deadline_at = datetime.fromisoformat(data["deadline_at"])
            except Exception:
                pass
        sub_deadline = None
        if data.get("submission_deadline"):
            try:
                sub_deadline = datetime.fromisoformat(data["submission_deadline"])
            except Exception:
                pass
        ev_start = None
        if data.get("event_start_date"):
            try:
                ev_start = datetime.fromisoformat(data["event_start_date"])
            except Exception:
                pass
        ev_end = None
        if data.get("event_end_date"):
            try:
                ev_end = datetime.fromisoformat(data["event_end_date"])
            except Exception:
                pass
        tags = data.get("tags", "").split(",") if data.get("tags") else []
        matched = data.get("matched_keywords", "").split(",") if data.get("matched_keywords") else []
        topics = data.get("topics", "").split(",") if data.get("topics") else []
        item = cls(
            title=data["title"],
            source=data["source"],
            category=data.get("category", "cfp"),
            url=data["url"],
            description=data["description"],
            tags=tags,
            posted_at=posted_at,
            deadline_at=deadline_at,
            location=data.get("location", ""),
            language=data.get("language", "unknown"),
            score=data.get("score", 0.0),
            matched_keywords=matched,
            event_type=data.get("event_type", "cfp"),
            venue=data.get("venue", ""),
            submission_deadline=sub_deadline,
            event_start_date=ev_start,
            event_end_date=ev_end,
            topics=topics,
            is_virtual=bool(data.get("is_virtual", False)),
            travel_grant=bool(data.get("travel_grant", False)),
            track=data.get("track") or "",
            deadline_status=data.get("deadline_status") or "unknown",
        )
        item.url_hash = data["url_hash"]
        return item


TRACK_EMOJI = {"bolsa": "🎓", "publicacao": "📄", "evento": "📅"}
TRACK_LABEL = {"bolsa": "Bolsas", "publicacao": "Publicações", "evento": "Eventos"}


def academic_section(item: "BaseItem") -> tuple:
    """(ordem, rótulo) das seções de saída acadêmica.

    ① Bolsas (PT) | ② Eventos e Publicações (PT) | ③ Língua estrangeira (EN+ES).
    """
    lang = (getattr(item, "language", "") or "unknown").lower()
    track = getattr(item, "track", "") or "evento"
    if lang == "pt":
        if track == "bolsa":
            return (0, f"{TRACK_EMOJI['bolsa']} Bolsas")
        return (1, "📄📅 Eventos e Publicações")
    return (2, f"🌍 Língua estrangeira ({lang.upper()})")
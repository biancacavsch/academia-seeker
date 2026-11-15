"""WikiCFP collector - Call for Papers from WikiCFP."""

import logging
from typing import Iterator, Optional
from datetime import datetime

from collectors.academic_base import AcademicRSSCollector
from models import AcademicItem

logger = logging.getLogger(__name__)


class WikiCFPCollector(AcademicRSSCollector):
    name = "wikicfp"

    def fetch(self) -> Iterator[AcademicItem]:
        base_url = self.source_config.get("url", "https://wikicfp.com/cfp/servlet/event.showcfp?feed=rss")
        categories = self.source_config.get("params", {}).get("categories", [])

        # WikiCFP supports category filtering via URL parameter
        if categories:
            for cat in categories:
                url = f"{base_url}&cat={cat}"
                yield from self._fetch_category(url, cat)
        else:
            yield from self._fetch_category(base_url, "all")

    def _fetch_category(self, url: str, category: str) -> Iterator[AcademicItem]:
        feed = self._parse_feed(url)
        for entry in feed.entries:
            try:
                item = self._parse_wikicfp_entry(entry, category)
                if item:
                    yield item
            except Exception as e:
                logger.warning(f"Failed to parse WikiCFP entry: {e}")
        self._sleep()

    def _parse_wikicfp_entry(self, entry, category: str) -> Optional[AcademicItem]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        description = entry.get("summary", entry.get("description", "")).strip()
        published = entry.get("published_parsed") or entry.get("updated_parsed")

        posted_at = None
        if published:
            posted_at = datetime(*published[:6])

        # WikiCFP entries have structured info in description
        # Format usually: "When: ... Where: ... Deadline: ..."
        venue = self._extract_venue(description)
        deadline_at = self._extract_deadline(description)
        event_dates = self._extract_event_dates(description)
        location = self._extract_location(description)
        is_virtual = self._detect_virtual(title, description)

        tags = [category, "wikicfp"]
        if "philosophy" in category.lower():
            tags.append("philosophy")
        if "humanities" in category.lower():
            tags.append("humanities")
        if "digital" in category.lower():
            tags.append("digital-humanities")

        item = AcademicItem(
            title=title,
            source=self.name,
            category="cfp",
            url=link,
            description=description,
            tags=tags,
            posted_at=posted_at,
            deadline_at=deadline_at,
            venue=venue,
            event_type=self._detect_event_type(title, description),
            submission_deadline=deadline_at,
            event_start_date=event_dates.get("start"),
            event_end_date=event_dates.get("end"),
            location=location,
            is_virtual=is_virtual,
        )
        return item

    def _extract_venue(self, text: str) -> str:
        import re
        # WikiCFP format: "CFP: Conference Name (Acronym) ..."
        patterns = [
            r"CFP:\s*([^\(]+)",
            r"Call for Papers[:\s]*([^\n]+)",
            r"Conference[:\s]*([^\n]+)",
            r"Workshop[:\s]*([^\n]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _extract_deadline(self, text: str) -> Optional[datetime]:
        import re
        patterns = [
            r"Deadline[:\s]*([^\n]+)",
            r"Submission Deadline[:\s]*([^\n]+)",
            r"Due Date[:\s]*([^\n]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                date_str = m.group(1).strip()
                try:
                    return self._parse_flexible_date(date_str)
                except Exception:
                    pass
        return None

    def _extract_event_dates(self, text: str) -> dict:
        import re
        result = {"start": None, "end": None}
        patterns = [
            r"When[:\s]*([^\n]+)",
            r"Date[:\s]*([^\n]+)",
            r"Conference Date[:\s]*([^\n]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                date_str = m.group(1).strip()
                # Try to parse start-end
                if " - " in date_str or " to " in date_str.lower():
                    parts = re.split(r"\s+-\s+|\s+to\s+", date_str, flags=re.IGNORECASE)
                    if len(parts) >= 2:
                        result["start"] = self._parse_flexible_date(parts[0])
                        result["end"] = self._parse_flexible_date(parts[1])
                else:
                    result["start"] = self._parse_flexible_date(date_str)
                break
        return result

    def _extract_location(self, text: str) -> str:
        import re
        patterns = [
            r"Where[:\s]*([^\n]+)",
            r"Location[:\s]*([^\n]+)",
            r"Venue[:\s]*([^\n]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def _parse_flexible_date(self, date_str: str) -> Optional[datetime]:
        """Parse various date formats from WikiCFP."""
        import re
        # Clean up
        date_str = re.sub(r'\s+', ' ', date_str.strip())
        date_str = re.sub(r'\(.*?\)', '', date_str).strip()

        formats = [
            "%B %d, %Y", "%b %d, %Y",
            "%d %B %Y", "%d %b %Y",
            "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y",
            "%B %d-%d, %Y", "%b %d-%d, %Y",
            "%d-%d %B %Y", "%d-%d %b %Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except Exception:
                pass

        # Try to extract just the first date-like thing
        m = re.search(r'([A-Za-z]+ \d{1,2},? \d{4})', date_str)
        if m:
            for fmt in ["%B %d, %Y", "%b %d, %Y"]:
                try:
                    return datetime.strptime(m.group(1), fmt)
                except Exception:
                    pass
        return None
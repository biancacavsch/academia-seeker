"""Base collectors for academic sources (CFPs, events, conferences)."""

import logging
import re
from abc import ABC
from typing import Iterator, Optional
from datetime import datetime
from urllib.parse import urljoin

from collectors import BaseCollector, RSSCollector
from models import AcademicItem, BaseItem

logger = logging.getLogger(__name__)


class AcademicRSSCollector(RSSCollector):
    """Base collector for academic RSS feeds."""

    def __init__(self):
        super().__init__()
        self.category = self.source_config.get("category", "cfp")
        self.keywords = self.source_config.get("params", {}).get("keywords", [])

    def fetch(self) -> Iterator[AcademicItem]:
        url = self.source_config.get("url")
        if not url:
            logger.warning(f"{self.name}: No URL configured")
            return

        feed = self._parse_feed(url)
        for entry in feed.entries:
            try:
                item = self._parse_entry(entry)
                if item:
                    yield item
            except Exception as e:
                logger.warning(f"Failed to parse {self.name} entry: {e}")

        self._sleep()

    def _parse_entry(self, entry) -> Optional[AcademicItem]:
        title = entry.get("title", "").strip()
        link = entry.get("link", entry.get("id", "")).strip()
        description = entry.get("summary", entry.get("description", "")).strip()
        published = entry.get("published_parsed") or entry.get("updated_parsed")

        posted_at = None
        if published:
            posted_at = datetime(*published[:6])

        # Extract tags
        tags = []
        for tag in entry.get("tags", []):
            if isinstance(tag, dict):
                tags.append(tag.get("term", ""))
            else:
                tags.append(str(tag))

        # Try to extract deadline from description
        deadline_at = self._extract_deadline(description)
        venue = self._extract_venue(title, description)

        # Determine event type
        event_type = self._detect_event_type(title, description)

        # Check if virtual
        is_virtual = self._detect_virtual(title, description)

        item = AcademicItem(
            title=title,
            source=self.name,
            category=self.category,
            url=link,
            description=description,
            tags=tags,
            posted_at=posted_at,
            deadline_at=deadline_at,
            venue=venue,
            event_type=event_type,
            submission_deadline=deadline_at,
            is_virtual=is_virtual,
        )
        return item

    def _extract_deadline(self, text: str) -> Optional[datetime]:
        """Extract deadline date from text."""
        patterns = [
            r"deadline[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            r"deadline[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
            r"submission[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            r"due[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*(?:deadline|due)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return self._parse_date(m.group(1))
                except Exception:
                    pass
        return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Try to parse various date formats."""
        formats = [
            "%B %d, %Y", "%b %d, %Y",
            "%d/%m/%Y", "%m/%d/%Y",
            "%d-%m-%Y", "%Y-%m-%d",
            "%d %B %Y", "%d %b %Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except Exception:
                pass
        return None

    def _extract_venue(self, title: str, desc: str) -> str:
        """Extract conference/journal venue name."""
        # Common patterns
        patterns = [
            r"(?:at|@)\s+([A-Z][A-Za-z\s&.,'-]{3,})",
            r"(?:conference|workshop|symposium|journal)\s+([A-Z][A-Za-z\s&.,'-]{3,})",
            r"^([A-Z][A-Za-z\s&.,'-]{3,}):\s",
        ]
        text = f"{title} {desc}"
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1).strip()
        return ""

    def _detect_event_type(self, title: str, desc: str) -> str:
        text = f"{title} {desc}".lower()
        if any(w in text for w in ["summer school", "summerschool", "winter school"]):
            return "summer-school"
        if any(w in text for w in ["fellowship", "grant", "scholarship"]):
            return "fellowship"
        if any(w in text for w in ["workshop", "hackathon"]):
            return "workshop"
        if any(w in text for w in ["symposium", "colloquium"]):
            return "symposium"
        if any(w in text for w in ["conference", "congress", "meeting"]):
            return "conference"
        return "cfp"

    def _detect_virtual(self, title: str, desc: str) -> bool:
        text = f"{title} {desc}".lower()
        return any(w in text for w in ["virtual", "online", "remote", "hybrid", "webinar", "zoom"])


class AcademicHTMLCollector(BaseCollector):
    """Base collector for academic HTML scraping with configurable selectors."""

    def __init__(self):
        super().__init__()
        try:
            from playwright.sync_api import sync_playwright
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=True)
        except Exception as e:
            logger.warning(f"Playwright not available: {e}")
            self.playwright = None
            self.browser = None

        params = self.source_config.get("params", {})
        self.selector = params.get("selector", "article, .post, .entry, .item")
        self.title_selector = params.get("title_selector", "h1, h2, h3, .entry-title, .post-title")
        self.link_selector = params.get("link_selector", "a")
        self.date_selector = params.get("date_selector", "time, .date, .published")
        self.desc_selector = params.get("description_selector", ".entry-content, .post-content, .excerpt, .content")
        self.category = self.source_config.get("category", "cfp")

    def fetch(self) -> Iterator[AcademicItem]:
        url = self.source_config.get("url")
        if not url or not self.browser:
            logger.warning(f"{self.name}: No URL or browser not available")
            return

        page = self.browser.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            items = page.query_selector_all(self.selector)
            for item_el in items:
                try:
                    item = self._parse_element(item_el, url)
                    if item:
                        yield item
                except Exception as e:
                    logger.debug(f"Failed to parse element: {e}")

        except Exception as e:
            logger.warning(f"{self.name} fetch failed: {e}")
        finally:
            page.close()
            self._sleep()

    def _parse_element(self, el, base_url: str) -> Optional[AcademicItem]:
        # Title and link
        title_el = el.query_selector(self.title_selector)
        link_el = el.query_selector(self.link_selector)

        if not title_el:
            return None

        title = title_el.inner_text().strip()
        link = ""
        if link_el:
            href = link_el.get_attribute("href")
            if href:
                link = urljoin(base_url, href)

        # Description
        desc_el = el.query_selector(self.desc_selector)
        description = desc_el.inner_text().strip() if desc_el else ""

        # Date
        date_el = el.query_selector(self.date_selector)
        posted_at = None
        if date_el:
            date_text = date_el.inner_text().strip()
            posted_at = self._parse_date(date_text)
        # Try datetime attribute
        if not posted_at and date_el:
            dt_attr = date_el.get_attribute("datetime")
            if dt_attr:
                try:
                    posted_at = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                except Exception:
                    pass

        # Extract deadline from description
        deadline_at = self._extract_deadline(description)

        item = AcademicItem(
            title=title,
            source=self.name,
            category=self.category,
            url=link or base_url,
            description=description,
            posted_at=posted_at,
            deadline_at=deadline_at,
            event_type=self._detect_event_type(title, description),
            is_virtual=self._detect_virtual(title, description),
        )
        return item

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        formats = [
            "%B %d, %Y", "%b %d, %Y",
            "%d/%m/%Y", "%m/%d/%Y",
            "%d-%m-%Y", "%Y-%m-%d",
            "%d %B %Y", "%d %b %Y",
            "%Y-%m-%dT%H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except Exception:
                pass
        return None

    def _extract_deadline(self, text: str) -> Optional[datetime]:
        import re
        patterns = [
            r"deadline[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            r"deadline[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
            r"submission[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            r"due[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return self._parse_date(m.group(1))
                except Exception:
                    pass
        return None

    def _detect_event_type(self, title: str, desc: str) -> str:
        text = f"{title} {desc}".lower()
        if any(w in text for w in ["summer school", "summerschool", "winter school"]):
            return "summer-school"
        if any(w in text for w in ["fellowship", "grant", "scholarship"]):
            return "fellowship"
        if any(w in text for w in ["workshop", "hackathon"]):
            return "workshop"
        if any(w in text for w in ["symposium", "colloquium"]):
            return "symposium"
        if any(w in text for w in ["conference", "congress", "meeting"]):
            return "conference"
        return "cfp"

    def _detect_virtual(self, title: str, desc: str) -> bool:
        text = f"{title} {desc}".lower()
        return any(w in text for w in ["virtual", "online", "remote", "hybrid", "webinar", "zoom"])

    def close(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
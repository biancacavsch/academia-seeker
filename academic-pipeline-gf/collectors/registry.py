"""Collector registry - import and register all collectors (academic only)."""

from collectors.euraxess import EuraxessCollector
from collectors.wikicfp import WikiCFPCollector
from collectors.hnet import HNetCollector
from collectors.upenn_cfp import UpennCfpCollector
from collectors.search_academic import SearchAcademicCollector
from collectors import AcademicRSSCollector, AcademicHTMLCollector
from config import CONFIG


def _create_rss_collector(name: str, source_config: dict):
    """Create an RSS collector dynamically from config."""
    class DynamicRSSCollector(AcademicRSSCollector):
        pass
    DynamicRSSCollector.name = name
    DynamicRSSCollector.__name__ = f"DynamicRSS_{name}"
    collector = DynamicRSSCollector()
    collector.source_config = source_config
    return collector


def _create_html_collector(name: str, source_config: dict):
    """Create an HTML collector dynamically from config (academic)."""
    class DynamicHTMLCollector(AcademicHTMLCollector):
        pass
    DynamicHTMLCollector.name = name
    DynamicHTMLCollector.__name__ = f"DynamicHTML_{name}"
    collector = DynamicHTMLCollector()
    collector.source_config = source_config
    return collector


ACADEMIC_COLLECTORS = {
    "wikicfp": WikiCFPCollector,
    "hnet_announcements": HNetCollector,
    "upenn_cfp": UpennCfpCollector,
    "euraxess": EuraxessCollector,
}


def get_collector(name: str, source_config: dict = None):
    cls = ACADEMIC_COLLECTORS.get(name)
    if cls:
        return cls()

    # Dynamic creation from config
    if source_config:
        source_type = source_config.get("type", "rss")
        if source_type == "rss":
            return _create_rss_collector(name, source_config)
        elif source_type == "html":
            return _create_html_collector(name, source_config)

    raise ValueError(f"Unknown collector: {name}")


def get_job_collectors():
    """Get only job collectors (empty — this pipeline is academic-only)."""
    return []


def get_academic_collectors():
    """Get only academic collectors."""
    enabled = []
    for src in CONFIG.get("academic_sources", []):
        if src.get("enabled", True):
            collector = get_collector(src["name"], src)
            enabled.append(collector)
    if CONFIG.get("academic_search", {}).get("enabled", False):
        enabled.append(SearchAcademicCollector())
    return enabled


def get_enabled_collectors():
    """Get all collectors (backward compatibility)."""
    return get_academic_collectors()
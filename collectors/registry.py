"""Collector registry - import and register all collectors."""

from collectors.arbeitnow import ArbeitnowCollector
from collectors.remotive import RemotiveCollector
from collectors.remotejobs_org import RemoteJobsOrgCollector
from collectors.dhnow import DHNowCollector
from collectors.archives_gig import ArchivesGigDHCollector
from collectors.euraxess import EuraxessCollector
from collectors.wikicfp import WikiCFPCollector
from collectors.hnet import HNetCollector
from collectors.upenn_cfp import UpennCfpCollector
from collectors.search_academic import SearchAcademicCollector
from collectors.adzuna import AdzunaCollector, AdzunaEstagioCollector
from collectors.jooble import JoobleCollector
from collectors.estagio_search import EstagioSearchCollector
from collectors.empresas_alvo import EmpresasAlvoCollector
from collectors.job_html import JobHTMLCollector
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


def _create_job_html_collector(name: str, source_config: dict):
    """Create an HTML job collector dynamically from config (jobs/estágio)."""
    class DynamicJobHTMLCollector(JobHTMLCollector):
        pass
    DynamicJobHTMLCollector.name = name
    DynamicJobHTMLCollector.__name__ = f"DynamicJobHTML_{name}"
    collector = DynamicJobHTMLCollector()
    collector.source_config = source_config
    collector.rate_limit = source_config.get("rate_limit", 2.0)
    return collector


JOB_COLLECTORS = {
    "arbeitnow": ArbeitnowCollector,
    "remotive": RemotiveCollector,
    "remotejobs_org": RemoteJobsOrgCollector,
    "dhnow_jobs": DHNowCollector,
    "archives_gig_dh": ArchivesGigDHCollector,
    "euraxess": EuraxessCollector,
    "adzuna": AdzunaCollector,
    "adzuna_estagio": AdzunaEstagioCollector,
    "jooble": JoobleCollector,
    "estagio_search": EstagioSearchCollector,
    "empresas_alvo": EmpresasAlvoCollector,
}

ACADEMIC_COLLECTORS = {
    "wikicfp": WikiCFPCollector,
    "hnet_announcements": HNetCollector,
    "upenn_cfp": UpennCfpCollector,
}


def get_collector(name: str, source_config: dict = None):
    cls = JOB_COLLECTORS.get(name) or ACADEMIC_COLLECTORS.get(name)
    if cls:
        return cls()

    # Dynamic creation from config
    if source_config:
        source_type = source_config.get("type", "rss")
        if source_type == "html_job":
            return _create_job_html_collector(name, source_config)
        elif source_type == "rss":
            return _create_rss_collector(name, source_config)
        elif source_type == "html":
            return _create_html_collector(name, source_config)

    raise ValueError(f"Unknown collector: {name}")


def get_job_collectors():
    """Get only job collectors."""
    enabled = []
    for src in CONFIG["sources"]:
        if src.get("enabled", True):
            collector = get_collector(src["name"], src)
            enabled.append(collector)
    return enabled


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
    return get_job_collectors() + get_academic_collectors()
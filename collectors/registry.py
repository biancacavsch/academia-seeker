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


def get_collector(name: str, source_config: dict = None, config: dict = None):
    """Cria coletor. `config` permite que cada levantamento use a própria whitelist."""
    cfg = config if config is not None else CONFIG
    cls = JOB_COLLECTORS.get(name) or ACADEMIC_COLLECTORS.get(name)
    if cls:
        collector = cls()
        if hasattr(collector, "cfg"):
            collector.cfg = _scope_config(cfg, name, source_config)
        if hasattr(collector, "source_config") and source_config:
            collector.source_config = dict(source_config)
        return collector

    # Dynamic creation from config
    if source_config:
        source_type = source_config.get("type", "rss")
        if source_type == "html_job":
            collector = _create_job_html_collector(name, source_config)
        elif source_type == "rss":
            collector = _create_rss_collector(name, source_config)
        elif source_type == "html":
            collector = _create_html_collector(name, source_config)
        else:
            raise ValueError(f"Unknown collector: {name}")
        if hasattr(collector, "cfg"):
            collector.cfg = _scope_config(cfg, name, source_config)
        if hasattr(collector, "source_config") and source_config:
            collector.source_config = dict(source_config)
        return collector

    raise ValueError(f"Unknown collector: {name}")


def _scope_config(cfg: dict, name: str, source_config: dict | None) -> dict:
    """Subseção de config relevante para o coletor (com override do levantamento)."""
    if source_config and source_config.get("kind") == "estagio":
        section = "estagio_search"
    elif name in ("estagio_search", "empresas_alvo", "catho_estagio",
                  "vagas_estagio", "jobs99_estagio"):
        section = "estagio_search" if name == "estagio_search" else "empresas_alvo"
    else:
        section = "academic_search" if name in ACADEMIC_COLLECTORS or \
            (source_config or {}).get("category") else "academic_search"
    return cfg.get(section, {}) or {}


def get_job_collectors(config: dict = None):
    """Get only job collectors, honoring the active survey's config."""
    cfg = config if config is not None else CONFIG
    enabled = []
    for src in cfg.get("sources", []):
        if not src.get("enabled", True):
            continue
        if (src.get("kind") == "estagio" and
                not (cfg.get("estagio_search", {}) or {}).get("enabled", True)):
            continue
        enabled.append(get_collector(src["name"], src, cfg))
    return enabled


def get_academic_collectors(config: dict = None):
    """Get only academic collectors, honoring the active survey's config."""
    cfg = config if config is not None else CONFIG
    enabled = []
    for src in cfg.get("academic_sources", []):
        if src.get("enabled", True):
            enabled.append(get_collector(src["name"], src, cfg))
    if (cfg.get("academic_search", {}) or {}).get("enabled", False):
        collector = SearchAcademicCollector()
        collector.cfg = cfg.get("academic_search", {})
        enabled.append(collector)
    return enabled


def get_enabled_collectors(config: dict = None):
    """Get all collectors (backward compatibility)."""
    return get_job_collectors(config) + get_academic_collectors(config)



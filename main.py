"""Main CLI entry point."""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from typing import List
from pathlib import Path

# Ensure package root is in path
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import CONFIG
from store import ItemStore, get_jobs_store, get_academic_store
from score import score_item
from relevance import deduplicate
from collectors.registry import get_job_collectors, get_academic_collectors
from alerts import AlertManager
from models import Job, AcademicItem, BaseItem, academic_section, TRACK_EMOJI

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("job-pipeline")


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.getLogger().setLevel(level)


def run_job_collection(store: ItemStore, verbose: bool = False) -> List[Job]:
    """Executa coleta apenas de vagas de emprego."""
    collectors = get_job_collectors()
    all_jobs = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        for collector in collectors:
            task = progress.add_task(f"Coletando vagas {collector.name}...", total=None)
            try:
                for job in deduplicate(collector.fetch()):
                    job = score_item(job)
                    if job.score >= CONFIG["filters"]["min_score_digest"] - 10:
                        is_new = store.upsert_item(job)
                        if is_new:
                            all_jobs.append(job)
                            if verbose:
                                console.print(f"  [green]+[/green] 💼 {job.title[:60]} (score: {job.score})")
                progress.update(task, description=f"✓ {collector.name} ({len(all_jobs)} novas)")
            except Exception as e:
                logger.error(f"Collector {collector.name} failed: {e}")
                progress.update(task, description=f"✗ {collector.name} falhou")

    return all_jobs


def run_academic_collection(store: ItemStore, verbose: bool = False) -> List[AcademicItem]:
    """Executa coleta apenas de CFPs/eventos acadêmicos."""
    collectors = get_academic_collectors()
    all_items = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        for collector in collectors:
            task = progress.add_task(f"Coletando acadêmico {collector.name}...", total=None)
            try:
                for item in deduplicate(collector.fetch()):
                    item = score_item(item)
                    if item.score >= CONFIG["filters"]["min_score_digest"] - 10:
                        is_new = store.upsert_item(item)
                        if is_new:
                            all_items.append(item)
                            if verbose:
                                cat_emoji = {"cfp": "📄", "event": "📅", "conference": "🎪", "workshop": "🔧", "symposium": "🎓", "fellowship": "🎓"}.get(item.category, "📋")
                                console.print(f"  [green]+[/green] {cat_emoji} {item.title[:60]} (score: {item.score})")
                progress.update(task, description=f"✓ {collector.name} ({len(all_items)} novas)")
            except Exception as e:
                logger.error(f"Collector {collector.name} failed: {e}")
                progress.update(task, description=f"✗ {collector.name} falhou")

    return all_items


def run_alerts(store: ItemStore, channel: str = "both", category: str = None, kind: str = None):
    """Envia alertas para items não alertados acima do threshold."""
    min_score = CONFIG["filters"]["min_score_alert"]
    unalerted = store.get_unalerted_items(min_score=min_score, category=category, kind=kind)

    if not unalerted:
        cat_str = f" ({category or kind})" if (category or kind) else ""
        console.print(f"[yellow]Nenhum item novo acima do threshold para alertar{cat_str}[/yellow]")
        return

    # Acadêmicos: ordena por seção (bolsas → ev/pub → estrangeira) e score
    if kind == "academic":
        unalerted.sort(key=lambda i: (academic_section(i)[0],
                                      0 if getattr(i, "deadline_status", "") == "closing_soon" else 1,
                                      -i.score))

    alert_mgr = AlertManager()
    failed = alert_mgr.send_alerts(unalerted, channel=channel) or set()

    try:
        from feedback import get_feedback_store
        fb = get_feedback_store()
        for item in unalerted:
            if item.url_hash not in failed:
                fb.record(item, "alerted",
                          ", ".join(item.matched_keywords[:3]))
    except Exception as exc:
        logger.warning(f"Não foi possível registrar feedback: {exc}")

    # Só marca o que de fato foi enviado (falha de envio fica para a próxima)
    sent = 0
    for item in unalerted:
        if item.url_hash in failed:
            continue
        store.mark_alerted(item.url_hash, channel)
        sent += 1

    cat_str = f" ({category or kind})" if (category or kind) else ""
    if failed:
        console.print(f"[yellow]⚠ {sent} alertas enviados, {len(failed)} falharam"
                      f" (serão reenviados na próxima execução){cat_str}[/yellow]")
    else:
        console.print(f"[green]✓ Alertas enviados para {sent} itens{cat_str}[/green]")


def _academic_table(title: str, items: list) -> None:
    table = Table(title=title)
    table.add_column("Score", style="bold green", justify="right")
    table.add_column("Tipo", style="dim", justify="center")
    table.add_column("Título", style="cyan", max_width=45)
    table.add_column("Venue/Fonte", style="magenta", max_width=25)
    table.add_column("Deadline/Local", style="blue", max_width=22)
    table.add_column("Keywords", style="yellow", max_width=30)
    for item in items[:15]:
        kw = ", ".join(item.matched_keywords[:3])
        track = getattr(item, "track", "") or "evento"
        emoji = TRACK_EMOJI.get(track, "📋")
        lang = (getattr(item, "language", "") or "?").upper()
        venue = getattr(item, "venue", "") or ""
        dl = getattr(item, "submission_deadline", None) or getattr(item, "deadline_at", None)
        if dl:
            try:
                loc = f"⏰ {dl.strftime('%d/%m/%Y')}"
            except Exception:
                loc = ""
        else:
            loc = (item.location or "")[:20]
        table.add_row(str(item.score), f"{emoji} {lang}", item.title[:43],
                      venue[:23], loc[:20], kw[:28])
    console.print(table)
    console.print(f"Total na seção: {len(items)} itens\n")


def show_academic_digest(store: ItemStore, days: int = 7, min_score: float = None):
    """Digest acadêmico em 3 seções + quarentena."""
    if min_score is None:
        min_score = CONFIG["filters"]["min_score_digest"]

    items = [i for i in store.get_recent_items(days=days, min_score=min_score, posted_age=False)
             if i.category != "job"]
    open_items = [i for i in items
                  if getattr(i, "deadline_status", "unknown") in ("open", "closing_soon")]
    # Quarentena: sem deadline extraível — só recentes (vale a pena verificar)
    quar = sorted(
        [i for i in store.get_recent_items(days=days, min_score=min_score, posted_age=True)
         if i.category != "job"
         and getattr(i, "deadline_status", "unknown") == "unknown"],
        key=lambda x: -x.score)[:15]

    def soon_first(it):
        return (0 if getattr(it, "deadline_status", "") == "closing_soon" else 1,
                -it.score)

    bolsas_pt = sorted([i for i in open_items
                        if getattr(i, "track", "") == "bolsa" and (i.language or "") == "pt"],
                       key=soon_first)
    evpub_pt = sorted([i for i in open_items
                       if getattr(i, "track", "") in ("evento", "publicacao")
                       and (i.language or "") == "pt"], key=soon_first)
    foreign = sorted([i for i in open_items if (i.language or "") in ("en", "es")],
                     key=soon_first)

    console.print(f"[bold cyan]🎓 Digest Acadêmico — últimos {days} dia(s), score ≥ {min_score}[/bold cyan]")
    console.print("[bold]① 🎓 Bolsas (PT)[/bold]")
    if bolsas_pt:
        _academic_table("① 🎓 Bolsas", bolsas_pt)
    else:
        console.print("[yellow]Nenhuma bolsa PT aberta no período[/yellow]\n")
    console.print("[bold]② 📄📅 Eventos e Publicações (PT)[/bold]")
    if evpub_pt:
        _academic_table("② 📄📅 Eventos e Publicações", evpub_pt)
    else:
        console.print("[yellow]Nenhum evento/publicação PT aberto no período[/yellow]\n")
    console.print("[bold]③ 🌍 Língua estrangeira (EN+ES)[/bold]")
    if foreign:
        _academic_table("③ 🌍 Língua estrangeira", foreign)
    else:
        console.print("[yellow]Nenhum item EN/ES aberto no período[/yellow]\n")
    console.print("[bold]⚠️ Quarentena — sem data de fechamento identificada (verificar manualmente, nunca alerta)[/bold]")
    if quar:
        _academic_table("⚠️ Quarentena", quar)
    else:
        console.print("[yellow]Quarentena vazia[/yellow]\n")


def show_digest(store: ItemStore, days: int = 7, min_score: float = None, category: str = None):
    """Mostra digest dos itens recentes."""
    if min_score is None:
        min_score = CONFIG["filters"]["min_score_digest"]

    items = store.get_recent_items(days=days, min_score=min_score, category=category)

    if not items:
        cat_str = f" ({category})" if category else ""
        console.print(f"[yellow]Nenhum item no período{cat_str}[/yellow]")
        return

    cat_str = f" ({category})" if category else ""
    table = Table(title=f"📋 Digest - Últimos {days} dia(s) (score ≥ {min_score}){cat_str}")
    table.add_column("Score", style="bold green", justify="right")
    table.add_column("Tipo", style="dim", justify="center")
    table.add_column("Título", style="cyan", max_width=45)
    table.add_column("Fonte/Venue", style="magenta", max_width=25)
    table.add_column("Local/Deadline", style="blue", max_width=22)
    table.add_column("Keywords", style="yellow", max_width=35)

    for item in items[:40]:
        kw = ", ".join(item.matched_keywords[:3])
        cat_emoji = {"job": "💼", "cfp": "📄", "event": "📅", "conference": "🎪", "workshop": "🔧", "symposium": "🎓", "fellowship": "🎓"}.get(item.category, "📋")
        venue = item.venue if hasattr(item, 'venue') and item.venue else (item.company if hasattr(item, 'company') else "")
        loc = ""
        if hasattr(item, 'submission_deadline') and item.submission_deadline:
            loc = f"📅 {item.submission_deadline.strftime('%d/%m')}"
        elif item.location:
            loc = item.location[:20]
        elif hasattr(item, 'deadline_at') and item.deadline_at:
            loc = f"⏰ {item.deadline_at.strftime('%d/%m')}"

        table.add_row(
            str(item.score),
            cat_emoji,
            item.title[:43],
            venue[:23],
            loc[:20],
            kw[:33],
        )

    console.print(table)
    console.print(f"\nTotal: {len(items)} itens")


def show_deadlines(store: ItemStore, days: int = 30):
    """Mostra oportunidades acadêmicas com deadlines próximas (qualquer categoria)."""
    items = store.get_upcoming_deadlines(days=days, category=None)

    if not items:
        console.print(f"[yellow]Nenhum prazo de submissão nos próximos {days} dias[/yellow]")
        return

    table = Table(title=f"⏰ Prazos de Submissão nos Próximos {days} Dias")
    table.add_column("Deadline", style="bold red", justify="center")
    table.add_column("Score", style="green", justify="right")
    table.add_column("Título", style="cyan", max_width=50)
    table.add_column("Venue", style="magenta", max_width=30)
    table.add_column("Tipo", style="dim", max_width=12)
    table.add_column("Virtual", style="blue", justify="center")

    for item in items:
        deadline = item.submission_deadline or item.deadline_at
        deadline_str = deadline.strftime("%d/%m/%Y") if deadline else "N/A"
        virtual = "🌐" if item.is_virtual else ""

        table.add_row(
            deadline_str,
            str(item.score),
            item.title[:48],
            item.venue[:28],
            item.event_type,
            virtual,
        )

    console.print(table)
    console.print(f"\nTotal: {len(items)} itens com prazo")


def show_stats(store: ItemStore, label: str = "Banco"):
    """Mostra estatísticas de um banco."""
    stats = store.get_stats()

    table = Table(title=f"📊 Estatísticas — {label} ({Path(store.db_path).name})")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", style="green")

    table.add_row("Total de itens", str(stats["total_items"]))
    table.add_row("Alertados", str(stats["alerted"]))
    table.add_row("Não alertados", str(stats["unalerted"]))
    table.add_row("Score médio", str(stats["avg_score"]))

    console.print(table)

    if stats["by_category"]:
        cat_table = Table(title="Por Categoria")
        cat_table.add_column("Categoria", style="cyan")
        cat_table.add_column("Itens", style="green", justify="right")
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            cat_table.add_row(cat, str(count))
        console.print(cat_table)

    if stats["by_source"]:
        source_table = Table(title="Por Fonte")
        source_table.add_column("Fonte", style="cyan")
        source_table.add_column("Itens", style="green", justify="right")
        for src, count in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
            source_table.add_row(src, str(count))
        console.print(source_table)


def test_alerts():
    """Testa configuração de alertas."""
    alert_mgr = AlertManager()

    # Job de teste
    test_job = Job(
        title="Digital Humanities Researcher - Science Communication",
        company="University of Example",
        location="Remote (Worldwide)",
        remote=True,
        url="https://example.com/job/123",
        description="We seek a digital humanities researcher with background in science communication and cultural dissemination. Social sciences PhD preferred.",
        source="test",
        tags=["digital humanities", "science communication", "remote"],
        score=85.0,
        matched_keywords=["digital humanities", "science communication", "cultural dissemination", "social sciences"],
    )

    # CFP de teste
    test_cfp = AcademicItem(
        title="CFP: Philosophy of Technology Conference 2025",
        source="test",
        category="cfp",
        url="https://example.com/cfp/456",
        description="Call for papers for the annual Philosophy of Technology conference. Topics include ethics of AI, digital humanities, posthumanism.",
        venue="Society for Philosophy of Technology",
        event_type="conference",
        submission_deadline=datetime.utcnow() + timedelta(days=30),
        is_virtual=True,
        score=90.0,
        matched_keywords=["philosophy of technology", "digital humanities", "posthumanism", "ethics of technology"],
    )

    console.print("[bold]Testando alertas...[/bold]")
    alert_mgr.send_alerts([test_job, test_cfp], channel="both")
    console.print("[green]✓ Teste concluído (verifique Telegram/email)[/green]")


def export_csv(stores, output: str, days: int = 30, min_score: float = 0, category: str = None, track: str = None):
    """Exporta items para CSV. `stores` pode ser uma ItemStore ou lista (2 bancos)."""
    import csv
    if isinstance(stores, ItemStore):
        stores = [stores]
    academic = (track in ("bolsa", "publicacao", "evento")
                or (category not in (None, "all", "job")))
    items, seen = [], set()
    for st in stores:
        for it in st.get_recent_items(days=days, min_score=min_score, category=category,
                                      track=None if track in (None, "all") else track,
                                      posted_age=not academic):
            if it.url_hash in seen:
                continue
            seen.add(it.url_hash)
            items.append(it)

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "score", "category", "track", "language", "deadline_status",
            "title", "source", "venue", "company",
            "location", "remote", "url", "posted_at", "deadline", "submission_deadline",
            "event_type", "is_virtual", "tags", "matched_keywords"
        ])
        for item in items:
            venue = getattr(item, 'venue', '')
            company = getattr(item, 'company', '')
            remote = getattr(item, 'remote', False)
            deadline = getattr(item, 'deadline_at', None)
            sub_deadline = getattr(item, 'submission_deadline', None)
            event_type = getattr(item, 'event_type', '')
            is_virtual = getattr(item, 'is_virtual', False)

            writer.writerow([
                item.score, item.category, getattr(item, 'track', ''),
                item.language, getattr(item, 'deadline_status', ''),
                item.title, item.source, venue, company,
                item.location, "Sim" if remote else "Não", item.url,
                item.posted_at.isoformat() if item.posted_at else "",
                deadline.isoformat() if deadline else "",
                sub_deadline.isoformat() if sub_deadline else "",
                event_type, "Sim" if is_virtual else "Não",
                ";".join(item.tags), ";".join(item.matched_keywords)
            ])

    console.print(f"[green]✓ Exportado {len(items)} itens para {output}[/green]")


def cmd_audit():
    """Mostra precisão por fonte e os motivos de rejeição mais comuns."""
    from feedback import get_feedback_store
    fb = get_feedback_store()

    for store, titulo in ((get_jobs_store(), "Vagas"),
                          (get_academic_store(), "Acadêmico")):
        stats = store.get_stats()
        console.print(f"[bold cyan]📊 {titulo}: {stats['total_items']} itens, "
                      f"{stats['alerted']} alertados[/bold cyan]")
        table = Table()
        table.add_column("Fonte")
        table.add_column("Itens", justify="right")
        table.add_column("Score médio", justify="right")
        for source, qtd in sorted(stats["by_source"].items(),
                                  key=lambda x: -x[1])[:20]:
            table.add_row(source, str(qtd), str(stats["avg_score"]))
        console.print(table)

    console.print("\n[bold cyan]🎯 Precisão por fonte (feedback da webview)[/bold cyan]")
    table = Table()
    table.add_column("Fonte")
    table.add_column("Alertados", justify="right")
    table.add_column("✓", justify="right")
    table.add_column("✗", justify="right")
    table.add_column("Precisão", justify="right")
    for row in fb.precision_by_source():
        table.add_row(row["source"], str(row["alerted"]), str(row["relevant"]),
                      str(row["irrelevant"]),
                      f"{row['precision']}%" if row["precision"] is not None else "—")
    console.print(table)

    console.print("\n[bold cyan]🚫 Rejeições mais comuns[/bold cyan]")
    from collections import Counter
    rejections = Counter()
    for store in (get_jobs_store(), get_academic_store()):
        for item in store.get_all_items():
            if item.score < 0 and item.matched_keywords:
                rejections[item.matched_keywords[0]] += 1
    for reason, qtd in rejections.most_common(12):
        console.print(f"  {qtd:5d}  {reason}")


def cmd_simulate():
    """Prévia exata do que seria enviado por e-mail agora (sem enviar)."""
    for store, titulo, kind in (
        (get_jobs_store(), "Vagas", "job"),
        (get_academic_store(), "Acadêmico", "academic"),
    ):
        min_score = CONFIG["filters"]["min_score_alert"]
        itens = store.get_unalerted_items(min_score=min_score, kind=kind)
        items_to_send = [i for i in itens if i.score >= min_score]
        console.print(f"[bold cyan]📧 {titulo}: {len(items_to_send)} item(ns) "
                      f"seriam enviados (score ≥ {min_score})[/bold cyan]")
        for item in items_to_send[:25]:
            console.print(f"  • {item.score:5.1f}  {item.title[:70]} "
                          f"[dim]({item.source})[/dim]")
        if len(items_to_send) > 25:
            console.print(f"  ... e mais {len(items_to_send) - 25}")


def cmd_reprocess(apply: bool = False):
    """Reaplica os filtros atuais aos itens já salvos nos bancos."""
    from feedback import get_feedback_store
    fb = get_feedback_store()
    changed = 0
    total = 0
    for store in (get_jobs_store(), get_academic_store()):
        for item in store.get_all_items():
            total += 1
            old = item.score
            score_item(item)
            if item.score != old:
                changed += 1
                fb.record(item, "rejected" if item.score < 0 else "kept",
                          item.matched_keywords[0] if item.matched_keywords else "")
                if apply:
                    store.upsert_item(item)
    console.print(f"[green]{'Aplicado' if apply else 'Simulado'}: "
                  f"{changed}/{total} itens mudariam de score[/green]")
    if not apply:
        console.print("[dim]Use --apply para gravar as novas pontuações.[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Job & Academic Pipeline - Vagas remotas + CFPs/Eventos em Humanidades Digitais, Filosofia da Tecnologia, Divulgação Científica",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Comandos principais:
  jobs collect     Coleta apenas vagas de emprego
  jobs alert       Envia alertas de vagas
  jobs digest      Mostra digest de vagas
  academic collect Coleta apenas CFPs/eventos acadêmicos
  academic alert   Envia alertas de CFPs/eventos
  academic digest  Mostra digest de CFPs/eventos
  academic deadlines Mostra prazos de submissão próximos (qualquer trilho)
  stats            Estatísticas gerais
  export           Exporta para CSV
  test-alerts      Testa configuração de alertas
        """
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log verboso")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # JOBS subcommands
    jobs_parser = subparsers.add_parser("jobs", help="Comandos para vagas de emprego")
    jobs_sub = jobs_parser.add_subparsers(dest="jobs_command", required=True)

    jobs_collect = jobs_sub.add_parser("collect", help="Coleta vagas de emprego")
    jobs_alert = jobs_sub.add_parser("alert", help="Envia alertas de vagas")
    jobs_alert.add_argument("--channel", choices=["telegram", "email", "both"], default="both")
    jobs_digest = jobs_sub.add_parser("digest", help="Mostra digest de vagas")
    jobs_digest.add_argument("-d", "--days", type=int, default=7)
    jobs_digest.add_argument("--min-score", type=float)

    # ACADEMIC subcommands
    academic_parser = subparsers.add_parser("academic", help="Comandos para CFPs/eventos acadêmicos")
    academic_sub = academic_parser.add_subparsers(dest="academic_command", required=True)

    academic_collect = academic_sub.add_parser("collect", help="Coleta CFPs/eventos acadêmicos")
    academic_alert = academic_sub.add_parser("alert", help="Envia alertas de CFPs/eventos")
    academic_alert.add_argument("--channel", choices=["telegram", "email", "both"], default="both")
    academic_digest = academic_sub.add_parser("digest", help="Mostra digest de CFPs/eventos")
    academic_digest.add_argument("-d", "--days", type=int, default=7)
    academic_digest.add_argument("--min-score", type=float)
    academic_deadlines = academic_sub.add_parser("deadlines", help="Mostra CFPs com deadlines próximas")
    academic_deadlines.add_argument("-d", "--days", type=int, default=30)

    # Stats
    subparsers.add_parser("stats", help="Estatísticas dos dois bancos (jobs + academic)")

    # Export
    export_parser = subparsers.add_parser("export", help="Exporta para CSV")
    export_parser.add_argument("-o", "--output", default="items_export.csv")
    export_parser.add_argument("-d", "--days", type=int, default=30)
    export_parser.add_argument("--min-score", type=float, default=0)
    export_parser.add_argument("--category", choices=["job", "cfp", "event", "conference", "workshop", "all"], default="all")
    export_parser.add_argument("--track", choices=["bolsa", "publicacao", "evento", "all"], default="all")
    export_parser.add_argument("--db", choices=["jobs", "academic", "all"], default="all",
                               help="Banco de origem (default: ambos)")

    # Calibração / auditoria
    subparsers.add_parser("audit", help="Precisão por fonte e motivos de rejeição")
    subparsers.add_parser("simulate", help="Prévia do que seria alertado (sem enviar)")
    reprocess_parser = subparsers.add_parser(
        "reprocess", help="Reaplica filtros aos itens já salvos")
    reprocess_parser.add_argument("--apply", action="store_true",
                                  help="Grava as novas pontuações no banco")

    # Test alerts
    subparsers.add_parser("test-alerts", help="Testa configuração de alertas")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Bancos separados: vagas/estágios → jobs.db, bolsas/eventos → academic.db
    if args.command == "jobs":
        store = get_jobs_store()
    elif args.command == "academic":
        store = get_academic_store()
    else:
        store = None  # stats/export resolvem os bancos abaixo

    try:
        if args.command == "jobs":
            if args.jobs_command == "collect":
                console.print("[bold cyan]💼 Coletando vagas de emprego...[/bold cyan]")
                new_jobs = run_job_collection(store, args.verbose)
                console.print(f"[green]Coleta finalizada: {len(new_jobs)} vagas novas[/green]")
            elif args.jobs_command == "alert":
                run_alerts(store, args.channel, "job")
            elif args.jobs_command == "digest":
                show_digest(store, args.days, args.min_score, "job")

        elif args.command == "academic":
            if args.academic_command == "collect":
                console.print("[bold cyan]🎓 Coletando CFPs/eventos acadêmicos...[/bold cyan]")
                new_items = run_academic_collection(store, args.verbose)
                console.print(f"[green]Coleta finalizada: {len(new_items)} itens novos[/green]")
            elif args.academic_command == "alert":
                run_alerts(store, args.channel, kind="academic")
            elif args.academic_command == "digest":
                show_academic_digest(store, args.days, args.min_score)
            elif args.academic_command == "deadlines":
                show_deadlines(store, args.days)

        elif args.command == "stats":
            show_stats(get_jobs_store(), "Vagas/Estágios")
            console.print()
            show_stats(get_academic_store(), "Acadêmico (bolsas/eventos)")
        elif args.command == "export":
            cat = None if args.category == 'all' else args.category
            stores = []
            if args.db in ("jobs", "all"):
                stores.append(get_jobs_store())
            if args.db in ("academic", "all"):
                stores.append(get_academic_store())
            export_csv(stores, args.output, args.days, args.min_score, cat, args.track)
        elif args.command == "audit":
            cmd_audit()
        elif args.command == "simulate":
            cmd_simulate()
        elif args.command == "reprocess":
            cmd_reprocess(args.apply)
        elif args.command == "test-alerts":
            test_alerts()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrompido pelo usuário[/yellow]")
        sys.exit(1)
    except Exception as e:
        logger.exception("Erro fatal")
        console.print(f"[red]Erro: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
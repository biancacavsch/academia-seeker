"""Alert system - Telegram and Email."""

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Union
from datetime import datetime

from models import Job, AcademicItem, BaseItem
from config import CONFIG

logger = logging.getLogger(__name__)


class AlertManager:
    def __init__(self):
        self.telegram_cfg = CONFIG["alerts"].get("telegram", {})
        self.email_cfg = CONFIG["alerts"].get("email", {})
        self._bot = None

    def send_alerts(self, items: List[BaseItem], channel: str = "both",
                    to_email: str = "") -> set:
        """Envia alertas. Retorna o set de url_hash que FALHARAM enviar.

        O chamador só marca como alertado o que não está nesse set — caso
        contrário itens de um lote grande (backlog) se perderiam sem chegar
        ao destinatário.
        """
        if not items:
            logger.info("No items to alert")
            return set()

        failed = set()
        if channel in ("telegram", "both") and self.telegram_cfg.get("enabled"):
            failed |= asyncio.run(self._send_telegram(items))

        if channel in ("email", "both") and self.email_cfg.get("enabled"):
            self._send_email(items, to_email=to_email)

        return failed

    async def _send_telegram(self, items: List[BaseItem]) -> set:
        try:
            from telegram import Bot
            from telegram.error import RetryAfter, TelegramError
        except ImportError:
            logger.warning("python-telegram-bot not installed, skipping Telegram")
            return set()

        token = self.telegram_cfg.get("bot_token")
        chat_id = self.telegram_cfg.get("chat_id")
        if not token or not chat_id:
            logger.warning("Telegram credentials not configured")
            return set()

        bot = Bot(token=token)
        failed = set()
        for item in items:
            message = self._format_item_telegram(item)
            for attempt in range(3):
                try:
                    await bot.send_message(chat_id=chat_id, text=message,
                                           parse_mode="HTML")
                    logger.info(f"Telegram alert sent for: {item.title[:50]}")
                    break
                except RetryAfter as e:
                    # Flood control: lotes grandes (backlog) disparam RetryAfter.
                    # Espera e reenvia — sem isso o item se perderia.
                    logger.warning(f"Telegram flood control, aguardando {e.retry_after}s")
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramError as e:
                    logger.error(f"Telegram send failed for {item.title[:40]}: {e}")
                    failed.add(item.url_hash)
                    break
            else:
                logger.error(f"Telegram: desistiu de {item.title[:40]} após 3 tentativas")
                failed.add(item.url_hash)
        if failed:
            logger.error(f"{len(failed)} alertas do Telegram não enviados")
        return failed

    def _send_email(self, items: List[BaseItem], to_email: str = ""):
        host = self.email_cfg.get("smtp_host")
        port = self.email_cfg.get("smtp_port", 587)
        user = self.email_cfg.get("smtp_user")
        password = self.email_cfg.get("smtp_pass")
        from_email = self.email_cfg.get("from_email")
        # Destinatário do levantamento tem prioridade; vazio usa o global.
        to_email = (to_email or "").strip() or self.email_cfg.get("to_email")

        if not all([host, port, user, password, from_email, to_email]):
            logger.warning("Email credentials not fully configured")
            return

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"🎯 {len(items)} New Matches - {datetime.now().strftime('%Y-%m-%d')}"
            msg["From"] = from_email
            msg["To"] = to_email

            html = self._format_items_html(items)
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(user, password)
                server.send_message(msg)

            logger.info(f"Email alert sent with {len(items)} items")
        except Exception as e:
            logger.error(f"Email send failed: {e}")

    def _format_item_telegram(self, item: BaseItem) -> str:
        cat_emoji = {"job": "💼", "cfp": "📄", "event": "📅", "conference": "🎪", "workshop": "🔧", "symposium": "🎓", "fellowship": "🎓"}.get(item.category, "📋")
        tags_str = f" 🏷️ {', '.join(item.tags[:5])}" if item.tags else ""
        matched = f" ✅ {', '.join(item.matched_keywords[:5])}" if item.matched_keywords else ""

        section_header = ""
        if isinstance(item, AcademicItem):
            from models import academic_section
            _order, label = academic_section(item)
            section_header = f"<i>{label}</i>\n"

        extra = ""
        if isinstance(item, Job):
            salary_str = f" 💰 {item.salary_text}" if item.salary_text else ""
            extra = f"🏢 {item.company} | 📍 {item.location} {'🌐' if item.remote else ''}{salary_str}"
        elif isinstance(item, AcademicItem):
            venue = f" 🏛️ {item.venue}" if item.venue else ""
            deadline = ""
            if item.submission_deadline:
                deadline = f" 📅 Sub: {item.submission_deadline.strftime('%d/%m/%Y')}"
            elif item.deadline_at:
                deadline = f" ⏰ {item.deadline_at.strftime('%d/%m/%Y')}"
            virtual = " 🌐" if item.is_virtual else ""
            extra = f"{venue}{deadline}{virtual}"

        posted_str = ""
        if item.posted_at:
            try:
                posted_str = f"\n📰 Publicado em: {item.posted_at.strftime('%d/%m/%Y')}"
            except Exception:
                pass

        return (
            f"{section_header}{cat_emoji} <b>{item.title}</b>\n"
            f"{extra}\n"
            f"📊 Score: <b>{item.score}</b>{tags_str}\n"
            f"{matched}{posted_str}\n"
            f"🔗 <a href='{item.url}'>Ver detalhes</a>"
        )

    def _format_items_html(self, items: List[BaseItem]) -> str:
        from models import academic_section
        rows = []
        last_section = None
        academic_only = bool(items) and all(isinstance(i, AcademicItem) for i in items)
        for item in items:
            if academic_only:
                _order, label = academic_section(item)
                if label != last_section:
                    rows.append(f"<tr><td style='padding:10px 12px;background:#f1f5f9'>"
                                f"<b>{label}</b></td></tr>")
                    last_section = label
            cat_emoji = {"job": "💼", "cfp": "📄", "event": "📅", "conference": "🎪", "workshop": "🔧", "symposium": "🎓", "fellowship": "🎓"}.get(item.category, "📋")
            cat_color = {"job": "#1a73e8", "cfp": "#e65100", "event": "#43a047", "conference": "#7b1fa2", "workshop": "#fb8c00"}.get(item.category, "#333")

            tags_str = f"<span style='color:#666'>{', '.join(item.tags[:5])}</span>" if item.tags else ""
            matched = f"<span style='color:#1565c0'>{', '.join(item.matched_keywords[:5])}</span>" if item.matched_keywords else ""
            posted_html = ""
            if item.posted_at:
                try:
                    posted_html = f"<br><small style='color:#888'>📰 Publicado em: {item.posted_at.strftime('%d/%m/%Y')}</small>"
                except Exception:
                    pass

            if isinstance(item, Job):
                salary_str = f"<span style='color:#2e7d32'>{item.salary_text}</span>" if item.salary_text else ""
                extra = f"<span style='color:#555'>{item.company}</span> | <span style='color:#555'>{item.location}</span> {'🌐' if item.remote else ''}{salary_str}"
            elif isinstance(item, AcademicItem):
                venue = f"<span style='color:#555'>{item.venue}</span>" if item.venue else ""
                deadline = ""
                if item.submission_deadline:
                    deadline = f" <span style='color:#c62828'>📅 Sub: {item.submission_deadline.strftime('%d/%m/%Y')}</span>"
                elif item.deadline_at:
                    deadline = f" <span style='color:#c62828'>⏰ {item.deadline_at.strftime('%d/%m/%Y')}</span>"
                virtual = " <span style='color:#1565c0'>🌐</span>" if item.is_virtual else ""
                extra = f"{venue}{deadline}{virtual}"
            else:
                extra = ""

            rows.append(f"""
                <tr style='border-bottom:1px solid #eee'>
                    <td style='padding:12px'>
                        <span style='background:{cat_color};color:white;padding:2px 6px;border-radius:3px;font-size:11px'>{cat_emoji} {item.category.upper()}</span>
                        <a href='{item.url}' style='color:#1a73e8;text-decoration:none;font-weight:600;font-size:16px;margin-left:8px'>
                            {item.title}
                        </a><br>
                        {extra}<br>
                        <span style='color:#2e7d32;font-weight:bold'>Score: {item.score}</span>
                        {tags_str}<br>
                        <small>{matched}</small>{posted_html}
                    </td>
                </tr>
            """)

        return f"""
            <html><body style='font-family:Arial,sans-serif;max-width:700px;margin:0 auto;padding:20px'>
                <h2 style='color:#1a73e8'>🎯 {len(items)} Novos Matches (Vagas + CFPs/Eventos)</h2>
                <p style='color:#666'>{datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                <table style='width:100%;border-collapse:collapse'>
                    {''.join(rows)}
                </table>
                <hr style='margin-top:30px'>
                <p style='color:#999;font-size:12px'>
                    Job & Academic Pipeline - Humanidades Digitais, Filosofia da Tecnologia, Divulgação Científica<br>
                    <a href='https://github.com'>Ver no GitHub</a>
                </p>
            </body></html>
        """

    def send_digest(self, items: List[BaseItem]):
        """Envia digest diário/semanal."""
        if self.telegram_cfg.get("enabled"):
            self._send_telegram(items)
        if self.email_cfg.get("enabled"):
            self._send_email(items)
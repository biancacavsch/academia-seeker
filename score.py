"""Scoring engine for job and academic item relevance."""

import re
from datetime import datetime, timedelta
from typing import Set
from langdetect import detect, LangDetectException

from models import Job, AcademicItem, BaseItem
from config import CONFIG


class Scorer:
    def __init__(self):
        self.config = CONFIG["keywords"]
        self.filters = CONFIG["filters"]

        # Compila regex patterns para busca case-insensitive
        self._compile_patterns()

    def _compile_patterns(self):
        self.patterns = {
            "core": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                     for kw in self.config["core"]],
            "scicomm": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                        for kw in self.config["scicomm"]],
            "glam": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                     for kw in self.config["glam"]],
            "education": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                          for kw in self.config["education_fit"]],
            # Termos nucleares simples (alto recall)
            "broad": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                      for kw in self.config.get("broad", [])],
            # Academic-specific keywords
            "philosophy_tech": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                                for kw in self.config.get("philosophy_tech", [])],
            "digital_humanities": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                                   for kw in self.config.get("digital_humanities", [])],
            "cfp_specific": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                             for kw in self.config.get("cfp_specific", [])],
            # Estágio / internship (nível + perfil + home office)
            "estagio": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                        for kw in self.config.get("estagio", [])],
            "negatives": [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                          for kw in self.config["negatives"]],
        }

        # ---- Gates rígidos (config → filters) ----
        interests = self.filters.get("interests", []) or []
        # Palavra ÚNICA só vale no título/tags (evita "ótima comunicação"
        # em vaga fora de escopo); EXPRESSÃO vale no texto completo.
        self.interest_single = [
            (kw, re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE))
            for kw in interests if " " not in kw]
        self.interest_phrase = [
            (kw, re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE))
            for kw in interests if " " in kw]
        self.exclude_pats = [
            (kw, re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE))
            for kw in self.filters.get("exclude_areas", []) or []]
        self.onsite_pats = [
            re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            for kw in self.filters.get("onsite_markers", []) or []]
        self.remote_strong_pats = [
            re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            for kw in self.filters.get("remote_strong_markers", []) or []]

        # Listicle/guia de vagas — match no título (rejeita páginas de listagem)
        self.job_guide_pats = [
            re.compile(re.escape(m), re.IGNORECASE)
            for m in (
                "best ", "top ", "list of ", "jobs for students", "huge list",
                "discover internships", "internship listings", "internship listing",
                "remote internship jobs", "opportunities for students",
                "work at home jobs", "getting hired", "internships open this week",
                "paid opportunities for students", "vagas 100%",
            )]

        # Notícia de portal (não é chamada) — aplica a todos os coletores acadêmicos
        try:
            from collectors.search_academic import (
                NEWS_TITLE_MARKERS, CALL_TITLE_MARKERS)
        except Exception:
            NEWS_TITLE_MARKERS, CALL_TITLE_MARKERS = (), ()
        self.news_title_pats = [
            re.compile(re.escape(m), re.IGNORECASE)
            for m in NEWS_TITLE_MARKERS]
        self.call_title_pats = [
            re.compile(re.escape(m), re.IGNORECASE)
            for m in CALL_TITLE_MARKERS]

    def _in_interests(self, strong_hay: str, full_text: str) -> bool:
        """True se a vaga bate com ao menos UM termo da allow-list.

        Tanto termos únicos quanto expressões são checados SOMENTE no
        título/tags/localização (strong_hay) — nunca na descrição livre,
        para não deixar listicles ("best remote jobs...") entrarem só
        porque mencionam "social media" no corpo do texto.
        """
        if not (self.interest_single or self.interest_phrase):
            return True  # sem lista configurada → não filtra
        for _kw, pat in self.interest_single:
            if pat.search(strong_hay):
                return True
        for _kw, pat in self.interest_phrase:
            if pat.search(strong_hay):
                return True
        return False

    def detect_language(self, text: str) -> str:
        try:
            lang = detect(text)
            return lang if lang in self.filters["languages"] else "other"
        except LangDetectException:
            return "unknown"

    def _find_matches(self, text: str, patterns: list[re.Pattern]) -> Set[str]:
        matches = set()
        for pat in patterns:
            for m in pat.finditer(text):
                matches.add(m.group(0).lower())
        return matches

    def _reject(self, item: BaseItem, reason: str) -> tuple[float, list[str]]:
        """Rejeição que também grava o estado no item (senão o score antigo persiste)."""
        item.score = -1000.0
        item.matched_keywords = [reason]
        return item.score, item.matched_keywords

    def score(self, item: BaseItem) -> tuple[float, list[str]]:
        """Retorna (score, matched_keywords). Works for both Job and AcademicItem."""
        title = item.title or ""
        desc = item.description or ""
        tags_text = " ".join(item.tags) if item.tags else ""
        full_text = f"{title} {desc} {tags_text}"

        # Filtro de idioma
        lang = self.detect_language(full_text)
        item.language = lang

        # ---- Gates rígidos de VAGA (vaga precisa estar no escopo) ----
        if isinstance(item, Job):
            hay_tl = f"{title} {item.location or ''}".lower()
            # 1) área excluída no título/localização → rejeição imediata
            for kw, pat in self.exclude_pats:
                if pat.search(hay_tl):
                    return self._reject(item, f"filtered: off-topic ({kw})")
            # 2) allow-list de interesses (marketing, HD, divulgação, etc.)
            if not self._in_interests(hay_tl, full_text.lower()):
                return self._reject(item, "filtered: not in interests")
            # 3) remote_only: presencial é rejeitado MESMO com flag remote=1
            if self.filters.get("remote_only"):
                strong = any(p.search(hay_tl) for p in self.remote_strong_pats)
                onsite = any(p.search(full_text) for p in self.onsite_pats)
                if onsite and not strong:
                    return self._reject(item, "filtered: on-site only")
                # flag remote OU localização/título remoto (sem flag) → ok
                if not (item.remote or strong):
                    return self._reject(item, "filtered: not remote")

        if lang not in self.filters["languages"] and lang != "unknown":
            return self._reject(item, f"filtered: language {lang}")

        # Filtro de idade (max_job_age_days) — SÓ para vagas.
        # Itens acadêmicos são regidos pela data de fechamento (pré-requisito
        # de edital aberto): um CFP postado há 2 meses com deadline futura
        # continua válido; sem posted_at, mantém.
        max_age = self.filters.get("max_job_age_days", 30)
        if isinstance(item, Job) and item.posted_at is not None:
            try:
                posted = item.posted_at.replace(tzinfo=None)
                if (datetime.utcnow() - posted).days > max_age:
                    return self._reject(item, f"filtered: older than {max_age}d")
            except Exception:
                pass

        # Pré-requisito de edital aberto (só itens acadêmicos)
        if isinstance(item, AcademicItem):
            from deadlines import compute_deadline_status
            closing = item.submission_deadline or item.deadline_at
            item.deadline_status = compute_deadline_status(
                closing, f"{item.title} {item.description}")
            if item.deadline_status == "closed":
                return self._reject(item, "filtered: closed deadline")

            # Bolsa: a usuária já está no mestrado → remove PROGRAMAS de
            # mestrado (ingresso/vagas). Doutorado, pós-doc, IC, intercâmbio
            # e bolsas de pesquisa continuam elegíveis.
            if item.track == "bolsa" or item.category == "bolsa":
                t = f"{title} {desc}".lower()
                has_master = bool(re.search(
                    r"\bmestrad[oa]s?\b|\bmaestr[íi]a?s?\b|\bmaestrias\b|"
                    r"\bmaster'?s?\b|\bmasters\b|\bmaster degree\b|"
                    r"joint master|\berasmus mundus\b", t))
                has_higher = bool(re.search(
                    r"\bdoutorad[oa]s?\b|\bdoctorad[oa]s?\b|\bdoctoral\b|"
                    r"\bdoctorate\b|\bph\.?d\b|\bpre-?doctoral\b|"
                    r"\bp[óo]s-?doutorad[oa]s?\b|\bpost-?doc\b|"
                    r"\binicia[çc][ãa]o\s+cient[íi]fica\b", t))
                has_undergrad = bool(re.search(
                    r"\bgradua[çc][ãa]o\b|\bundergrad|\blicenciatura\b|"
                    r"\bbacharelado\b", t))
                if has_master and not has_higher:
                    return self._reject(item, "filtered: master's program")
                if has_undergrad and not (has_master or has_higher):
                    return self._reject(item, "filtered: undergrad program")

            # Notícia de portal (g1 etc.) — não é chamada/edital aberto
            tl = (item.title or "").lower()
            if any(p.search(tl) for p in self.news_title_pats) and \
                    not any(p.search(tl) for p in self.call_title_pats):
                return self._reject(item, "filtered: news")

            # Listicle/guia de vagas ("best remote jobs", "internship listings",
            # "jobs for students", etc.) — não é uma vaga específica
            if isinstance(item, Job):
                for p in self.job_guide_pats:
                    if p.search(tl):
                        return self._reject(item, "filtered: job listing/guide")

        # Gate final de oportunidade / blocklists (configurável pela webview).
        # Fica depois dos gates históricos para preservar os motivos já
        # conhecidos nos testes e nos logs ("not in interests", etc.).
        from relevance import check_opportunity
        ok, reason = check_opportunity(item)
        if not ok:
            return self._reject(item, reason)

        all_matches = []
        score = 0.0

        # Core DH (peso alto)
        core_matches = self._find_matches(full_text, self.patterns["core"])
        if core_matches:
            title_core = self._find_matches(title, self.patterns["core"])
            score += len(title_core) * self.config["high_weight"]
            score += (len(core_matches) - len(title_core)) * self.config["medium_weight"]
            all_matches.extend(core_matches)

        # Science communication
        scicomm_matches = self._find_matches(full_text, self.patterns["scicomm"])
        if scicomm_matches:
            title_scicomm = self._find_matches(title, self.patterns["scicomm"])
            score += len(title_scicomm) * self.config["high_weight"]
            score += (len(scicomm_matches) - len(title_scicomm)) * self.config["medium_weight"]
            all_matches.extend(scicomm_matches)

        # GLAM
        glam_matches = self._find_matches(full_text, self.patterns["glam"])
        if glam_matches:
            score += len(glam_matches) * self.config["medium_weight"]
            all_matches.extend(glam_matches)

        # Education fit
        edu_matches = self._find_matches(full_text, self.patterns["education"])
        if edu_matches:
            score += len(edu_matches) * self.config["low_weight"]
            all_matches.extend(edu_matches)

        # Termos nucleares simples: título pesa médio, resto da descrição pesa baixo
        # (controla ruído de palavras comuns como "education" em qualquer anúncio)
        if self.patterns["broad"]:
            broad_title = self._find_matches(title, self.patterns["broad"])
            broad_rest = self._find_matches(f"{desc} {tags_text}", self.patterns["broad"]) - broad_title
            score += len(broad_title) * self.config["medium_weight"]
            score += len(broad_rest) * self.config["low_weight"]
            all_matches.extend(broad_title | broad_rest)

        # Philosophy of technology
        phil_matches = self._find_matches(full_text, self.patterns["philosophy_tech"])
        if phil_matches:
            title_phil = self._find_matches(title, self.patterns["philosophy_tech"])
            score += len(title_phil) * self.config["high_weight"]
            score += (len(phil_matches) - len(title_phil)) * self.config["medium_weight"]
            all_matches.extend(phil_matches)

        # Digital humanities specific
        dh_matches = self._find_matches(full_text, self.patterns["digital_humanities"])
        if dh_matches:
            score += len(dh_matches) * self.config["medium_weight"]
            all_matches.extend(dh_matches)

        # CFP specific (call for papers, submission, deadline, etc.)
        cfp_matches = self._find_matches(full_text, self.patterns["cfp_specific"])
        if cfp_matches:
            score += len(cfp_matches) * self.config.get("cfp_weight", 20)
            all_matches.extend(cfp_matches)

        # Estágio / internship (nível, perfil e home office) — só para vagas
        if self.patterns["estagio"] and isinstance(item, Job):
            est_matches = self._find_matches(full_text, self.patterns["estagio"])
            if est_matches:
                title_est = self._find_matches(title, self.patterns["estagio"])
                score += len(title_est) * self.config["high_weight"]
                score += (len(est_matches) - len(title_est)) * self.config["medium_weight"]
                all_matches.extend(est_matches)

        # Bonus for academic items with upcoming deadlines
        if isinstance(item, AcademicItem) and item.submission_deadline:
            days_until = (item.submission_deadline - datetime.utcnow()).days
            if 0 <= days_until <= 30:
                score += 15  # Bonus for near deadlines
                all_matches.append(f"deadline_in_{days_until}d")
            elif 30 < days_until <= 60:
                score += 5
                all_matches.append(f"deadline_in_{days_until}d")

        # Virtual/hybrid bonus for academic events
        if isinstance(item, AcademicItem) and item.is_virtual:
            score += 10
            all_matches.append("virtual")

        # Negativos
        neg_matches = self._find_matches(full_text, self.patterns["negatives"])
        if neg_matches:
            score += len(neg_matches) * self.config["negative_weight"]
            all_matches.extend([f"NEG:{m}" for m in neg_matches])

        # Normaliza: score mínimo 0 para não filtrados
        if score < 0 and not neg_matches:
            score = 0

        item.score = round(score, 1)
        item.matched_keywords = sorted(set(all_matches))
        return item.score, item.matched_keywords


def score_item(item: BaseItem) -> BaseItem:
    scorer = Scorer()
    scorer.score(item)
    return item
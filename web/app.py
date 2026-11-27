"""Webview do academia-seeker — flask app."""

import csv
import io
import os
from pathlib import Path

from flask import (
    Flask, Response, flash, redirect, render_template, request, session, url_for,
)

from config import CONFIG, load_config
from store import get_jobs_store, get_academic_store
from feedback import get_feedback_store
from web import auth
from web import services
from web import settings
from web import survey_forms
from surveys import active_ids, list_surveys

BASE = Path(__file__).parent


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(BASE / "templates"),
                static_folder=str(BASE / "static"), static_url_path="/static")
    app.secret_key = auth.secret_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    auth.init_app(app)

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", message=str(e)), 400

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user"):
            return redirect(url_for("dashboard"))
        message = ""
        if not auth.configured():
            message = ("Senha não configurada. Defina WEB_PASSWORD_HASH (ou WEB_PASSWORD) "
                       "no .env e reinicie o serviço academia-seeker-web.")
        if request.method == "POST":
            ip = getattr(request, "remote_addr", "") or "?"
            if auth.rate_limited(ip):
                message = "Muitas tentativas. Aguarde 5 minutos."
            elif auth.check_password(request.form.get("password", "")):
                auth.reset_rate(ip)
                session.clear()
                session["user"] = os.getenv("WEB_USER", "bianca")
                nxt = request.args.get("next", "")
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = url_for("dashboard")
                return redirect(nxt)
            else:
                message = "Senha incorreta."
        return render_template("login.html", message=message)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @auth.login_required
    def dashboard():
        jobs = get_jobs_store().get_stats()
        acad = get_academic_store().get_stats()
        state = services.service_state()
        timer = services.timer_state()
        fb = get_feedback_store()
        recent = []
        for store in (get_jobs_store(), get_academic_store()):
            rows, _ = store.get_items_page(6, 0, order="recent")
            recent.extend((item, alerted, "vaga" if item.category == "job" else "acadêmico")
                          for item, alerted in rows)
        recent.sort(key=lambda r: str(r[0].posted_at or getattr(r[0], "first_seen_at", "") or ""),
                    reverse=True)
        deadlines = get_academic_store().get_upcoming_deadlines(days=30)
        return render_template(
            "dashboard.html", jobs=jobs, acad=acad, state=state, timer=timer,
            recent=recent[:8], deadlines=deadlines[:6],
            precision=fb.precision_by_source(), schedule=load_config().get("schedule", {}),
        )

    @app.route("/levantamentos/<scope>", methods=["GET", "POST"])
    @auth.login_required
    def levantamentos(scope: str):
        if scope not in ("academic", "professional"):
            return render_template("error.html", message="Escopo inválido"), 404
        edit_id = request.args.get("editar", "")
        success = True
        if request.method == "POST":
            action = request.form.get("action", "save")
            success, errors = survey_forms.apply_form(request.form, scope)
            for e in errors:
                flash(e, "ok" if success else "error")
            if success:
                if action == "activate":
                    flash(f"Levantamento '{request.form.get('survey_id', '')}' ativado.", "ok")
                return redirect(url_for("levantamentos", scope=scope))
        surveys = list_surveys(scope)
        active = next((s for s in surveys if s["active"]), surveys[0] if surveys else None)
        current = next((s for s in surveys if s["id"] == edit_id), active)
        view = survey_forms.editable_paths(scope, sid=current["id"] if current else "")
        title = "Levantamentos acadêmicos" if scope == "academic" else "Levantamentos profissionais"
        return render_template(
            "levantamentos.html", scope=scope, title=title, surveys=surveys,
            active=active, current=current, view=view,
            term_labels=survey_forms.TERM_LABELS,
        )

    @app.route("/itens")
    @auth.login_required
    def items():
        db = request.args.get("db", "academic")
        store = get_jobs_store() if db == "jobs" else get_academic_store()
        q = request.args.get("q", "").strip()
        source = request.args.get("source", "")
        category = request.args.get("category", "")
        track = request.args.get("track", "")
        min_score = request.args.get("min_score", "0")
        try:
            min_score = float(min_score)
        except ValueError:
            min_score = 0.0
        order = request.args.get("order", "score")
        survey_id = request.args.get("survey", "")
        page = max(1, int(request.args.get("page", 1) or 1))
        per = 20
        rows, total = store.get_items_page(
            per, (page - 1) * per, q=q, source=source, category=category,
            track=track, survey_id=survey_id, min_score=min_score, order=order)
        return render_template(
            "items.html", db=db, rows=rows, total=total, page=page,
            per=per, pages=max(1, (total + per - 1) // per),
            q=q, source=source, category=category, track=track,
            survey_id=survey_id, surveys=list_surveys(db),
            min_score=min_score, order=order, sources=store.get_sources(),
            export_qs=request.query_string.decode(),
        )

    @app.route("/export.csv")
    @auth.login_required
    def export_csv():
        db = request.args.get("db", "academic")
        store = get_jobs_store() if db == "jobs" else get_academic_store()
        rows, _ = store.get_items_page(5000, 0, q=request.args.get("q", ""),
                                       source=request.args.get("source", ""),
                                       min_score=float(request.args.get("min_score") or 0))
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["titulo", "fonte", "categoria", "trilha", "score", "url",
                    "publicado", "prazo", "motivos"])
        for item, _ in rows:
            w.writerow([
                item.title, item.source, item.category, getattr(item, "track", ""),
                item.score, item.url,
                item.posted_at.isoformat() if item.posted_at else "",
                (item.submission_deadline or item.deadline_at or "").isoformat()
                if hasattr(item, "submission_deadline") and
                (item.submission_deadline or item.deadline_at) else "",
                ";".join(item.matched_keywords or []),
            ])
        return Response(out.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{db}_export.csv"'})

    @app.route("/ajustes", methods=["GET", "POST"])
    @auth.login_required
    def ajustes():
        if request.method == "POST":
            overlay, errors = settings.overlay_from_form(request.form)
            if errors:
                for e in errors:
                    flash(e, "error")
            else:
                settings.save_overlay(overlay)
                flash("Ajustes salvos. Válidos na próxima rodada do pipeline.", "ok")
            return redirect(url_for("ajustes"))
        return render_template("ajustes.html", view=settings.editable_view(),
                               presets=settings.PRESETS)

    @app.route("/ajustes/reset", methods=["POST"])
    @auth.login_required
    def ajustes_reset():
        settings.reset_overlay()
        flash("Ajustes restaurados ao config.yaml original.", "ok")
        return redirect(url_for("ajustes"))

    @app.route("/ajustes/aplicar-agenda", methods=["POST"])
    @auth.login_required
    def aplicar_agenda():
        code, out = services.ctl("apply-schedule")
        flash(f"Agenda aplicada. {out}" if code == 0 else f"Falha: {out}",
              "ok" if code == 0 else "error")
        return redirect(url_for("ajustes"))

    @app.route("/rodar", methods=["POST"])
    @auth.login_required
    def rodar():
        code, out = services.ctl("start")
        flash("Coleta iniciada." if code == 0 else f"Falha ao iniciar: {out}",
              "ok" if code == 0 else "error")
        return redirect(url_for("sistema"))

    @app.route("/parar", methods=["POST"])
    @auth.login_required
    def parar():
        code, out = services.ctl("stop")
        flash("Coleta interrompida." if code == 0 else f"Falha ao parar: {out}",
              "ok" if code == 0 else "error")
        return redirect(url_for("sistema"))

    @app.route("/sistema")
    @auth.login_required
    def sistema():
        log, log_name = services.latest_log(80)
        return render_template(
            "sistema.html", state=services.service_state(),
            timer=services.timer_state(), info=services.system_info(),
            neighbors=services.neighbors(), log=log, log_name=log_name,
            schedule=services.schedule_expression(),
        )

    @app.route("/sistema/log")
    @auth.login_required
    def sistema_log():
        log, log_name = services.latest_log(40)
        return render_template("log_partial.html", log=log, log_name=log_name,
                               state=services.service_state())

    @app.route("/revisao", methods=["GET", "POST"])
    @auth.login_required
    def revisao():
        fb = get_feedback_store()
        if request.method == "POST":
            url_hash = request.form.get("url_hash", "")
            label = request.form.get("label", "")
            reason = request.form.get("reason", "")
            if url_hash and label in ("relevant", "irrelevant", "block_domain",
                                      "block_source"):
                for store in (get_jobs_store(), get_academic_store()):
                    item = store.get_item(url_hash)
                    if item:
                        fb.mark(item, label, reason)
                        break
                flash("Feedback registrado.", "ok")
            return redirect(url_for("revisao"))

        min_alert = float(CONFIG["filters"]["min_score_alert"])
        min_digest = float(CONFIG["filters"]["min_score_digest"])
        rows = []
        labels = fb.labels()
        for store in (get_jobs_store(), get_academic_store()):
            items, _ = store.get_items_page(
                60, 0, min_score=min(min_alert, min_digest) - 10, order="recent")
            for item, alerted in items:
                if min_digest <= item.score <= min_alert + 20 and item.url_hash not in labels:
                    rows.append((item, alerted))
        rows.sort(key=lambda r: -r[0].score)
        return render_template("revisao.html", rows=rows[:40],
                               precision=fb.precision_by_source(),
                               has_feedback=bool(fb.labels()),
                               min_alert=min_alert, min_digest=min_digest)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8090)

#!/bin/bash
# run_weekly.sh — Pipeline semanal: vagas + CFPs/eventos + alertas por e-mail
#
# Executado pelo systemd (deploy/academia-seeker.timer) no Raspberry Pi.
# Também pode ser rodado manualmente, a qualquer momento:
#   sudo systemctl start academia-seeker.service
#
# Roda TODOS os levantamentos ligados de cada escopo, cada um com seu próprio
# config e destinatário de e-mail (surveys/*.yaml). Bancos separados:
#   etapas 1-2 -> jobs.db      (vagas/estagios)
#   etapas 3-4 -> academic.db  (bolsas/eventos/chamadas)
# Credenciais (SMTP/Adzuna/Jooble) vem do .env, carregado por config.py.
# Telegram esta desativado em config.yaml (alerts.telegram.enabled: false).
# Logs em logs/weekly_YYYYMMDD_HHMMSS.log (mantidos os 12 mais recentes).

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/weekly_${STAMP}.log"

mkdir -p "$LOG_DIR"

# Evita sobreposicao entre o timer e uma execucao manual.
exec 9>"$PROJECT_DIR/.run_weekly.lock"
if ! flock -n 9; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') | ja em execucao — abortando" >> "$LOG_DIR/weekly_running.log"
  exit 0
fi

cd "$PROJECT_DIR" || exit 1

# Backup semanal dos bancos (retem 60 dias)
BACKUP_DIR="$PROJECT_DIR/backups"
mkdir -p "$BACKUP_DIR"
for db in jobs.db academic.db items.db; do
  if [ -f "$db" ]; then
    cp "$db" "$BACKUP_DIR/${db%.db}_$(date +%Y%m%d).db" 2>/dev/null
  fi
done
find "$BACKUP_DIR" -name "*.db" -mtime +60 -delete 2>/dev/null

# IDs dos levantamentos ligados (cada um tem seus interesses e e-mail).
ACADEMIC_IDS="$("$PYTHON" -c "from surveys import enabled_surveys; print(' '.join(s['id'] for s in enabled_surveys('academic')))" 2>>"$LOG_FILE")"
PROFESSIONAL_IDS="$("$PYTHON" -c "from surveys import enabled_surveys; print(' '.join(s['id'] for s in enabled_surveys('professional')))" 2>>"$LOG_FILE")"
[ -n "$ACADEMIC_IDS" ] || ACADEMIC_IDS="principal"
[ -n "$PROFESSIONAL_IDS" ] || PROFESSIONAL_IDS="principal"

{
  echo "=== Pipeline semanal iniciado em $(date '+%Y-%m-%d %H:%M:%S') ==="
  echo "Levantamentos profissionais: $PROFESSIONAL_IDS"
  echo "Levantamentos academicos: $ACADEMIC_IDS"

  echo "--- [1/4] Coletando vagas ---"
  for sid in $PROFESSIONAL_IDS; do
    echo ">> levantamento profissional '$sid'"
    if "$PYTHON" -m main jobs collect --survey "$sid"; then
      echo "OK: coleta de vagas '$sid' concluida"
    else
      echo "FALHA: coleta de vagas '$sid' (codigo $?)"
    fi
  done

  echo "--- [2/4] Alertas de vagas (email de cada levantamento) ---"
  for sid in $PROFESSIONAL_IDS; do
    echo ">> alertas do levantamento profissional '$sid'"
    if "$PYTHON" -m main jobs alert --channel email --survey "$sid"; then
      echo "OK: alertas de vagas '$sid' enviados"
    else
      echo "FALHA: alertas de vagas '$sid' (codigo $?)"
    fi
  done

  echo "--- [3/4] Coletando CFPs/eventos ---"
  for sid in $ACADEMIC_IDS; do
    echo ">> levantamento academico '$sid'"
    if "$PYTHON" -m main academic collect --survey "$sid"; then
      echo "OK: coleta academica '$sid' concluida"
    else
      echo "FALHA: coleta academica '$sid' (codigo $?)"
    fi
  done

  echo "--- [4/4] Alertas academicos (email de cada levantamento) ---"
  for sid in $ACADEMIC_IDS; do
    echo ">> alertas do levantamento academico '$sid'"
    if "$PYTHON" -m main academic alert --channel email --survey "$sid"; then
      echo "OK: alertas academicos '$sid' enviados"
    else
      echo "FALHA: alertas academicos '$sid' (codigo $?)"
    fi
  done

  echo "=== Pipeline semanal concluido em $(date '+%Y-%m-%d %H:%M:%S') ==="
} >> "$LOG_FILE" 2>&1

# Rotacao: mantem os 12 logs semanais mais recentes
ls -t "$LOG_DIR"/weekly_*.log 2>/dev/null | tail -n +13 | xargs -r rm -f

exit 0

#!/bin/bash
# run_weekly.sh — Pipeline semanal: vagas + CFPs/eventos + alertas por e-mail
#
# Executado pelo systemd (deploy/academia-seeker.timer) no Raspberry Pi.
# Também pode ser rodado manualmente, a qualquer momento:
#   sudo systemctl start academia-seeker.service
#
# Bancos separados (ver config.yaml storage):
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

{
  echo "=== Pipeline semanal iniciado em $(date '+%Y-%m-%d %H:%M:%S') ==="

  echo "--- [1/4] Coletando vagas ---"
  if "$PYTHON" -m main jobs collect; then
    echo "OK: coleta de vagas concluida"
  else
    echo "FALHA: coleta de vagas (codigo $?)"
  fi

  echo "--- [2/4] Alertas de vagas (email) ---"
  if "$PYTHON" -m main jobs alert --channel email; then
    echo "OK: alertas de vagas enviados"
  else
    echo "FALHA: alertas de vagas (codigo $?)"
  fi

  echo "--- [3/4] Coletando CFPs/eventos ---"
  if "$PYTHON" -m main academic collect; then
    echo "OK: coleta academica concluida"
  else
    echo "FALHA: coleta academica (codigo $?)"
  fi

  echo "--- [4/4] Alertas academicos (email) ---"
  if "$PYTHON" -m main academic alert --channel email; then
    echo "OK: alertas academicos enviados"
  else
    echo "FALHA: alertas academicos (codigo $?)"
  fi

  echo "=== Pipeline semanal concluido em $(date '+%Y-%m-%d %H:%M:%S') ==="
} >> "$LOG_FILE" 2>&1

# Rotacao: mantem os 12 logs semanais mais recentes
ls -t "$LOG_DIR"/weekly_*.log 2>/dev/null | tail -n +13 | xargs -r rm -f

exit 0

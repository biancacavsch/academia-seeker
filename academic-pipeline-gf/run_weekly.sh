#!/bin/bash
# run_weekly.sh — Pipeline semanal acadêmico: CFPs/eventos/bolsas + alertas
#
# Executado pelo anacron (1x por semana, com catch-up no boot).
# Entrada no /etc/anacrontab:
#   7  20  pipeline.academico-gf  runuser -u SEU_USUARIO -- <CAMINHO_DO_PROJETO>/run_weekly.sh
#
# Banco: academic.db (bolsas/eventos/chamadas — história, literatura, LatAm, gótico, terror)
# Credenciais (Telegram/SMTP) vêm do .env, carregado pelo config.py.
# Logs em logs/weekly_YYYYMMDD_HHMMSS.log (mantidos os 12 mais recentes).

PROJECT_DIR="<CAMINHO_DO_PROJETO>/academic-pipeline-gf"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/weekly_${STAMP}.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR" || exit 1

# Backup semanal do banco acadêmico (retém 60 dias)
BACKUP_DIR="$PROJECT_DIR/backups"
mkdir -p "$BACKUP_DIR"
for db in academic.db; do
  if [ -f "$db" ]; then
    cp "$db" "$BACKUP_DIR/${db%.db}_$(date +%Y%m%d).db" 2>/dev/null
  fi
done
find "$BACKUP_DIR" -name "*.db" -mtime +60 -delete 2>/dev/null

{
  echo "=== Pipeline acadêmico semanal iniciado em $(date '+%Y-%m-%d %H:%M:%S') ==="

  echo "--- [1/2] Coletando CFPs/eventos acadêmicos ---"
  if "$PYTHON" main.py academic collect; then
    echo "OK: coleta acadêmica concluída"
  else
    echo "FALHA: coleta acadêmica (código $?)"
  fi

  echo "--- [2/2] Alertas acadêmicos ---"
  if "$PYTHON" main.py academic alert --channel both; then
    echo "OK: alertas acadêmicos enviados"
  else
    echo "FALHA: alertas acadêmicos (código $?)"
  fi

  echo "=== Pipeline acadêmico semanal concluído em $(date '+%Y-%m-%d %H:%M:%S') ==="
} >> "$LOG_FILE" 2>&1

# Rotação: mantém os 12 logs semanais mais recentes
ls -t "$LOG_DIR"/weekly_*.log 2>/dev/null | tail -n +13 | xargs -r rm -f

exit 0

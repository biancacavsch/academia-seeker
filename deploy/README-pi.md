# academia-seeker no Raspberry Pi 3B (Debian headless + CasaOS + Pi-hole + Trilium)

Instalação **somente no Pi**. Sem Playwright/Chromium (poupa RAM e SD), sem Telegram.
Alertas apenas por e-mail (SMTP). Agendamento semanal com systemd + execução manual sob demanda.

## 0. Acesso SSH

Na máquina de trabalho (onde está a chave `~/.ssh/id_ed25519`):

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub bianca@192.168.11.127
ssh bianca@192.168.11.127
```

A chave pública é:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIO830+fcyt9Ri8cuhklhRznW0ZsOV4UzrBFW1YQ7iJQl academia-seeker-pi
```

## 1. Verificação rápida do Pi

```bash
uname -m
dpkg --print-architecture
free -h
swapon --show
df -h /
python3 --version
```

Se não houver swap, crie 1 GB (recomendado em Pi 3B com 1 GB de RAM):

```bash
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. Dependências de sistema

```bash
sudo apt update
sudo apt install -y python3-venv git sqlite3 curl
```

Se o pip reclamar de `lxml` (dependência do `trafilatura`) em `armhf`:

```bash
sudo apt install -y build-essential libxml2-dev libxslt1-dev
```

## 3. Clonar e instalar

```bash
sudo git clone https://github.com/biancacavsch/academia-seeker.git /opt/academia-seeker
sudo chown -R bianca:bianca /opt/academia-seeker
cd /opt/academia-seeker
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-pi.txt
```

> Repositório é público: **não** copiar o PAT do GitHub para o Pi.

## 4. Chaves de API (`.env`)

```bash
cd /opt/academia-seeker
cp .env.example .env
chmod 600 .env
nano .env
```

Preencher **apenas** estas (Telegram fica em branco/desativado):

```dotenv
# SMTP — único canal de alerta
SMTP_USER=seu_email@gmail.com
SMTP_PASS=senha_de_app_de_16_caracteres
FROM_EMAIL=seu_email@gmail.com
TO_EMAIL=destino@gmail.com

# Adzuna (250 chamadas/dia grátis)
ADZUNA_APP_ID=...
ADZUNA_APP_KEY=...

# Jooble (chave gratuita; coloque enabled: true no config.yaml para jooble)
JOOBLE_API_KEY=...
```

### 4.1 SMTP (Gmail — exemplo)

1. Acesse https://myaccount.google.com/security
2. Ative **Verificação em duas etapas** (obrigatório para App Password).
3. Em https://myaccount.google.com/apppasswords, clique em **Senhas de app**.
4. Escolha app = **Mail**, dispositivo = **Outro (nome personalizado)** → digite `academia-seeker` → **Gerar**.
5. Copie a senha de 16 caracteres (sem espaços) para `SMTP_PASS`.
6. `FROM_EMAIL` e `SMTP_USER` = seu Gmail; `TO_EMAIL` = onde receber (pode ser o mesmo).
   - Outros provedores: ajuste `alerts.email.smtp_host` e `smtp_port` no `config.yaml` (ex.: Outlook `smtp.office365.com:587`).

### 4.2 Adzuna

1. Crie conta em https://developer.adzuna.com/
2. Abra **My Apps** → **Add new App** (nome: `academia-seeker`, URL: `http://localhost`).
3. Copie **App ID** e **App Key** para `ADZUNA_APP_ID` e `ADZUNA_APP_KEY`.
4. Limite gratuito: 250 chamadas/dia. O projeto usa 4 países × 2 páginas × 2 coletores ≈ 16 chamadas/rodada — dentro do limite.

### 4.3 Jooble

1. Acesse https://jooble.org/api/about
2. Preencha o formulário (nome, e-mail, site/país) e envie.
3. A chave chega por e-mail (geralmente em poucos minutos).
4. Cole em `JOOBLE_API_KEY`.
5. Ative o coletor: em `config.yaml`, troque `jooble.enabled: false` por `true`.

### 4.4 Telegram (desativado)

`config.yaml` → `alerts.telegram.enabled: false`. Não preencher `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.
O `requirements-pi.txt` nem instala `python-telegram-bot`.

## 5. Validar antes de agendar

```bash
cd /opt/academia-seeker
.venv/bin/python -m main --help
.venv/bin/python -m main stats
.venv/bin/python -m main test-alerts
```

`test-alerts` envia um e-mail de teste — confirme que chegou (inclusive no spam).

## 6. systemd — semanal + manual

```bash
sudo cp /opt/academia-seeker/deploy/academia-seeker.service /etc/systemd/system/
sudo cp /opt/academia-seeker/deploy/academia-seeker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now academia-seeker.timer
systemctl list-timers academia-seeker.timer
```

**Executar manualmente a qualquer momento:**

```bash
sudo systemctl start academia-seeker.service
```

**Acompanhar:**

```bash
journalctl -u academia-seeker.service -f
tail -f /opt/academia-seeker/logs/weekly_*.log
```

**Resultados sem rodar coleta:**

```bash
cd /opt/academia-seeker
.venv/bin/python -m main jobs digest -d 7
.venv/bin/python -m main academic digest -d 7
.venv/bin/python -m main stats
```

## 7. Ajustes feitos para o Pi

| Ajuste | Motivo |
|---|---|
| `requirements-pi.txt` (sem Playwright/Telegram/APScheduler) | ~170 MB e RAM economizados |
| `upenn_cfp`, `dhsi_cfps`, `ach_announcements` desativados | URLs mortos (DNS `0.0.0.0` / HTTP 404) e exigiam Chromium |
| `dhsi_feed` + `ach_rss` adicionados (RSS) | Substituem 2 das 3 fontes sem navegador |
| `academic_search.page_budget: 40` | Reduz downloads por rodada |
| `Telegram: false`, e-mail como único canal | Pedido do usuário |
| `run_weekly.sh`: `PROJECT_DIR` automático, `-m main`, `--channel email`, `flock` | Funciona em qualquer caminho, sem sobreposição |
| `MemoryMax=700M`, `Nice=10`, `IOSchedulingClass=idle` | Não competir com Pi-hole/Trilium |

Os bancos `jobs.db`, `academic.db` e `items.db` são criados na primeira execução (não precisam vir do desktop).

## 8. Atualizações futuras

```bash
cd /opt/academia-seeker
git pull --ff-only
.venv/bin/pip install -r requirements-pi.txt
sudo systemctl restart academia-seeker.service
```

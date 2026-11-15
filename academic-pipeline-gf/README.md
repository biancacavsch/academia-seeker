# Academic Pipeline — História / Literatura / Gótico / Terror

Pipeline acadêmico separado (sem parte de vagas/estágios) para monitorar **CFPs, chamadas de artigos, eventos e bolsas** em:

- **História** / História da/na América Latina
- **História da Literatura** / Literatura Latino-Americana
- **Gótico / Terror / Horror**

Idiomas: **PT / EN / ES** · Thresholds: alerta ≥60 · digest ≥40

---

## 🚀 Quick Start

```bash
# 1. Entre no diretório
cd academic-pipeline-gf

# 2. Crie venv e instale dependências
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure alertas
cp .env.example .env
# edite .env com TO_EMAIL (e-mail de destino) e credenciais SMTP/Telegram

# 4. Execute primeira coleta
python -m main academic collect -v

# 5. Veja digest e prazos
python -m main academic digest -d 7
python -m main academic deadlines -d 30

# 6. Envie alertas (e-mail + Telegram)
python -m main academic alert --channel both

# 7. Agende no cron/anacron (exemplos em cron.example)
```

---

## 📦 Fontes Acadêmicas

| Fonte | Tipo | Categoria | Foco |
|-------|------|-----------|------|
| Busca web (ddgs + Marginalia) | search | bolsa/publicacao/evento | 61+ queries trilíngues: história, literatura, LatAm, gótico, terror |
| UPenn CFP | HTML | publicacao | Humanidades, literatura, comparative literature |
| WikiCFP | RSS | cfp | Philosophy, humanities, digital-humanities, technology |
| H-Net Announcements | RSS | event | História, literatura, LatAm, gótico, terror |
| EURAXESS | RSS | bolsa | Pesquisa na Europa |
| PhilPapers CFP | RSS | cfp | Filosofia / literatura |

### Queries por trilho (exemplos)

- **História:** `call for papers history`, `convocatoria artículos historia`, `CFP history conference 2027`
- **História da Literatura:** `chamada de artigos história da literatura`, `CFP literary history`, `convocatoria artículos historia de la literatura`
- **América Latina:** `call for papers Latin America history`, `chamada de artigos América Latina`, `convocatoria historia latinoamericana`
- **Literatura Latino-Americana:** `call for papers Latin American literature`, `chamada de artigos literatura latino-americana`, `convocatoria artículos literatura latinoamericana`
- **Gótico / Terror / Horror:** `call for papers gothic`, `CFP horror studies`, `chamada de artigos gótico terror`, `gothic literature conference 2027`

---

## ⚙️ Configuração

Edite `config.yaml`:

- **`academic_sources`**: fontes RSS/HTML com seletores CSS
- **`academic_search.queries`**: buscas web trilíngues por trilho
- **`keywords`**: termos de scoring (gothic_horror, literatura_latina, america_latina, etc.)
- **`filters.interests`**: allow-list de títulos para filtrar o escopo
- **`filters.exclude_areas`**: áreas rejeitadas (vaga, estágio, emprego, sales, etc.)
- **`alerts`**: Telegram e/ou e-mail

### Exemplo de nova fonte (apenas YAML)

```yaml
academic_sources:
  - name: minha_fonte
    enabled: true
    type: rss
    url: "https://exemplo.com/feed.rss"
    category: "cfp"
    rate_limit: 3.0
```

---

## 🎯 Scoring

| Subcategoria | Termos exemplo | Peso |
|--------------|----------------|------|
| `cfp_specific` | call for papers, chamada de artigos, submission deadline | 20 |
| `education_fit` | mestrado, doutorado, bolsa, fellowship, pesquisa | 15 |
| `broad` | history, história, literatura, literature, museum, archive | 15 (título) / 15 (desc) |
| `gothic_horror` | gothic, gótico, terror, horror, literatura gótica | 25 |
| `literatura_latina` | literatura latino-americana, history of literature | 25 |
| `america_latina` | américa latina, latin america, história da américa latina | 25 |
| `negatives` | vaga, estágio, emprego, sales, call center | -30 |

**Thresholds:**
- `min_score_alert`: 60 → dispara alerta
- `min_score_digest`: 40 → aparece no digest
- `max_job_age_days`: 30 (não elimina acadêmicos, só vagas)

---

## 🗄️ Banco de Dados

**Apenas um banco SQLite:** `academic.db`

- Tabela `items`: todos os itens acadêmicos (bolsa/publicacao/evento/cfp)
- Tabela `alerts_sent`: controle do que já foi alertado
- Nenhum item de `category = job` é armazenado aqui

---

## 📋 Comandos

```bash
python -m main academic collect -v     # Coleta CFPs/eventos/bolsas
python -m main academic alert          # Envia alertas (canal: both/email/telegram)
python -m main academic digest -d 7    # Digest últimos 7 dias
python -m main academic deadlines -d 30 # Prazos de submissão ≤30 dias
python -m main stats                   # Estatísticas do banco acadêmico
python -m main export -o cfps.csv -d 30 # Exporta para CSV
python -m main test-alerts             # Testa Telegram/email
```

O digest agrupa em: **① 🎓 Bolsas (PT) | ② 📄📅 Eventos e Publicações (PT) | ③ 🌍 Língua estrangeira (EN+ES) | ⚠️ Quarentena**.

---

## 📅 Agendamento

**Anacron** (recomendado para notebook):

```bash
# Adicione ao /etc/anacrontab:
7	20	pipeline.academico-gf	runuser -u bianca -- /home/bianca/job-pipeline/academic-pipeline-gf/run_weekly.sh
```

**run_weekly.sh** já existe no diretório — coleta + alertas + backup semanal do `academic.db` (60 dias de retenção).

---

## ⚠️ Notas Legais / ToS

- RSS público (DHNow, H-Net, PhilPapers, WikiCFP, EURAXESS): uso não-comercial
- Busca web (ddgs): respeite rate-limits; o pipeline usa delays conservadores (2s)
- **LinkedIn**: não incluído — ToS proíbe scraping
- Respeite `robots.txt`

---

## 📄 Licença

MIT — use, modifique, compartilhe.

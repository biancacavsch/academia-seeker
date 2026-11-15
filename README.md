# Job & Academic Pipeline — Humanidades Digitais / Divulgação Científica / Filosofia da Tecnologia

Pipeline automatizado para monitorar **vagas remotas globais** + **CFPs/eventos acadêmicos** (EN/PT/ES) com foco em:
- **Humanidades Digitais** / Digital Humanities / Humanidades Computacionais
- **Divulgação Científica** / Science Communication / Comunicação Científica
- **Divulgação Cultural** / Cultural Dissemination
- **GLAM** (Galleries, Libraries, Archives, Museums)
- **Filosofia da Tecnologia** / Philosophy of Technology / STS
- Perfil: **Ciências Sociais + Mestrado em Divulgação Científica/Cultural em andamento**

---

## 🚀 Quick Start

```bash
# 1. Clone e entre no diretório
cd job-pipeline

# 2. Crie venv e instale dependências
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Instale Playwright (para fontes HTML)
playwright install chromium

# 4. Configure alertas e chaves de API (opcional)
cp .env.example .env
# edite .env com suas credenciais

# 5. Execute primeiras coletas (comandos SEPARADOS)
python -m main jobs collect -v      # Apenas vagas
python -m main academic collect -v  # Apenas CFPs/eventos

# 6. Veja digests
python -m main jobs digest -d 7
python -m main academic digest -d 7
python -m main academic deadlines -d 30  # CFPs com deadline próximas

# 7. Agende no cron (exemplos em cron.example)
```

---

## 📦 Fontes de Dados

### Vagas de Emprego (`jobs`)
| Fonte | Tipo | Auth | Foco |
|-------|------|------|------|
| **Arbeitnow** | API | Não | Europa + remote, ATS direto |
| **Remotive** | API | Não | Remote global, sem filtro de categoria (scoring decide) |
| **RemoteJobs.org** | API | Não | Remote global, multi-idioma |
| **Adzuna** | API | Chave free no `.env` | BR + US + GB + ES, busca `what_or`, 2 págs/país |
| **Jooble** | API | Não | Vagas multi-país |
| **EURAXESS** | RSS oficial | Não | Pesquisa na Europa (maioria presencial — `remote_only` filtra) |
| **Digital Humanities Now** | RSS | Não | Vagas DH curadas |
| **Archives Gig** | RSS | Não | Arquivos/museus + DH |
| **Code4Lib Jobs** | RSS | Não | Vagas de bibliotecas digitais (migrou de `academic_sources` p/ `sources`: category=job precisa ir a jobs.db) |

### Estágios / Home Office (`jobs`, tag `estagio`)
| Fonte | Tipo | Foco |
|-------|------|------|
| **estagio_search** | busca web `ddgs` | Queries trilíngues (pt/en/es — LatAm); mira home office/remoto + portais `site:` (vagas.com.br, catho, 99jobs, indeed) |
| **empresas_alvo** | busca web `ddgs` | 13 empresas-alvo × templates `site:` (Gupy/LinkedIn/Indeed) → links diretos de vaga |
| **adzuna_estagio** | API | Estágios por país (códigos ISO: br, us, gb, es) |
| **vagas_estagio** | HTML (`html_job`) | vagas.com.br — filtro home office |
| **catho_estagio** | HTML (`html_job`) | catho.com.br/vagas/estagio-home-office (20 ofertas/pág) |
| **jobs99_estagio** | HTML (`html_job`) | 99jobs.com busca "estágio" (1 página — page=2 redireciona p/ home) |
| **url_utils.resolve_direct_url** | extração | Baixa a página interna da vaga e extrai link direto (Gupy/empresa); só aceita páginas de vaga (`is_job_page`) |

### CFPs / Eventos Acadêmicos (`academic`)
| Fonte | Tipo | Auth | Categoria | Foco |
|-------|------|------|-----------|------|
| **Busca web** (`ddgs` + Marginalia) | search | Não | bolsa/publicacao/evento | 61 queries trilíngues por trilho (ver `academic_search` no config): inclui eventos/chamadas BR (Intercom, SBPC, ANPOCS), editais CAPES/CNPq/FAPESP e LatAm em espanhol |
| **UPenn CFP** | HTML | Não | publicacao | Categorias humanities-computing, science-and-culture (deadlines estruturados) |
| **WikiCFP** | RSS | Não | cfp | Philosophy, humanities, digital-humanities, technology |
| **H-Net** | RSS | Não | event | Anúncios filtrados por keywords |
| **DHNow CFPs** | RSS | Não | cfp | CFPs curados DH |
| **DHNow Conferences** | RSS | Não | event | Conferências DH |
| **PhilPapers** | RSS | Não | cfp | Filosofia |
| **ALA TechSource** | RSS | Não | event | Biblioteconomia/tech |
| **DHSI** | HTML | Não | cfp | dhsi.org (seletores configuráveis) |
| **ACH** | HTML | Não | event | ach.org (seletores configuráveis) |

### Pré-requisito de edital aberto (garantia)
Toda oportunidade acadêmica tem `deadline_status`: `open` | `closing_soon` (≤15d) | `closed` | `unknown`.
- **Alertam e aparecem nas seções ①②③ apenas itens `open`** (fechamento ≥ hoje; dia do vencimento conta).
- `closed` (data passada ou `ENCERRADO`/`closed` no texto) nunca alerta nem aparece.
- `unknown` (sem data extraível) vai para a **quarentena rotulada** (digest), nunca alerta.
- Data de referência: momento do scraping (`first_seen_at`), reavaliada contra "agora" no alerta.
- Vale como fechamento: fim de intervalo explícito ("inscrições A **a B**") > data com marcador (`deadline/prazo/inscrições até/até DD de mês/applications close`) > data avulsa **não vale**.
- Idade do post **não** elimina acadêmicos (só vagas); presenciais passam sem filtro geográfico, com local destacado.
- Trilho `bolsa` é estrito: só mestrado/intercâmbio (doutorado, pós-doc, IC e graduação são descartados, salvo edital misto com mestrado elegível).

### Saída acadêmica em seções
`academic digest` e alertas agrupam em: **① 🎓 Bolsas (PT) | ② 📄📅 Eventos e Publicações (PT) | ③ 🌍 Língua estrangeira (EN+ES) | ⚠️ Quarentena**.

---

## ⚙️ Configuração

Edite `config.yaml`:

- **sources** (vagas): habilite/desabilite, configure parâmetros
- **academic_sources** (CFPs/eventos): adicione/remova fontes RSS/HTML com seletores CSS
- **keywords**: adicione/remova termos do seu perfil
  - Pesos: `core`=40, `scicomm`=25, `glam`=15, `philosophy_tech`=40, `digital_humanities`=25, `cfp_specific`=20, `education_fit`=15, `negatives`=-30
- **filters**: `remote_only`, `languages`, `min_score_alert` (default 60), `min_score_digest` (default 40)
- **alerts**: habilite `telegram` ou `email` e configure no `.env`

### Adicionar nova fonte RSS (sem código)
```yaml
academic_sources:
  - name: minha_fonte
    enabled: true
    type: rss
    url: "https://exemplo.com/feed.rss"
    category: "cfp"
    rate_limit: 3.0
    params:
      keywords: ["termo1", "termo2"]
```

### Adicionar fonte HTML/scraping (sem código)
```yaml
academic_sources:
  - name: minha_fonte_html
    enabled: true
    type: html
    url: "https://exemplo.com/cfps"
    category: "cfp"
    rate_limit: 5.0
    params:
      selector: "article, .post, .item"
      title_selector: "h2 a, h3 a, .title a"
      link_selector: "a"
      date_selector: "time, .date"
      description_selector: ".content, .excerpt, p"
```

---

## 🎯 Scoring

| Categoria | Peso | Onde busca |
|-----------|------|------------|
| Core DH | 40 (título) / 25 (desc) | título, descrição, tags |
| Science Comm | 40 / 25 | título, descrição, tags |
| GLAM | 25 | descrição, tags |
| Philosophy of Tech | 40 / 25 | título, descrição, tags |
| Digital Humanities | 25 | descrição, tags |
| CFP Specific | 20 | descrição, tags |
| Fit formação | 15 | descrição |
| Termos nucleares (broad) | 25 (título) / 15 (desc) | título, descrição — recall p/ history, museum, archive, phd etc. |
| **Negativos** | **-30** | título, descrição — inclui boilerplates: employment/work history, our/company philosophy, sales |
| **Bônus deadline ≤30d** | **+15** | academic items |
| **Bônus virtual** | **+10** | academic items |

**Thresholds:**
- `min_score_alert`: 60 → dispara alerta Telegram/email
- `min_score_digest`: 40 → aparece no digest
- armazenamento: score ≥ 30 (`min_score_digest - 10`)
- `max_job_age_days`: 30 → itens mais velhos são descartados no scoring e nos alertas (nunca alertam)

---

## 📋 Comandos

### Vagas de Emprego (`jobs`)
```bash
python -m main jobs collect -v     # Coleta vagas
python -m main jobs alert          # Envia alertas de vagas
python -m main jobs digest -d 7    # Digest últimas vagas
```

### CFPs/Eventos Acadêmicos (`academic`)
```bash
python -m main academic collect -v     # Coleta CFPs/eventos
python -m main academic alert          # Envia alertas acadêmicos
python -m main academic digest -d 7    # Digest CFPs/eventos
python -m main academic deadlines -d 30 # CFPs com deadline ≤30 dias
```

### Gerais
```bash
python -m main stats                 # Estatísticas do banco
python -m main export -o itens.csv -d 30 --category job
python -m main export -o cfps.csv -d 30 --category cfp
python -m main test-alerts           # Testa Telegram/email
```

---

## 🗄️ Banco de Dados

**Dois bancos SQLite separados por domínio** (config → `storage`):

| Banco | Grupo de coletores | Conteúdo |
|---|---|---|
| `jobs.db` | `sources` | Vagas/estágios (`category = job`) + `alerts_sent` |
| `academic.db` | `academic_sources` + `academic_search` | Bolsas/eventos/chamadas (`category != job`) + `alerts_sent` |

- Cada comando usa o banco do seu grupo: `jobs *` → `jobs.db`, `academic *` → `academic.db`
- `stats` mostra os dois; `export --db jobs|academic|all` escolhe a origem
- `items.db` fica como **legado** (backup pré-separação em `items.db.pre-separacao`)
- Migração idempotente: `migrate_split_db.py` (roda uma vez; cópia itens + alertas)
- Backup semanal automático em `backups/` (roda no `run_weekly.sh`, retém 60 dias)
- Campos por tipo (company/remote/salary para jobs; venue/event_type/deadline para academic)
- `alerts_sent`: controle do que já foi alertado, por banco

---

## 🔧 Extendendo

### Adicionar nova fonte API (jobs)
1. Crie `collectors/minha_fonte.py` herdando `APICollector`
2. Implemente `fetch()` yieldando `Job`
3. Registre em `collectors/registry.py` (dicionário `JOB_COLLECTORS`)
4. Adicione em `config.yaml` → `sources`

### Adicionar fonte RSS/HTML (academic)
1. **Apenas YAML**: adicione em `config.yaml` → `academic_sources` (veja exemplos acima)
2. **Custom Python**: herde `AcademicRSSCollector` ou `AcademicHTMLCollector`, registre em `ACADEMIC_COLLECTORS`

### Ajustar scoring
Edite `config.yaml` → `keywords` ou modifique `score.py` para lógica customizada.

---

## 📅 Agendamento

### Anacron — semanal, roda no primeiro boot da semana (recomendado p/ notebook)

O cron puro perde a execução se o notebook estiver desligado. O anacron faz *catch-up*: se passou da data, roda automaticamente no próximo boot (com atraso p/ a rede subir).

**1. O script semanal já existe:** `run_weekly.sh` — coleta vagas + alertas, coleta acadêmico + alertas, loga em `logs/weekly_*.log` (mantém os 12 mais recentes).

**2. Adicione ao `/etc/anacrontab` (uma vez, exige sudo):**
```bash
sudo nano /etc/anacrontab
# adicione esta linha:
7	20	pipeline.semanal	runuser -u bianca -- /home/bianca/job-pipeline/run_weekly.sh
```
- `7` = período em dias (semanal); `20` = atraso em minutos após o boot (tempo do Wi-Fi conectar).

**3. Valide e teste:**
```bash
sudo anacron -T                          # testa sintaxe (sem executar nada)
/home/bianca/job-pipeline/run_weekly.sh  # teste manual completo
tail -f logs/weekly_*.log                # acompanha o log
ls /var/spool/anacron/                   # carimbo pipeline.semanal aparece após a 1ª execução
```

### Cron (Linux/macOS) — horário fixo, só roda se ligado

Exemplos completos em `cron.example`. Resumo:

### GitHub Actions (gratuito, roda na nuvem)
Workflow pronto em `.github/workflows/daily.yml`:
- Jobs diários (coleta + alertas)
- Academic diários (coleta + alertas + deadlines)
- Digest semanal às segundas
- Artefatos com banco SQLite

Configure secrets no repositório:
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `SMTP_USER`, `SMTP_PASS`, `FROM_EMAIL`, `TO_EMAIL`
- `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`
- `JOOBLE_API_KEY`

---

## ⚠️ Notas Legais / ToS

- **Arbeitnow**: uso livre, sem auth, rate-limit via Cloudflare (~8 reqs burst)
- **Remotive**: exige link de volta + menção "via Remotive" (já no footer do alerta)
- **RemoteJobs.org**: atribuição "Powered by RemoteJobs.org" solicitada
- **Adzuna/Jooble**: free tier com limites (250/dia, 60 países)
- **DHNow / Archives Gig / H-Net / PhilPapers**: RSS público, uso não-comercial
- **WikiCFP**: uso educacional/pessoal
- **LinkedIn**: **não incluído** — ToS proíbe scraping, sem API pública de vagas
- Respeite `robots.txt` e rate-limits; o pipeline usa delays conservadores (1–2s)
- Playwright (HTML collectors) pode exigir ajustes em ambientes headless/CI

---

## 📄 Licença

MIT — use, modifique, compartilhe.

---

## 👩‍🎓 Pipeline Acadêmico Separado — História / Literatura / Gótico / Terror

Este repositório inclui, no diretório `academic-pipeline-gf/`, um **pipeline acadêmico separado** dedicado exclusivamente à namorada, focado em:

- **História** / História da/na América Latina
- **História da Literatura** / Literatura Latino-Americana
- **Gótico / Terror / Horror**

### Estrutura

```
job-pipeline/                 # Seu pipeline (vagas + acadêmico seu)
├── academic-pipeline-gf/     # Pipeline dela (apenas acadêmico)
│   ├── config.yaml           # Fontes e keywords específicas dela
│   ├── main.py               # CLI acadêmico-only (sem comandos jobs)
│   ├── academic.db           # Banco SQLite só dela
│   ├── run_weekly.sh         # Execução semanal
│   ├── .env                  # Credenciais dela (e-mail: SEU_EMAIL@gmail.com)
│   └── tests/                # 41 testes passando
└── ...                       # Seu pipeline original inalterado
```

### Comandos (dentro de `academic-pipeline-gf/`)

```bash
python -m main academic collect -v   # Coleta CFPs/eventos/bolsas
python -m main academic alert        # Envia alertas por e-mail/Telegram
python -m main academic digest -d 7  # Digest semanal
python -m main academic deadlines -d 30  # Prazos próximos
python -m main stats                 # Estatísticas do banco acadêmico
```

### Filtros aplicados

- ✅ Programas de **mestrado puro são rejeitados** (já está no mestrado)
- ✅ Doutorado, pós-doc, bolsas de pesquisa e intercâmbio seguem elegíveis
- ✅ Páginas de notícia (ex: g1) são bloqueadas, exceto quando o título é uma chamada explícita
- ✅ Vagas/estágios são filtrados (áreas excluídas: direito, enfermagem, vendas, etc.)
- ✅ Score mínimo para alerta: 60 | Digest: 40
- Idiomas: PT / EN / ES

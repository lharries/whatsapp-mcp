"""
github_bugs_sync.py — Sincroniza bugs do WhatsApp Cismetro com GitHub Issues
=============================================================================
- Le mensagens de bug do SQLite
- Cria Issues no GitHub para novos bugs (deduplicado por ID de mensagem)
- Fecha Issues automaticamente quando detecta "resolvido" no suporte
- Aplica labels: severidade, modulo, status
- Token lido via env var GITHUB_TOKEN (definido pelo .bat)
"""

import os
import sys
import re
import sqlite3
import requests
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuracoes ──────────────────────────────────────────────────────────────
DB_PATH    = os.path.join(os.path.expanduser("~"), "store", "messages.db")
CHAT_JID   = "120363418632425656@g.us"
CHAT_NAME  = "Suporte Cismetro"
TOKEN_FILE = Path(__file__).parent / ".github_token"

DIAS_PADRAO = 30

# GitHub — preencha com seu usuario e nome do repositorio
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "")  # ex: "seunome"
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")   # ex: "cismetro-bugs"
GITHUB_API   = "https://api.github.com"

# ── Palavras-chave (mesma logica do relatorio_agente.py) ─────────────────────
KW_BUG = [
    "nao encontra", "nao aparece", "nao funciona", "nao esta", "erro",
    "bug", "falha", "problema", "parou", "caiu", "offline", "inoperante",
    "duplicado", "duplicata", "fantasma", "divergencia", "divergente",
    "nao consegue", "travando", "trava", "lento",
    "nao carrega", "nao abre", "nao gera", "sem acesso", "fora do ar",
    "zerado", "bloqueado", "nao mostra", "sumiu", "desapareceu",
    "inconsistencia", "valor errado", "nao localiza"
]
KW_CRITICO = [
    "sem sistema", "sistema parado", "sistema offline", "sistema fora",
    "inoperante", "caiu o sistema", "sistema caiu", "sem acesso ao sistema",
    "fora do ar", "sistema muito lento", "sistema oscilando"
]
KW_RESOLVIDO = [
    "vamos analisar", "iremos analisar", "estamos verificando",
    "ja liberamos", "pronto", "deu certo", "resolvido", "foi corrigido",
    "liberado", "liberamos", "pode testar", "testado", "normalizado"
]

# Modulos para detectar automaticamente
MODULOS = {
    "Exames":        ["exame", "resultado", "laudo", "laboratorio", "pcr", "vdrl", "urocultura"],
    "Agendamento":   ["agendamento", "agenda", "consulta", "marcar", "desmarcar", "cancelar"],
    "Prontuario":    ["prontuario", "paciente", "cadastro", "ficha"],
    "Relatorios":    ["relatorio", "exportar", "planilha", "impressao", "imprimir"],
    "Acesso":        ["senha", "login", "acesso", "usuario", "bloqueado", "perfil"],
    "Financeiro":    ["fatura", "cobranca", "pagamento", "financeiro", "valor"],
    "Sistema Geral": [],
}

def normalize(text: str) -> str:
    """Remove acentos e converte para minusculas."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def detectar_modulo(text: str) -> str:
    t = normalize(text)
    for modulo, kws in MODULOS.items():
        if modulo == "Sistema Geral":
            continue
        if any(k in t for k in kws):
            return modulo
    return "Sistema Geral"


def detectar_severidade(text: str) -> str:
    t = normalize(text)
    if any(k in t for k in KW_CRITICO):
        return "critical"
    palavras_altas = ["nao funciona", "parou", "inoperante", "sem acesso", "erro critico"]
    if any(k in t for k in palavras_altas):
        return "high"
    return "medium"


def eh_bug(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in KW_BUG)


def eh_resolvido(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in KW_RESOLVIDO)


# ── Token GitHub ───────────────────────────────────────────────────────────────
def get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    print("\n[ERRO] Token GitHub nao encontrado.")
    print("  Execute pelo arquivo 'Gerar Relatorio Cismetro.bat'")
    sys.exit(1)


def get_config() -> tuple[str, str]:
    owner = GITHUB_OWNER or os.environ.get("GITHUB_OWNER", "").strip()
    repo  = GITHUB_REPO  or os.environ.get("GITHUB_REPO",  "").strip()
    if not owner or not repo:
        print("\n[ERRO] GITHUB_OWNER e GITHUB_REPO nao configurados.")
        print("  Edite o arquivo github_bugs_sync.py e preencha GITHUB_OWNER e GITHUB_REPO.")
        sys.exit(1)
    return owner, repo


# ── GitHub API helpers ─────────────────────────────────────────────────────────
class GitHubClient:
    def __init__(self, token: str, owner: str, repo: str):
        self.base    = f"{GITHUB_API}/repos/{owner}/{repo}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept":        "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        self.owner = owner
        self.repo  = repo

    def _get(self, url, **kwargs):
        r = requests.get(url, headers=self.headers, **kwargs)
        r.raise_for_status()
        return r.json()

    def _post(self, url, **kwargs):
        r = requests.post(url, headers=self.headers, **kwargs)
        r.raise_for_status()
        return r.json()

    def _patch(self, url, **kwargs):
        r = requests.patch(url, headers=self.headers, **kwargs)
        r.raise_for_status()
        return r.json()

    def test_connection(self):
        try:
            r = requests.get(f"{GITHUB_API}/repos/{self.owner}/{self.repo}",
                             headers=self.headers, timeout=10)
            if r.status_code == 401:
                print("[ERRO] Token GitHub invalido (401). Verifique o token.")
                TOKEN_FILE.unlink(missing_ok=True)
                sys.exit(1)
            if r.status_code == 404:
                print(f"[ERRO] Repositorio '{self.owner}/{self.repo}' nao encontrado.")
                print("  Crie o repositorio em https://github.com/new")
                sys.exit(1)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError:
            print("[ERRO] Sem conexao com GitHub. Verifique sua internet.")
            sys.exit(1)

    def ensure_labels(self):
        """Cria os labels necessarios se nao existirem."""
        labels_desejados = [
            {"name": "severity: critical",    "color": "B60205", "description": "Impacto critico / sistema fora"},
            {"name": "severity: high",        "color": "E4580A", "description": "Impacto alto"},
            {"name": "severity: medium",      "color": "FBCA04", "description": "Impacto medio"},
            {"name": "severity: low",         "color": "0E8A16", "description": "Impacto baixo"},
            {"name": "bug",                   "color": "D73A4A", "description": "Bug confirmado"},
            {"name": "auto-detectado",        "color": "0075CA", "description": "Detectado automaticamente pelo agente"},
            {"name": "resolvido",             "color": "28A745", "description": "Bug resolvido pelo suporte"},
            {"name": "modulo: Exames",        "color": "BFD4F2", "description": ""},
            {"name": "modulo: Agendamento",   "color": "BFD4F2", "description": ""},
            {"name": "modulo: Prontuario",    "color": "BFD4F2", "description": ""},
            {"name": "modulo: Relatorios",    "color": "BFD4F2", "description": ""},
            {"name": "modulo: Acesso",        "color": "BFD4F2", "description": ""},
            {"name": "modulo: Financeiro",    "color": "BFD4F2", "description": ""},
            {"name": "modulo: Sistema Geral", "color": "BFD4F2", "description": ""},
        ]
        try:
            existing = {l["name"] for l in self._get(f"{self.base}/labels", params={"per_page": 100})}
        except Exception:
            existing = set()

        criados = 0
        for lb in labels_desejados:
            if lb["name"] not in existing:
                try:
                    self._post(f"{self.base}/labels", json=lb)
                    criados += 1
                except Exception:
                    pass
        if criados:
            print(f"[OK] {criados} label(s) criado(s) no repositorio.")

    def buscar_issue_por_msg_id(self, msg_id: str):
        """Procura issue que contenha o msg_id no corpo (para deduplicar)."""
        try:
            results = self._get(f"{GITHUB_API}/search/issues",
                                params={"q": f"repo:{self.owner}/{self.repo} {msg_id} in:body",
                                        "per_page": 5})
            items = results.get("items", [])
            return items[0] if items else None
        except Exception:
            return None

    def criar_issue(self, titulo: str, corpo: str, labels: list) -> dict:
        return self._post(f"{self.base}/issues", json={
            "title":  titulo,
            "body":   corpo,
            "labels": labels
        })

    def fechar_issue(self, numero: int, comentario: str):
        """Adiciona comentario e fecha a issue."""
        try:
            self._post(f"{self.base}/issues/{numero}/comments",
                       json={"body": comentario})
            self._patch(f"{self.base}/issues/{numero}",
                        json={"state": "closed"})
        except Exception as e:
            print(f"  [!] Nao foi possivel fechar issue #{numero}: {e}")

    def adicionar_label(self, numero: int, label: str):
        try:
            self._post(f"{self.base}/issues/{numero}/labels",
                       json={"labels": [label]})
        except Exception:
            pass


# ── Banco de dados ─────────────────────────────────────────────────────────────
def buscar_mensagens(dias: int) -> list:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Banco nao encontrado: {DB_PATH}")

    after = datetime.now() - timedelta(days=dias)
    conn  = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur   = conn.cursor()
    cur.execute("""
        SELECT
            m.id,
            m.timestamp,
            m.sender,
            m.content,
            m.is_from_me,
            COALESCE(c.name, m.sender) AS sender_name
        FROM messages m
        LEFT JOIN chats c ON c.jid = m.sender
        WHERE m.chat_jid = ?
          AND m.timestamp >= ?
          AND m.content IS NOT NULL
          AND m.content != ''
          AND (m.media_type IS NULL OR m.media_type = '')
        ORDER BY m.timestamp ASC
    """, (CHAT_JID, after.isoformat()))
    rows = cur.fetchall()
    conn.close()
    return rows


# ── Logica principal ──────────────────────────────────────────────────────────
def montar_corpo_issue(msg_id: str, dt: datetime, sender: str,
                       content: str, modulo: str, severidade: str) -> str:
    """Formata o corpo da Issue no padrao Markdown."""
    return f"""## Descricao do Bug

**Reportado por:** {sender}
**Data:** {dt.strftime('%d/%m/%Y %H:%M')}
**Modulo:** {modulo}
**Severidade:** {severidade}

### Mensagem Original (WhatsApp)

> {content}

---
*Criado automaticamente pelo Agente Cismetro*
<!-- msg_id:{msg_id} -->
"""


def processar_bugs(gh: GitHubClient, rows: list) -> dict:
    stats = {"novos": 0, "duplicados": 0, "fechados": 0, "erros": 0}

    bugs     = [(r, r["id"]) for r in rows if not r["is_from_me"] and eh_bug(r["content"] or "")]
    respostas = [r for r in rows if r["is_from_me"] and eh_resolvido(r["content"] or "")]

    print(f"[MSG] {len(rows)} mensagens | {len(bugs)} bugs detectados | {len(respostas)} respostas de resolucao")

    # -- Cria issues para bugs novos
    for row, msg_id in bugs:
        content = row["content"] or ""
        try:
            ts_val = row["timestamp"]
            dt = datetime.fromisoformat(ts_val) if isinstance(ts_val, str) else datetime.fromtimestamp(ts_val)
        except Exception:
            dt = datetime.now()

        sender     = row["sender_name"] or row["sender"] or "?"
        modulo     = detectar_modulo(content)
        severidade = detectar_severidade(content)

        # Deduplicar: busca por msg_id no corpo das issues
        existente = gh.buscar_issue_por_msg_id(msg_id)
        if existente:
            stats["duplicados"] += 1
            print(f"  [=] Ja existe: #{existente['number']} — {existente['title'][:60]}")
            continue

        # Titulo: primeiros 80 chars da mensagem
        titulo_raw = re.sub(r"\s+", " ", content).strip()
        titulo = f"[{modulo}] {titulo_raw[:75]}{'...' if len(titulo_raw) > 75 else ''}"

        corpo  = montar_corpo_issue(msg_id, dt, sender, content, modulo, severidade)
        labels = ["bug", "auto-detectado", f"severity: {severidade}", f"modulo: {modulo}"]

        try:
            issue = gh.criar_issue(titulo, corpo, labels)
            stats["novos"] += 1
            print(f"  [+] Issue #{issue['number']} criada: {titulo[:60]}")
        except Exception as e:
            stats["erros"] += 1
            print(f"  [!] Erro ao criar issue: {e}")

    # -- Fecha issues quando suporte confirmou resolucao
    # Estrategia: para cada resposta de resolucao, procura issues abertas
    # do mesmo dia e tenta fechar as mais recentes
    if respostas:
        print(f"\n[>>] Verificando {len(respostas)} resposta(s) de resolucao...")
        for resp in respostas:
            resp_content = resp["content"] or ""
            try:
                ts_val = resp["timestamp"]
                dt_resp = datetime.fromisoformat(ts_val) if isinstance(ts_val, str) else datetime.fromtimestamp(ts_val)
            except Exception:
                dt_resp = datetime.now()

            # Busca issues abertas com bug no mesmo periodo
            try:
                abertas = gh.buscar_issues_abertas_no_periodo(dt_resp)
                for issue in abertas[:3]:  # fecha as 3 mais proximas
                    comentario = (
                        f"**Resolvido pelo Suporte**\n\n"
                        f"> {resp_content}\n\n"
                        f"*Resolucao detectada automaticamente em {dt_resp.strftime('%d/%m/%Y %H:%M')}*"
                    )
                    gh.fechar_issue(issue["number"], comentario)
                    gh.adicionar_label(issue["number"], "resolvido")
                    stats["fechados"] += 1
                    print(f"  [V] Issue #{issue['number']} fechada como resolvida.")
            except Exception:
                pass

    return stats


# Adiciona metodo que estava faltando
def _buscar_issues_abertas_no_periodo(self, dt_ref: datetime) -> list:
    """Busca issues abertas criadas no mesmo dia ou dia anterior."""
    dia_inicio = (dt_ref - timedelta(days=1)).strftime("%Y-%m-%d")
    dia_fim    = dt_ref.strftime("%Y-%m-%d")
    try:
        results = self._get(f"{GITHUB_API}/search/issues",
                            params={"q": f"repo:{self.owner}/{self.repo} is:open label:bug "
                                         f"created:{dia_inicio}..{dia_fim}",
                                    "sort": "created", "order": "desc",
                                    "per_page": 10})
        return results.get("items", [])
    except Exception:
        return []

GitHubClient.buscar_issues_abertas_no_periodo = _buscar_issues_abertas_no_periodo


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    dias = DIAS_PADRAO
    if len(sys.argv) > 1:
        try:
            dias = int(sys.argv[1])
        except ValueError:
            pass

    print("=" * 55)
    print("  GITHUB BUGS SYNC — Suporte Cismetro")
    print(f"  Periodo: ultimos {dias} dias")
    print("=" * 55)

    token        = get_token()
    owner, repo  = get_config()

    print(f"[>>] Repositorio: https://github.com/{owner}/{repo}")

    gh = GitHubClient(token, owner, repo)

    print("[>>] Verificando conexao com GitHub...")
    info = gh.test_connection()
    print(f"[OK] Conectado: {info.get('full_name')} ({info.get('open_issues_count', 0)} issues abertas)")

    print("[>>] Verificando labels...")
    gh.ensure_labels()

    print("[>>] Buscando mensagens do banco...")
    try:
        rows = buscar_mensagens(dias)
    except FileNotFoundError as e:
        print(f"[ERRO] {e}")
        sys.exit(1)

    if not rows:
        print("[!] Nenhuma mensagem encontrada no periodo.")
        sys.exit(0)

    print("[>>] Processando bugs e sincronizando com GitHub Issues...")
    stats = processar_bugs(gh, rows)

    print()
    print("=" * 55)
    print(f"  RESULTADO:")
    print(f"  [+] Issues criadas:    {stats['novos']}")
    print(f"  [=] Ja existiam:       {stats['duplicados']}")
    print(f"  [V] Fechadas/resolvid: {stats['fechados']}")
    if stats["erros"]:
        print(f"  [!] Erros:             {stats['erros']}")
    print(f"  Ver: https://github.com/{owner}/{repo}/issues")
    print("=" * 55)


if __name__ == "__main__":
    main()

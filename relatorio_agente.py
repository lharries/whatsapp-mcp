"""
Agente Automático — Suporte Cismetro
=====================================
1. Garante que o whatsapp-bridge.exe está rodando
2. Busca mensagens do grupo Suporte Cismetro (período configurável)
3. Gera relatório Excel com mensagens + análise de bugs/incidentes
4. Salva na pasta Relatorios_Cismetro dentro do perfil do usuario
"""

import os
import sys
import time
import subprocess
import sqlite3
import requests
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

try:
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    print("Instalando openpyxl...")
    subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

# ── Configurações ─────────────────────────────────────────────────────────────
_BASE        = Path(__file__).parent
BRIDGE_EXE   = str(_BASE / "whatsapp-bridge" / "whatsapp-bridge.exe")
BRIDGE_DIR   = str(_BASE / "whatsapp-bridge")
BRIDGE_URL   = "http://localhost:8080/api"
DB_PATH      = os.path.join(os.path.expanduser("~"), "store", "messages.db")
OUTPUT_DIR   = os.path.join(os.path.expanduser("~"), "Relatorios_Cismetro")
CHAT_JID     = "120363418632425656@g.us"
CHAT_NAME    = "Suporte Cismetro"

# Período padrão: últimos 30 dias (pode passar --dias N na linha de comando)
DIAS_PADRAO  = 30

# ── Helpers de estilo ─────────────────────────────────────────────────────────
def make_fill(hex_color): return PatternFill("solid", fgColor=hex_color)
def make_font(bold=False, color="000000", size=9):
    return Font(bold=bold, color=color, size=size, name="Calibri")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT   = Alignment(horizontal="left",   vertical="top",    wrap_text=True)

# ── 1. Bridge ─────────────────────────────────────────────────────────────────
def bridge_alive():
    try:
        r = requests.get(f"{BRIDGE_URL}/chats", timeout=3)
        return r.status_code < 500
    except Exception:
        return False

def start_bridge():
    if bridge_alive():
        print("[OK] Bridge já está rodando.")
        return None

    print("[>>] Iniciando whatsapp-bridge.exe ...")
    proc = subprocess.Popen(
        [BRIDGE_EXE],
        cwd=BRIDGE_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )

    for i in range(30):           # aguarda até 30s
        time.sleep(1)
        if bridge_alive():
            print(f"[OK] Bridge pronto ({i+1}s).")
            return proc
        print(f"  aguardando... {i+1}s", end="\r")

    print("\n[!]  Bridge não respondeu em 30s. Verifique se o WhatsApp está conectado.")
    return proc

# ── 2. Busca mensagens via SQLite ─────────────────────────────────────────────
def buscar_mensagens(dias: int):
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Banco não encontrado: {DB_PATH}")

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
        ORDER BY m.timestamp ASC
    """, (CHAT_JID, after.isoformat()))

    rows = cur.fetchall()
    conn.close()
    print(f"[MSG] {len(rows)} mensagens encontradas (últimos {dias} dias).")
    return rows

# ── 3. Classificação automática ───────────────────────────────────────────────
KEYWORDS_BUG = [
    "não encontra", "não aparece", "não funciona", "não está", "erro",
    "bug", "falha", "problema", "parou", "caiu", "offline", "inoperante",
    "duplicado", "duplicata", "fantasma", "divergência", "divergente",
    "não consegue", "nao consegue", "travando", "trava", "lento",
    "não carrega", "não abre", "não gera", "sem acesso", "fora do ar",
    "zerado", "bloqueado", "não mostra", "sumiu", "desapareceu",
    "inconsistência", "valor errado", "vdrl", "nao localiza"
]
KEYWORDS_SUPORTE = [
    "vamos analisar", "iremos analisar", "so um minuto", "só um minuto",
    "estamos verificando", "pode testar", "ja liberamos", "pronto",
    "deu certo", "resolvido", "foi corrigido", "liberado", "liberamos"
]
KEYWORDS_INDISPONIBILIDADE = [
    "sem sistema", "sistema parado", "sistema offline", "sistema fora",
    "inoperante", "caiu o sistema", "sistema caiu", "sem acesso",
    "fora do ar", "sistema muito lento", "sistema oscilando", "não carrega"
]

def classify(text: str):
    t = text.lower()
    if any(k in t for k in KEYWORDS_INDISPONIBILIDADE):
        return "[CRIT] Indisponibilidade"
    if any(k in t for k in KEYWORDS_BUG):
        return "[WARN] Bug / Problema"
    if any(k in t for k in KEYWORDS_SUPORTE):
        return "[OK] Resposta Suporte"
    return "[INFO] Geral"

CATEGORIA_CORES = {
    "[CRIT] Indisponibilidade": ("FFC7CE", "9C0006"),
    "[WARN] Bug / Problema":    ("FFE699", "833C00"),
    "[OK] Resposta Suporte":  ("C6EFCE", "375623"),
    "[INFO] Geral":             ("F2F2F2", "444444"),
}

# ── 4. Gera Excel ─────────────────────────────────────────────────────────────
def gerar_excel(rows, dias: int):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts     = datetime.now().strftime("%Y%m%d_%H%M")
    output = os.path.join(OUTPUT_DIR, f"Cismetro_Mensagens_{ts}.xlsx")

    wb = Workbook()

    # ── Aba 1: Mensagens ──────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Mensagens"
    ws.freeze_panes = "A2"

    headers = ["#", "Data/Hora", "Remetente", "Mensagem", "Categoria", "De Mim?"]
    widths  = [5, 18, 22, 80, 22, 8]

    for col, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill      = make_fill("1F3964")
        cell.font      = make_font(bold=True, color="FFFFFF", size=10)
        cell.alignment = CENTER
        cell.border    = BORDER
        ws.column_dimensions[get_column_letter(col)].width = w

    ws.row_dimensions[1].height = 22

    data_rows = []
    for msg in rows:
        ts_val = msg["timestamp"]
        try:
            dt = datetime.fromisoformat(ts_val) if isinstance(ts_val, str) else datetime.fromtimestamp(ts_val)
        except Exception:
            dt = datetime.now()

        content  = msg["content"] or ""
        sender   = msg["sender_name"] or msg["sender"] or "?"
        from_me  = "Sim" if msg["is_from_me"] else "Não"
        categoria = classify(content)
        data_rows.append((dt, sender, content, categoria, from_me))

    for i, (dt, sender, content, categoria, from_me) in enumerate(data_rows, 1):
        bg, fg = CATEGORIA_CORES.get(categoria, ("FFFFFF", "000000"))
        row_fill = make_fill(bg)

        ws.cell(row=i+1, column=1, value=i).alignment           = CENTER
        ws.cell(row=i+1, column=2, value=dt.strftime("%d/%m/%Y %H:%M")).alignment = CENTER
        ws.cell(row=i+1, column=3, value=sender).alignment      = LEFT
        ws.cell(row=i+1, column=4, value=content).alignment     = LEFT
        cell_cat = ws.cell(row=i+1, column=5, value=categoria)
        cell_cat.alignment = CENTER
        cell_cat.font      = make_font(bold=True, color=fg)
        ws.cell(row=i+1, column=6, value=from_me).alignment     = CENTER

        for col in range(1, 7):
            c = ws.cell(row=i+1, column=col)
            if col != 5:
                c.fill = row_fill
                c.font = make_font(size=9)
            c.border = BORDER
        ws.row_dimensions[i+1].height = 55

    ws.auto_filter.ref = f"A1:F{len(data_rows)+1}"

    # ── Aba 2: Resumo ─────────────────────────────────────────────────────────
    ws2 = wb.create_sheet("Resumo")

    periodo_inicio = (datetime.now() - timedelta(days=dias)).strftime("%d/%m/%Y")
    periodo_fim    = datetime.now().strftime("%d/%m/%Y")

    ws2["B2"] = f"RELATÓRIO AUTOMÁTICO — {CHAT_NAME.upper()}"
    ws2["B2"].font = Font(bold=True, size=14, color="1F3964", name="Calibri")
    ws2.merge_cells("B2:F2")

    ws2["B3"] = f"Período: {periodo_inicio} a {periodo_fim}  |  Total de mensagens: {len(data_rows)}  |  Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws2["B3"].font = Font(italic=True, size=9, color="595959", name="Calibri")
    ws2.merge_cells("B3:F3")

    # Contagem por categoria
    cat_count = Counter(r[3] for r in data_rows)
    ws2["B5"] = "MENSAGENS POR CATEGORIA"
    ws2["B5"].font = make_font(bold=True, color="FFFFFF", size=11)
    ws2["B5"].fill = make_fill("1F3964")
    ws2.merge_cells("B5:D5")

    cat_order = ["[CRIT] Indisponibilidade", "[WARN] Bug / Problema", "[OK] Resposta Suporte", "[INFO] Geral"]
    for i, cat in enumerate(cat_order, start=6):
        bg, fg = CATEGORIA_CORES[cat]
        cnt    = cat_count.get(cat, 0)
        pct    = f"{cnt/len(data_rows)*100:.1f}%" if data_rows else "0%"

        lbl = ws2.cell(row=i, column=2, value=cat)
        num = ws2.cell(row=i, column=3, value=cnt)
        pct_cell = ws2.cell(row=i, column=4, value=pct)

        for c in (lbl, num, pct_cell):
            c.fill   = make_fill(bg)
            c.font   = make_font(bold=True, color=fg)
            c.border = BORDER
            c.alignment = CENTER
        lbl.alignment = Alignment(horizontal="left", vertical="center")

    # Top remetentes
    sender_count = Counter(r[1] for r in data_rows if r[4] == "Não")  # excluir próprias
    ws2["B12"] = "TOP 10 REMETENTES (Externos)"
    ws2["B12"].font = make_font(bold=True, color="FFFFFF", size=11)
    ws2["B12"].fill = make_fill("1F3964")
    ws2.merge_cells("B12:D12")

    for i, (name, cnt) in enumerate(sender_count.most_common(10), start=13):
        ws2.cell(row=i, column=2, value=name).font = make_font(size=9)
        ws2.cell(row=i, column=3, value=cnt).font  = make_font(bold=True, size=9)
        ws2.cell(row=i, column=3).alignment = CENTER
        bar = "█" * min(cnt, 20)
        ws2.cell(row=i, column=4, value=bar).font = Font(color="1F3964", size=9, name="Calibri")
        ws2.cell(row=i, column=2).border = ws2.cell(row=i, column=3).border = BORDER

    # Dias com mais incidentes
    inc_por_dia = Counter(
        r[0].strftime("%d/%m/%Y") for r in data_rows
        if r[3] in ("[CRIT] Indisponibilidade", "[WARN] Bug / Problema")
    )
    ws2["F5"] = "DIAS COM MAIS INCIDENTES"
    ws2["F5"].font = make_font(bold=True, color="FFFFFF", size=11)
    ws2["F5"].fill = make_fill("1F3964")
    ws2.merge_cells("F5:H5")

    for i, (day, cnt) in enumerate(inc_por_dia.most_common(10), start=6):
        ws2.cell(row=i, column=6, value=day).font  = make_font(size=9)
        ws2.cell(row=i, column=7, value=cnt).font  = make_font(bold=True, size=9)
        ws2.cell(row=i, column=7).alignment = CENTER
        ws2.cell(row=i, column=6).border = ws2.cell(row=i, column=7).border = BORDER

    for col, w in [("B",28),("C",10),("D",25),("E",4),("F",14),("G",8),("H",20)]:
        ws2.column_dimensions[col].width = w

    # ── Aba 3: Incidentes ─────────────────────────────────────────────────────
    ws3 = wb.create_sheet("Incidentes")
    ws3.freeze_panes = "A2"
    inc_headers = ["#", "Data/Hora", "Remetente", "Mensagem", "Categoria"]
    inc_widths  = [5, 18, 22, 90, 22]

    for col, (h, w) in enumerate(zip(inc_headers, inc_widths), 1):
        cell = ws3.cell(row=1, column=col, value=h)
        cell.fill      = make_fill("C00000")
        cell.font      = make_font(bold=True, color="FFFFFF", size=10)
        cell.alignment = CENTER
        cell.border    = BORDER
        ws3.column_dimensions[get_column_letter(col)].width = w

    inc_data = [(dt, s, c, cat, fm) for (dt, s, c, cat, fm) in data_rows
                if cat in ("[CRIT] Indisponibilidade", "[WARN] Bug / Problema")]
    for i, (dt, sender, content, cat, _) in enumerate(inc_data, 1):
        bg, fg = CATEGORIA_CORES[cat]
        ws3.cell(row=i+1, column=1, value=i).alignment           = CENTER
        ws3.cell(row=i+1, column=2, value=dt.strftime("%d/%m/%Y %H:%M")).alignment = CENTER
        ws3.cell(row=i+1, column=3, value=sender).alignment      = LEFT
        ws3.cell(row=i+1, column=4, value=content).alignment     = LEFT
        ws3.cell(row=i+1, column=5, value=cat).font              = make_font(bold=True, color=fg)
        ws3.cell(row=i+1, column=5).alignment                    = CENTER

        for col in range(1, 6):
            c = ws3.cell(row=i+1, column=col)
            c.fill   = make_fill(bg)
            c.border = BORDER
            if col != 5:
                c.font = make_font(size=9)
        ws3.row_dimensions[i+1].height = 55

    ws3.auto_filter.ref = f"A1:E{len(inc_data)+1}"

    wb.save(output)
    return output

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    dias = DIAS_PADRAO
    if len(sys.argv) > 1:
        try:
            dias = int(sys.argv[1])
        except ValueError:
            pass

    print("=" * 55)
    print(f"  AGENTE CISMETRO — Relatório Automático")
    print(f"  Período: últimos {dias} dias")
    print("=" * 55)

    # 1. Bridge
    proc = start_bridge()

    # 2. Mensagens
    try:
        rows = buscar_mensagens(dias)
    except FileNotFoundError as e:
        print(f"[ERRO] {e}")
        print("   Certifique-se de que o bridge foi executado ao menos uma vez.")
        input("\nPressione Enter para sair...")
        sys.exit(1)

    if not rows:
        print("[!]  Nenhuma mensagem encontrada no período.")
        input("\nPressione Enter para sair...")
        sys.exit(0)

    # 3. Relatório
    print("[XLS] Gerando relatório Excel...")
    output = gerar_excel(rows, dias)
    print(f"[OK] Relatório salvo em:\n   {output}")

    # Abre automaticamente
    os.startfile(output)
    print("\n[OK]  Excel aberto. Pressione Enter para sair...")
    input()

if __name__ == "__main__":
    main()

"""
Relatorio Executivo - Suporte Cismetro
=======================================
- Analisa mensagens via Claude AI
- Gera Word formatado para colar no corpo de email
- Compara periodos para identificar tendencias
"""

import os, sys, sqlite3, json, glob
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

# ── API Key: variavel de ambiente (definida pelo .bat) ou arquivo .apikey ─────
KEY_FILE = Path(__file__).parent / ".anthropic_key"

def get_api_key():
    # 1. Variavel de ambiente (passada pelo .bat)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    # 2. Arquivo salvo
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    print("\n[ERRO] API Key da Anthropic nao encontrada.")
    print("  Execute pelo arquivo 'Gerar Relatorio Cismetro.bat'")
    print("  ou defina a variavel de ambiente ANTHROPIC_API_KEY.")
    sys.exit(1)

import anthropic

try:
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "python-docx", "-q"])
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH    = os.path.join(os.path.expanduser("~"), "store", "messages.db")
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Relatorios_Cismetro")
CHAT_JID   = "120363418632425656@g.us"
CHAT_NAME  = "Suporte Cismetro"
DIAS       = int(sys.argv[1]) if len(sys.argv) > 1 else 30

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── 1. Busca mensagens ────────────────────────────────────────────────────────
def buscar_mensagens(dias):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    after = (datetime.now() - timedelta(days=dias)).isoformat()
    cur.execute("""
        SELECT m.timestamp, m.content, m.is_from_me,
               COALESCE(c.name, m.sender) AS sender_name
        FROM messages m
        LEFT JOIN chats c ON c.jid = m.sender
        WHERE m.chat_jid = ?
          AND m.timestamp >= ?
          AND m.content IS NOT NULL AND m.content != ''
          AND (m.media_type IS NULL OR m.media_type = '')
        ORDER BY m.timestamp ASC
    """, (CHAT_JID, after))
    rows = cur.fetchall()

    # Periodo anterior (para tendencias)
    before_after  = (datetime.now() - timedelta(days=dias*2)).isoformat()
    before_before = after
    cur.execute("""
        SELECT m.timestamp, m.content, m.is_from_me,
               COALESCE(c.name, m.sender) AS sender_name
        FROM messages m
        LEFT JOIN chats c ON c.jid = m.sender
        WHERE m.chat_jid = ?
          AND m.timestamp >= ? AND m.timestamp < ?
          AND m.content IS NOT NULL AND m.content != ''
          AND (m.media_type IS NULL OR m.media_type = '')
        ORDER BY m.timestamp ASC
    """, (CHAT_JID, before_after, before_before))
    rows_prev = cur.fetchall()
    conn.close()
    return rows, rows_prev

def formatar_msgs(rows):
    lines = []
    for r in rows:
        ts = r["timestamp"][:16] if r["timestamp"] else "?"
        origem = "SUPORTE" if r["is_from_me"] or "suporte" in (r["sender_name"] or "").lower() else r["sender_name"]
        lines.append(f"[{ts}] {origem}: {r['content']}")
    return "\n".join(lines)

# ── 2. Analise via Claude ─────────────────────────────────────────────────────
def analisar_com_claude(msgs_atual, msgs_prev, dias):
    key = get_api_key()
    client = anthropic.Anthropic(api_key=key)

    periodo_atual = f"ultimos {dias} dias"
    periodo_prev  = f"periodo anterior ({dias} dias antes)"

    prompt = f"""Voce e um analista de qualidade de sistemas de saude. Analise as mensagens do grupo de suporte do sistema Cismetro (sistema de regulacao de saude municipal) e gere um relatorio executivo em PORTUGUES BRASILEIRO.

=== MENSAGENS DO PERIODO ATUAL ({periodo_atual}) ===
{msgs_atual[:12000]}

=== MENSAGENS DO PERIODO ANTERIOR ({periodo_prev}) ===
{msgs_prev[:6000] if msgs_prev else "Sem dados do periodo anterior."}

Gere um relatorio executivo estruturado com as seguintes secoes. Use linguagem direta, profissional e objetiva. Seja especifico com exemplos das mensagens.

Retorne EXATAMENTE neste formato JSON (sem markdown, sem ```):
{{
  "periodo": "string com o periodo analisado",
  "resumo_executivo": "2-3 paragrafos resumindo o estado geral do sistema e suporte no periodo",
  "problemas_criticos": [
    {{"titulo": "nome do problema", "descricao": "descricao detalhada", "frequencia": "alta/media/baixa", "impacto": "descricao do impacto operacional", "exemplos": "trecho real das mensagens"}}
  ],
  "reclamacoes_frequentes": [
    {{"reclamacao": "descricao", "municipios_afetados": "lista", "frequencia_estimada": "numero de ocorrencias"}}
  ],
  "pontos_positivos": ["lista de aspectos positivos observados"],
  "tendencias": {{
    "positivas": ["lista de tendencias positivas comparando com periodo anterior"],
    "negativas": ["lista de tendencias negativas comparando com periodo anterior"],
    "sem_dados_anteriores": true/false
  }},
  "recomendacoes_prioritarias": [
    {{"prioridade": 1, "acao": "acao especifica", "justificativa": "por que e urgente"}}
  ],
  "indicadores": {{
    "total_mensagens": 0,
    "mensagens_problema": 0,
    "municipios_afetados": "lista de municipios mencionados",
    "dias_com_indisponibilidade": 0
  }}
}}"""

    print("  Analisando mensagens com Claude AI...")
    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
    except anthropic.AuthenticationError:
        # Apaga key invalida para forcar nova entrada no proximo .bat
        if KEY_FILE.exists():
            KEY_FILE.unlink()
        print("\n[ERRO] API Key invalida ou expirada.")
        print("  O arquivo de key foi removido.")
        print("  Execute o .bat novamente e informe uma key valida.")
        sys.exit(1)

    raw = response.content[0].text.strip()
    # limpa possivel markdown
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)

# ── 3. Helpers Word ───────────────────────────────────────────────────────────
def set_para_spacing(para, before=0, after=6):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    pPr = para._p.get_or_add_pPr()
    spacing = OxmlElement('w:spacing')
    spacing.set(qn('w:before'), str(before))
    spacing.set(qn('w:after'),  str(after))
    pPr.append(spacing)

def add_heading(doc, text, level=1, color="1F3964"):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    if level == 1:
        run.font.size = Pt(13)
        run.font.color.rgb = RGBColor(0x1F, 0x39, 0x64)
        # linha separadora
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '6')
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), '1F3964')
        pBdr.append(bottom)
        p._p.get_or_add_pPr().append(pBdr)
    elif level == 2:
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(0x2E, 0x75, 0xB6)
    else:
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0x40, 0x40, 0x40)
    set_para_spacing(p, before=120, after=40)
    return p

def add_bullet(doc, text, bold_prefix=None, color=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        r = p.add_run(bold_prefix + " ")
        r.bold = True
        if color:
            r.font.color.rgb = color
    p.add_run(text).font.size = Pt(10)
    set_para_spacing(p, before=0, after=3)
    return p

def add_numbered(doc, text, num):
    p = doc.add_paragraph()
    r1 = p.add_run(f"{num}. ")
    r1.bold = True
    r1.font.color.rgb = RGBColor(0x1F, 0x39, 0x64)
    p.add_run(text).font.size = Pt(10)
    set_para_spacing(p, before=0, after=4)
    return p

def add_highlight_box(doc, text, bg="FFF2CC", fg="7F6000"):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(9)
    r, g, b = int(fg[0:2],16), int(fg[2:4],16), int(fg[4:6],16)
    run.font.color.rgb = RGBColor(r, g, b)
    run.italic = True
    # fundo via shading
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), bg)
    pPr.append(shd)
    p.paragraph_format.left_indent = Inches(0.2)
    p.paragraph_format.right_indent = Inches(0.2)
    set_para_spacing(p, before=20, after=20)
    return p

def add_divider(doc):
    p = doc.add_paragraph()
    run = p.add_run("")
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '2')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), 'CCCCCC')
    pBdr.append(bottom)
    pPr.append(pBdr)
    set_para_spacing(p, before=40, after=40)

# ── 4. Gera Word ──────────────────────────────────────────────────────────────
SEVERIDADE_CORES = {
    "alta":  (RGBColor(0xC0, 0x00, 0x00), "FFC7CE"),
    "media": (RGBColor(0x83, 0x3C, 0x00), "FFE699"),
    "baixa": (RGBColor(0x37, 0x56, 0x23), "C6EFCE"),
}

def gerar_word(dados, dias, n_atual, n_prev):
    ts     = datetime.now().strftime("%Y%m%d_%H%M")
    output = os.path.join(OUTPUT_DIR, f"Relatorio_Executivo_{ts}.docx")
    doc    = Document()

    # Margens compactas (bom para email)
    for section in doc.sections:
        section.top_margin    = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # Fonte padrao
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(10)

    # ── Cabecalho ─────────────────────────────────────────────────────────────
    titulo = doc.add_paragraph()
    titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = titulo.add_run("RELATORIO EXECUTIVO")
    r.bold = True
    r.font.size = Pt(16)
    r.font.color.rgb = RGBColor(0x1F, 0x39, 0x64)
    set_para_spacing(titulo, before=0, after=4)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = sub.add_run(f"Grupo Suporte Cismetro  |  {dados['periodo']}")
    r2.font.size = Pt(10)
    r2.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
    set_para_spacing(sub, before=0, after=4)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r3 = meta.add_run(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y as %H:%M')}  |  "
        f"{n_atual} mensagens analisadas"
        + (f"  |  Periodo anterior: {n_prev} mensagens" if n_prev else "")
    )
    r3.font.size = Pt(8)
    r3.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    r3.italic = True
    set_para_spacing(meta, before=0, after=60)

    add_divider(doc)

    # ── Resumo Executivo ──────────────────────────────────────────────────────
    add_heading(doc, "RESUMO EXECUTIVO")
    for paragrafo in dados["resumo_executivo"].split("\n"):
        if paragrafo.strip():
            p = doc.add_paragraph(paragrafo.strip())
            p.font = doc.styles['Normal'].font
            set_para_spacing(p, before=0, after=6)

    add_divider(doc)

    # ── Indicadores ───────────────────────────────────────────────────────────
    ind = dados.get("indicadores", {})
    if ind:
        add_heading(doc, "INDICADORES DO PERIODO")
        table = doc.add_table(rows=1, cols=4)
        table.style = 'Table Grid'
        kpis = [
            ("Total de mensagens",       str(ind.get("total_mensagens", n_atual))),
            ("Mensagens de problema",    str(ind.get("mensagens_problema", "—"))),
            ("Dias c/ indisponibilidade",str(ind.get("dias_com_indisponibilidade", "—"))),
            ("Municipios afetados",       str(ind.get("municipios_afetados", "—"))[:30]),
        ]
        hdr = table.rows[0].cells
        for i, (label, valor) in enumerate(kpis):
            cell = hdr[i]
            cell.paragraphs[0].clear()
            p = cell.paragraphs[0]
            r_l = p.add_run(label + "\n")
            r_l.font.size = Pt(8)
            r_l.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
            r_v = p.add_run(valor)
            r_v.bold = True
            r_v.font.size = Pt(13)
            r_v.font.color.rgb = RGBColor(0x1F, 0x39, 0x64)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            # fundo azul claro
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), 'DEEAF1')
            tcPr.append(shd)
        doc.add_paragraph()
        add_divider(doc)

    # ── Problemas Criticos ────────────────────────────────────────────────────
    problemas = dados.get("problemas_criticos", [])
    if problemas:
        add_heading(doc, "PROBLEMAS CRITICOS IDENTIFICADOS")
        for i, prob in enumerate(problemas, 1):
            freq = prob.get("frequencia", "media").lower()
            cor_font, cor_bg = SEVERIDADE_CORES.get(freq, SEVERIDADE_CORES["media"])

            # Titulo do problema
            p_titulo = doc.add_paragraph()
            r_num = p_titulo.add_run(f"  {i}. ")
            r_num.bold = True
            r_num.font.color.rgb = cor_font
            r_tit = p_titulo.add_run(prob.get("titulo", ""))
            r_tit.bold = True
            r_tit.font.size = Pt(10)
            badge = p_titulo.add_run(f"  [ {freq.upper()} ]")
            badge.bold = True
            badge.font.size = Pt(8)
            badge.font.color.rgb = cor_font
            pPr = p_titulo._p.get_or_add_pPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), cor_bg)
            pPr.append(shd)
            set_para_spacing(p_titulo, before=60, after=2)

            # Descricao
            p_desc = doc.add_paragraph()
            p_desc.paragraph_format.left_indent = Inches(0.25)
            p_desc.add_run(prob.get("descricao", "")).font.size = Pt(10)
            set_para_spacing(p_desc, before=2, after=2)

            # Impacto
            if prob.get("impacto"):
                p_imp = doc.add_paragraph()
                p_imp.paragraph_format.left_indent = Inches(0.25)
                r_i = p_imp.add_run("Impacto: ")
                r_i.bold = True
                r_i.font.color.rgb = RGBColor(0x83, 0x3C, 0x00)
                p_imp.add_run(prob["impacto"]).font.size = Pt(9)
                set_para_spacing(p_imp, before=0, after=2)

            # Exemplo
            if prob.get("exemplos"):
                add_highlight_box(doc, f'"{prob["exemplos"][:200]}"')

        add_divider(doc)

    # ── Reclamacoes Frequentes ────────────────────────────────────────────────
    reclamacoes = dados.get("reclamacoes_frequentes", [])
    if reclamacoes:
        add_heading(doc, "RECLAMACOES MAIS FREQUENTES")
        table = doc.add_table(rows=1 + len(reclamacoes), cols=3)
        table.style = 'Table Grid'

        # Cabecalho
        for col, txt in enumerate(["Reclamacao", "Municipios Afetados", "Freq. Estimada"]):
            c = table.rows[0].cells[col]
            c.text = txt
            c.paragraphs[0].runs[0].bold = True
            c.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            tc = c._tc
            tcPr = tc.get_or_add_tcPr()
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), '1F3964')
            tcPr.append(shd)

        for i, rec in enumerate(reclamacoes, 1):
            row = table.rows[i].cells
            row[0].text = rec.get("reclamacao", "")
            row[1].text = rec.get("municipios_afetados", "—")
            row[2].text = str(rec.get("frequencia_estimada", "—"))
            row[2].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            # linha alternada
            if i % 2 == 0:
                for cell in row:
                    tc = cell._tc
                    tcPr = tc.get_or_add_tcPr()
                    shd = OxmlElement('w:shd')
                    shd.set(qn('w:val'), 'clear')
                    shd.set(qn('w:color'), 'auto')
                    shd.set(qn('w:fill'), 'EBF3FB')
                    tcPr.append(shd)
            for cell in row:
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(9)

        doc.add_paragraph()
        add_divider(doc)

    # ── Tendencias ────────────────────────────────────────────────────────────
    tend = dados.get("tendencias", {})
    add_heading(doc, "ANALISE DE TENDENCIAS")

    if tend.get("sem_dados_anteriores"):
        p = doc.add_paragraph()
        p.add_run("Dados de periodo anterior insuficientes para analise de tendencias. "
                  "Esta analise estara disponivel na proxima geracao de relatorio.").italic = True
        p.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    else:
        if tend.get("positivas"):
            add_heading(doc, "Tendencias Positivas", level=2)
            for t in tend["positivas"]:
                add_bullet(doc, t, bold_prefix="(+)")
        if tend.get("negativas"):
            add_heading(doc, "Tendencias Negativas", level=2)
            for t in tend["negativas"]:
                add_bullet(doc, t, bold_prefix="(-)",
                           color=RGBColor(0xC0, 0x00, 0x00))

    add_divider(doc)

    # ── Pontos Positivos ──────────────────────────────────────────────────────
    positivos = dados.get("pontos_positivos", [])
    if positivos:
        add_heading(doc, "PONTOS POSITIVOS")
        for pt in positivos:
            add_bullet(doc, pt)
        add_divider(doc)

    # ── Recomendacoes ─────────────────────────────────────────────────────────
    recomendacoes = dados.get("recomendacoes_prioritarias", [])
    if recomendacoes:
        add_heading(doc, "RECOMENDACOES PRIORITARIAS")
        for rec in sorted(recomendacoes, key=lambda x: x.get("prioridade", 99)):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.1)
            r_num = p.add_run(f"  {rec.get('prioridade','?')}. ")
            r_num.bold = True
            r_num.font.color.rgb = RGBColor(0x1F, 0x39, 0x64)
            r_ac = p.add_run(rec.get("acao", ""))
            r_ac.bold = True
            r_ac.font.size = Pt(10)
            set_para_spacing(p, before=40, after=2)
            if rec.get("justificativa"):
                p2 = doc.add_paragraph()
                p2.paragraph_format.left_indent = Inches(0.35)
                p2.add_run(rec["justificativa"]).font.size = Pt(9)
                p2.runs[0].font.color.rgb = RGBColor(0x59, 0x59, 0x59)
                set_para_spacing(p2, before=0, after=6)

    # ── Rodape ────────────────────────────────────────────────────────────────
    add_divider(doc)
    rodape = doc.add_paragraph()
    rodape.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_rod = rodape.add_run(
        f"Relatorio gerado automaticamente em {datetime.now().strftime('%d/%m/%Y as %H:%M')} "
        f"a partir das mensagens do grupo WhatsApp \"{CHAT_NAME}\". "
        f"Analise por Claude AI (Anthropic)."
    )
    r_rod.font.size = Pt(7)
    r_rod.font.color.rgb = RGBColor(0xA0, 0xA0, 0xA0)
    r_rod.italic = True

    doc.save(output)
    return output

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print(f"  RELATORIO EXECUTIVO CISMETRO")
    print(f"  Periodo: ultimos {DIAS} dias")
    print("=" * 55)

    print("  Buscando mensagens...")
    rows_atual, rows_prev = buscar_mensagens(DIAS)

    if not rows_atual:
        print("[!] Nenhuma mensagem encontrada no periodo.")
        sys.exit(0)

    print(f"  Periodo atual:    {len(rows_atual)} mensagens")
    print(f"  Periodo anterior: {len(rows_prev)} mensagens")

    msgs_atual = formatar_msgs(rows_atual)
    msgs_prev  = formatar_msgs(rows_prev)

    dados = analisar_com_claude(msgs_atual, msgs_prev, DIAS)

    print("  Gerando Word...")
    output = gerar_word(dados, DIAS, len(rows_atual), len(rows_prev))
    print(f"  Salvo em: {output}")
    os.startfile(output)

if __name__ == "__main__":
    main()

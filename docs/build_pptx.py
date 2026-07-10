#!/usr/bin/env python3
"""Gera docs/apresentacao_final.pptx a partir do template de proposta."""
import json
import re
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

REPO = Path(__file__).resolve().parent.parent
FIG = REPO / "analysis" / "figures"
ASSETS = REPO / "docs" / "assets"
VIDEO = REPO / "docs" / "run.mp4"
POSTER = ASSETS / "run_poster.jpg"
TEMPLATE = REPO / "docs" / "apresentacao_destracionamento.pptx"
OUT = REPO / "docs" / "apresentacao_final.pptx"

TEAL = RGBColor(0x37, 0x80, 0x90)
DARK = RGBColor(0x1F, 0x4F, 0x59)
GOLD = RGBColor(0xE4, 0xC0, 0x4C)
GRAY = RGBColor(0x66, 0x66, 0x66)
BODY = RGBColor(0x33, 0x33, 0x33)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xF2, 0xF5, 0xF6)
FONT = "Calibri"

FT = json.loads((REPO / "analysis/derived/final_test.json").read_text())


# ---------- helpers de baixo nível ------------------------------------------
def _sldIdLst(prs):
    return prs.slides._sldIdLst


def delete_all(prs):
    lst = _sldIdLst(prs)
    for el in list(lst):
        prs.part.drop_rel(el.get(qn("r:id")))
        lst.remove(el)


def add_blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[0])


def reorder(prs, ordered):
    lst = _sldIdLst(prs)
    m = {id(s): el for s, el in zip(list(prs.slides), list(lst))}
    for el in list(lst):
        lst.remove(el)
    for s in ordered:
        lst.append(m[id(s)])


def _set_run(r, text, size, color, bold=False, font=FONT):
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.name = font
    r.font.color.rgb = color


def textbox(slide, l, t, w, h, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    return tb, tf


def title(slide, text, sub=None):
    _, tf = textbox(slide, 0.5, 0.28, 9.0, 0.6)
    _set_run(tf.paragraphs[0].add_run(), text, 27, TEAL, bold=True)
    if sub:
        _, sf = textbox(slide, 0.5, 1.0, 9.0, 0.45)
        _set_run(sf.paragraphs[0].add_run(), sub, 14, GRAY)


def bullets(slide, items, l=0.6, t=1.7, w=8.8, h=3.3, size=14, gap=8):
    _, tf = textbox(slide, l, t, w, h)
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap)
        _set_run(p.add_run(), "▸  ", size, GOLD, bold=True)
        if isinstance(it, tuple):
            _set_run(p.add_run(), it[0] + "  ", size, DARK, bold=True)
            _set_run(p.add_run(), it[1], size, BODY)
        else:
            _set_run(p.add_run(), it, size, BODY)
    return tf


def image_fit(slide, path, l, t, w, h):
    pic = slide.shapes.add_picture(str(path), Inches(l), Inches(t))
    scale = min(Inches(w) / pic.width, Inches(h) / pic.height)
    pic.width = int(pic.width * scale)
    pic.height = int(pic.height * scale)
    pic.left = Inches(l) + (Inches(w) - pic.width) // 2
    pic.top = Inches(t) + (Inches(h) - pic.height) // 2
    return pic


def caption(slide, text, t=4.85, size=11):
    _, tf = textbox(slide, 0.5, t, 9.0, 0.35, MSO_ANCHOR.MIDDLE)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    _set_run(p.add_run(), text, size, DARK, bold=True)


def add_name_footer(slide):
    _, tf = textbox(slide, 0.4, 5.28, 8.5, 0.22)
    _set_run(tf.paragraphs[0].add_run(),
             "Gabriel Martins Lima  •  Data Science  •  PUC-Rio", 9, GRAY)


def set_pagenum(slide, n, total=14):
    for sh in slide.shapes:
        if sh.has_text_frame and re.fullmatch(r"\s*\d+\s*/\s*\d+\s*", sh.text_frame.text or ""):
            r = sh.text_frame.paragraphs[0].runs[0]
            r.text = f"{n} / {total}"
            return
    _, tf = textbox(slide, 8.9, 5.28, 1.0, 0.22)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    _set_run(p.add_run(), f"{n} / {total}", 9, GRAY)


def style_table(tbl, header_fill=TEAL, body_size=10, header_size=11):
    for c, cell in enumerate(tbl.rows[0].cells):
        cell.fill.solid()
        cell.fill.fore_color.rgb = header_fill
        for p in cell.text_frame.paragraphs:
            for r in p.runs:
                r.font.bold = True
                r.font.color.rgb = WHITE
                r.font.size = Pt(header_size)
                r.font.name = FONT
    for ri, row in enumerate(list(tbl.rows)[1:], start=1):
        for cell in row.cells:
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if ri % 2 else LIGHT
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(body_size)
                    r.font.name = FONT
                    r.font.color.rgb = BODY


def cell(tbl, r, c, text, size=10, bold=False, color=BODY, align=PP_ALIGN.LEFT):
    cl = tbl.cell(r, c)
    cl.vertical_anchor = MSO_ANCHOR.MIDDLE
    cl.margin_left = cl.margin_right = Inches(0.06)
    cl.margin_top = cl.margin_bottom = Inches(0.02)
    tf = cl.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    _set_run(p.add_run(), text, size, color, bold=bold)


# ---------- slides recriados (capa + robô) ----------------------------------
def build_capa(prs):
    sl = add_blank(prs)
    bar = sl.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.28), prs.slide_height)
    bar.fill.solid(); bar.fill.fore_color.rgb = TEAL
    bar.line.fill.background(); bar.shadow.inherit = False
    sl.shapes.add_picture(str(ASSETS / "logo.jpg"), Inches(8.4), Inches(0.4),
                          Inches(1.2), Inches(1.2))
    _, tf = textbox(sl, 0.8, 1.5, 8.6, 0.8)
    _set_run(tf.paragraphs[0].add_run(), "Detecção de destracionamento", 34, DARK, bold=True)
    _, tf2 = textbox(sl, 0.8, 2.35, 8.7, 0.7)
    _set_run(tf2.paragraphs[0].add_run(),
             "em robô diferencial via aprendizado de máquina", 24, TEAL, bold=True)
    rule = sl.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.85), Inches(3.18),
                               Inches(1.2), Inches(0.05))
    rule.fill.solid(); rule.fill.fore_color.rgb = GOLD
    rule.line.fill.background(); rule.shadow.inherit = False
    _, tf3 = textbox(sl, 0.8, 3.4, 8.5, 0.4)
    _set_run(tf3.paragraphs[0].add_run(),
             "Apresentação de resultados — trabalho final", 14, GRAY)
    _, tf4 = textbox(sl, 0.8, 5.0, 8.5, 0.3)
    _set_run(tf4.paragraphs[0].add_run(), "PUC-Rio  •  2026.1", 12, TEAL)
    return sl


def build_robo(prs):
    sl = add_blank(prs)
    title(sl, "O robô")
    _, tf = textbox(sl, 0.5, 1.15, 4.0, 0.4)
    _set_run(tf.paragraphs[0].add_run(), "Especificações", 16, DARK, bold=True)
    specs = [("Configuração diferencial", "2 rodas tracionadas + roda boba"),
             ("Tração independente", "Um motor por roda, com PID dedicado"),
             ("Operação indoor", "Pisos lisos: madeira, cimento queimado"),
             ("Eletrônica embarcada", "STM32F103 + ESP8266 (telemetria via WiFi/UDP)")]
    _, sf = textbox(sl, 0.5, 1.62, 4.2, 3.4)
    for i, (h, b) in enumerate(specs):
        ph = sf.paragraphs[0] if i == 0 else sf.add_paragraph()
        ph.space_after = Pt(3)
        _set_run(ph.add_run(), h, 13.5, TEAL, bold=True)
        pb = sf.add_paragraph(); pb.space_after = Pt(11)
        _set_run(pb.add_run(), b, 12.5, BODY)
    image_fit(sl, ASSETS / "robot.jpg", 4.9, 1.2, 4.6, 3.6)
    return sl


# ---------- montagem --------------------------------------------------------
prs = Presentation(str(TEMPLATE))
delete_all(prs)

s = {}
capa = build_capa(prs)
robo = build_robo(prs)

# 2. Contexto e objetivo
s["ctx"] = add_blank(prs)
title(s["ctx"], "Contexto e objetivo",
      "Detecção de escorregamento (slip) das rodas em tempo real")
bullets(s["ctx"], [
    ("Problema:", "quando a roda escorrega, a odometria por encoders erra — "
     "navegação e segurança do robô ficam comprometidas."),
    ("Objetivo:", "detectar o slip de cada roda usando APENAS sensores "
     "embarcados (encoders + IMU)."),
    ("Ground truth:", "câmera externa SSL-Vision serve só para rotular os dados "
     "— nunca entra como entrada do modelo."),
    ("Requisitos:", "detector causal, em tempo real e embarcável (Raspberry Pi)."),
], t=1.75, size=15, gap=12)

# 4. Vídeo (run.mp4 embutido, 16:9)
s["video"] = add_blank(prs)
title(s["video"], "Coleta de dados — robô em operação",
      "Vídeo das sessões de captura")
vw, vh = 6.4, 3.6                       # 16:9
s["video"].shapes.add_movie(str(VIDEO), Inches((10 - vw) / 2), Inches(1.55),
                            Inches(vw), Inches(vh), poster_frame_image=str(POSTER),
                            mime_type="video/mp4")

# 5. Visão geral do pipeline
s["pipe"] = add_blank(prs)
title(s["pipe"], "Pipeline de processamento", "Da captura à detecção de slip")
image_fit(s["pipe"], FIG / "slip_pipeline.png", 0.4, 1.35, 3.5, 3.65)
bullets(s["pipe"], [
    ("Captura (Fase 1):", "telemetria do robô + câmera → PostgreSQL."),
    ("Rotulagem (Stages 1–4):", "dados brutos → rótulos de slip por roda."),
    ("Modelagem (Stage 5):", "features causais → 5 modelos, validação e teste."),
], l=4.2, t=2.0, w=5.4, size=15, gap=16)

# 6. Fase 1 — captura
s["cap"] = add_blank(prs)
title(s["cap"], "Fase 1 — Captura de dados",
      "Dois apps em C++ registram tudo com timestamp de recepção")
bullets(s["cap"], [
    ("Robô:", "telemetria UDP a 100 Hz (velocidades e setpoints das rodas, IMU, "
     "estado do LED) → tabela robot.telemetry."),
    ("Câmera SSL-Vision (60 Hz):", "pose do robô (x, y, θ) e a \"bola\" (o LED) "
     "→ tabelas vision.robot_detection / ball_detection."),
    ("Armazenamento:", "PostgreSQL, com rx_wall (timestamp de recepção) em ambos."),
    ("Sincronismo:", "o LED laranja é visto como \"bola\" pela câmera — canal "
     "compartilhado para alinhar os relógios (Stage 1)."),
], t=1.7, size=14, gap=11)

# 7-10. Stages com figura
stage_slides = [
    ("s1", "Stage 1 — Sincronização temporal",
     "Alinhar o relógio do robô ao da câmera",
     "stage1_timesync_2026-06-28_175903+0000.png",
     "Ajuste robusto  t_capture ≈ a·(packet_id·0,01) + b  pelas bordas do LED e da bola; "
     "corrige a deriva do cristal."),
    ("s2", "Stage 2 — Reamostragem para 100 Hz",
     "Pose da câmera (60 Hz) na grade do robô (100 Hz)",
     "stage2_resample_2026-06-28_175903+0000.png",
     "Spline suavizadora → posição, velocidade e ω; gaps de câmera > 100 ms são mascarados."),
    ("s3", "Stage 3 — Cinemática inversa",
     "Movimento medido pela câmera → velocidade de solo por roda",
     "stage3_kinematics_2026-06-28_175903+0000_setpoint.png",
     "v_ground = v_tangent ∓ ω·(track/2);  correlação encoder ↔ câmera de 0,94–0,97."),
    ("s4", "Stage 4 — Rótulos de slip",
     "O alvo de aprendizado, por roda",
     "stage4_slip_labels.png",
     "slip_vel = v_encoder − v_ground (m/s);  limpeza de outliers e máscara de cobertura."),
]
for key, ttl, sub, fig, cap in stage_slides:
    s[key] = add_blank(prs)
    title(s[key], ttl, sub)
    image_fit(s[key], FIG / fig, 0.5, 1.5, 9.0, 3.2)
    caption(s[key], cap)

# 11. Features (lista)
s["feat_list"] = add_blank(prs)
title(s["feat_list"], "Features — entradas do modelo",
      "15 features causais por roda (janela de 200 ms, só passado)")
cols = [
    ("Instantâneas (7)", [
        ("w", "velocidade da roda"),
        ("w_other", "velocidade da roda oposta"),
        ("sp", "setpoint da roda"),
        ("sp_err", "erro de rastreio (sp − w)"),
        ("ax, ay", "aceleração linear (IMU)"),
        ("gz", "velocidade angular (giro z)"),
    ]),
    ("Estatísticas da janela (6)", [
        ("w_mean, w_std", "média e desvio da velocidade"),
        ("sp_mean", "média do setpoint"),
        ("ax_std, ay_std", "desvio das acelerações"),
        ("gz_std", "desvio do giro"),
    ]),
    ("Dinâmica (2)", [
        ("w_accel", "aceleração da roda na janela"),
        ("sp_rate", "taxa de variação do setpoint"),
    ]),
]
for ci, (hdr, items) in enumerate(cols):
    x = 0.5 + ci * 3.15
    _, hf = textbox(s["feat_list"], x, 1.7, 3.0, 0.4)
    _set_run(hf.paragraphs[0].add_run(), hdr, 14, GOLD, bold=True)
    _, tf = textbox(s["feat_list"], x, 2.18, 3.0, 2.7)
    for j, (nm, desc) in enumerate(items):
        p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
        p.space_after = Pt(8)
        _set_run(p.add_run(), nm, 12, TEAL, bold=True)
        _set_run(p.add_run(), "  " + desc, 11, BODY)
_, nf = textbox(s["feat_list"], 0.5, 4.95, 9.0, 0.35)
_set_run(nf.paragraphs[0].add_run(),
         "Todas estritamente causais (só o passado) → detector em tempo real.",
         12, DARK, bold=True)

# 12. Validação
s["feat"] = add_blank(prs)
title(s["feat"], "Validação — LOSO + holdout temporal",
      "Avaliação sem vazamento de dados")
bullets(s["feat"], [
    ("Alvo:", "slip_vel por roda (m/s)."),
    ("Validação LOSO", "(deixa-uma-sessão-de-fora) no dev = 80% de cada sessão."),
    ("Holdout:", "últimos 20% de cada sessão, intocados até o teste final."),
    ("Split temporal:", "impede o futuro de vazar para o passado."),
], l=0.5, t=1.7, w=4.3, size=13.5, gap=13)
image_fit(s["feat"], FIG / "slip_splits.png", 4.9, 1.55, 4.8, 3.5)

# 12. Otimização + ranges
s["opt"] = add_blank(prs)
title(s["opt"], "Otimização de hiperparâmetros",
      "Optuna (TPE + median pruner) · objetivo = MAE-LOSO · holdout intocado")
rows_opt = [
    ("kNN", "12", "n_neighbors 3–40; weights {uniform, distance}; p {1, 2}"),
    ("Random Forest", "25", "n_estimators 60–200; max_depth 6–24; min_samples_leaf 1–20; "
     "max_features 0,3–1,0"),
    ("XGBoost", "25", "n_estimators 100–600; max_depth 3–10; learning_rate 0,01–0,3 (log); "
     "subsample 0,5–1,0; colsample 0,5–1,0; λ 1e-3–10 (log)"),
    ("MLP", "40", "hidden {64,128,256}×{32,64,128}; lr 1e-4–5e-3 (log); "
     "weight_decay 1e-6–1e-2 (log); huber_δ 0,02–0,5 (log); epochs 20–80"),
    ("ESN", "40×3", "n_res {350…950}; spectral_radius 0,3–1,3; leak 0,05–1,0; "
     "in_scale 0,1–1,5 (log); density 0,05–0,3; ridge 1e-6–1 (log)"),
]
tbl = s["opt"].shapes.add_table(6, 3, Inches(0.5), Inches(1.55),
                                Inches(9.0), Inches(3.3)).table
tbl.columns[0].width = Inches(1.5)
tbl.columns[1].width = Inches(0.8)
tbl.columns[2].width = Inches(6.7)
for c, h in enumerate(("Modelo", "Trials", "Ranges dos hiperparâmetros")):
    cell(tbl, 0, c, h, size=11, align=PP_ALIGN.CENTER if c < 2 else PP_ALIGN.LEFT)
for r, (m, n, rg) in enumerate(rows_opt, start=1):
    cell(tbl, r, 0, m, size=10.5, bold=True, color=DARK)
    cell(tbl, r, 1, n, size=10, align=PP_ALIGN.CENTER)
    cell(tbl, r, 2, rg, size=9.5)
style_table(tbl)

# 14. Otimização — convergência
s["tune"] = add_blank(prs)
title(s["tune"], "Otimização — convergência",
      "Histórico do melhor MAE-LOSO por trial (Optuna TPE + median pruner)")
image_fit(s["tune"], FIG / "slip_tune_history.png", 0.3, 1.95, 9.4, 2.6)
caption(s["tune"], "Clássicos e MLP convergem cedo; o ESN é o mais difícil de tunar.",
        t=4.9)

# 15. ESN — capacidade do reservatório (ablação)
s["ablation"] = add_blank(prs)
title(s["ablation"], "ESN — capacidade do reservatório",
      "Ablação: variando só n_res (demais hiperparâmetros fixos nos melhores)")
image_fit(s["ablation"], FIG / "esn_reservoir_size.png", 0.5, 1.65, 9.0, 2.95)
caption(s["ablation"], "Reservatório maior melhora muito o ESN: MAE 0,039 → 0,032 e "
        "F1 0,85 → 0,88.  Adotado n_res = 950.", t=4.85)

# 16. Resultados finais
s["res"] = add_blank(prs)
title(s["res"], "Resultados finais — teste no holdout",
      "Refit em todo o dev (80%); avaliação única nos 20% reservados")
order = sorted(FT, key=lambda k: FT[k]["mae"])
b_mae = min(FT, key=lambda k: FT[k]["mae"])
b_rmse = min(FT, key=lambda k: FT[k]["rmse"])
b_f1 = max(FT, key=lambda k: FT[k]["f1"])
tbl = s["res"].shapes.add_table(6, 4, Inches(0.5), Inches(1.7),
                                Inches(4.3), Inches(2.6)).table
for w, cw in zip(tbl.columns, (1.7, 0.9, 0.9, 0.8)):
    w.width = Inches(cw)
for c, h in enumerate(("Modelo", "MAE", "RMSE", "F1")):
    cell(tbl, 0, c, h, size=11, align=PP_ALIGN.CENTER if c else PP_ALIGN.LEFT)
for r, k in enumerate(order, start=1):
    cell(tbl, r, 0, k, size=10.5, bold=True, color=DARK)
    for col, (key, fmt, isbest) in enumerate([
            ("mae", "{:.4f}", k == b_mae), ("rmse", "{:.4f}", k == b_rmse),
            ("f1", "{:.3f}", k == b_f1)], start=1):
        cell(tbl, r, col, fmt.format(FT[k][key]), size=10, align=PP_ALIGN.CENTER,
             bold=isbest, color=TEAL if isbest else BODY)
style_table(tbl)
image_fit(s["res"], FIG / "slip_final_test.png", 5.0, 1.7, 4.7, 2.7)
_, tf = textbox(s["res"], 0.5, 4.5, 9.0, 0.55, MSO_ANCHOR.MIDDLE)
_set_run(tf.paragraphs[0].add_run(),
         "MLP lidera em MAE (0,0236); o ESN é o melhor detector (F1 0,902) e o menor "
         "RMSE. Os modelos neurais assumem a dianteira.", 12, DARK, bold=True)

# 16. Predição no tempo (holdout) — zoom
s["ts"] = add_blank(prs)
title(s["ts"], "Predição vs. real no tempo (holdout) — MLP",
      "Zoom em 12–13 s; faixa ±0,20 m/s = limiar de detecção")
image_fit(s["ts"], FIG / "slip_test_timeseries_mlp_zoom.png", 0.4, 1.5, 9.2, 3.3)

# 17. Conclusão
s["concl"] = add_blank(prs)
title(s["concl"], "Conclusão e trabalhos futuros")
bullets(s["concl"], [
    "Detector de slip causal e em tempo real usando só encoders + IMU é viável (F1 ≈ 0,90).",
    "A câmera externa como ground truth permitiu rotular sem sensor extra no robô.",
    ("5 modelos tunados de forma justa (Optuna):", "MLP e ESN na frente — o ESN "
     "virou o melhor detector (F1 0,90) ao ampliar o reservatório."),
    ("Próximos passos:", "export ExecuTorch → inferência no Raspberry Pi; "
     "recaptura com câmera melhor para reduzir gaps."),
], t=1.5, size=15, gap=14)

# 19. Perguntas
s["qa"] = add_blank(prs)
bar = s["qa"].shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.28), prs.slide_height)
bar.fill.solid(); bar.fill.fore_color.rgb = TEAL
bar.line.fill.background(); bar.shadow.inherit = False
s["qa"].shapes.add_picture(str(ASSETS / "logo.jpg"), Inches(8.4), Inches(0.4),
                           Inches(1.2), Inches(1.2))
_, tf = textbox(s["qa"], 0.8, 2.0, 8.6, 1.2, MSO_ANCHOR.MIDDLE)
_set_run(tf.paragraphs[0].add_run(), "Perguntas?", 46, DARK, bold=True)
rule = s["qa"].shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.85), Inches(3.2),
                                Inches(1.2), Inches(0.05))
rule.fill.solid(); rule.fill.fore_color.rgb = GOLD
rule.line.fill.background(); rule.shadow.inherit = False
_, sf = textbox(s["qa"], 0.8, 3.4, 8.6, 0.5)
_set_run(sf.paragraphs[0].add_run(), "Obrigado pela atenção!", 20, TEAL, bold=True)

# 20. Homenagem (in memoriam) — slide de encerramento
s["memoriam"] = add_blank(prs)
image_fit(s["memoriam"], ASSETS / "Hamilko.jpg", 0.8, 0.8, 3.4, 4.05)
_, mf = textbox(s["memoriam"], 4.8, 1.55, 4.6, 0.4)
_set_run(mf.paragraphs[0].add_run(), "Em memória", 16, GRAY)
_, nf = textbox(s["memoriam"], 4.8, 1.95, 4.7, 0.9)
_set_run(nf.paragraphs[0].add_run(), "Hamilko", 40, DARK, bold=True)
rule = s["memoriam"].shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(4.85), Inches(2.95),
                                      Inches(1.2), Inches(0.05))
rule.fill.solid(); rule.fill.fore_color.rgb = GOLD
rule.line.fill.background(); rule.shadow.inherit = False
_, df = textbox(s["memoriam"], 4.8, 3.15, 4.6, 0.4)
_set_run(df.paragraphs[0].add_run(), "26/02/1996  –  23/06/2026", 17, TEAL, bold=True)
_, cf = textbox(s["memoriam"], 4.8, 3.75, 4.5, 1.0)
_set_run(cf.paragraphs[0].add_run(),
         "Dedico este trabalho ao meu grande amigo, com carinho e saudade.", 13.5, BODY)

# ordem final + rodapés + numeração
final = [capa, s["ctx"], robo, s["video"], s["pipe"], s["cap"],
         s["s1"], s["s2"], s["s3"], s["s4"], s["feat_list"], s["feat"],
         s["opt"], s["tune"], s["ablation"], s["res"], s["ts"], s["concl"],
         s["qa"], s["memoriam"]]
reorder(prs, final)
for i, sl in enumerate(final, start=1):
    if i == 1 or sl is s["memoriam"]:   # capa e homenagem: sem rodapé/numeração
        continue
    if not any(sh.has_text_frame and "Gabriel Martins" in (sh.text_frame.text or "")
               for sh in sl.shapes):
        add_name_footer(sl)
    set_pagenum(sl, i, len(final))

prs.save(str(OUT))
print(f"OK -> {OUT}  ({len(list(prs.slides))} slides)")

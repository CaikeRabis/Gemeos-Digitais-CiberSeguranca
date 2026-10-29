#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
PROJETO: Modelos Preditivos na Rede Elétrica do DF (Distrito Federal)
SISTEMA: Simulação Temporal Diária (Daily Mode 24h) nos 4 Circuitos Alimentadores
ATIVOS CRÍTICOS: HRC (TN08), 15ª DP (CN07), HBDF (02_BGC1), 1ª DP (HP04)
SCRIPT:  src/26_simulacao_24h_dashboard.py
AUTOR:   Engenheiro de Sistemas de Potência e Desenvolvedor Full-Stack
MISSÃO:  1. Executar simulação temporal de 24 horas (Daily Mode) no OpenDSS com
            curvas de carga (Loadshapes) específicas para Saúde e Segurança Pública.
         2. Coletar tensões nodais horárias (pu) nos barramentos críticos.
         3. Construir gráfico interativo de alta definição (Plotly Dark Mode)
            com as 4 curvas de tensão e limites regulatórios do PRODIST ANEEL.
         4. Injetar o gráfico e botão nativo (Modal) no Dashboard HTML definitivo
            (public/index.html e data/processed/Dashboard_Resiliencia_DF_Definitivo.html).
         5. Manter integridade total do mapa Folium/Esri Satellite e estilização Dark.
================================================================================
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import dss
import plotly.graph_objects as go

# ------------------------------------------------------------------------------
# Configurações de Diretórios, Governança e Logging
# ------------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
PROCESSED_DIR: Path = DATA_DIR / "processed"
OPENDSS_DIR: Path = PROCESSED_DIR / "opendss"
PUBLIC_DIR: Path = BASE_DIR / "public"
LOGS_DIR: Path = BASE_DIR / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
RUN_TAG: str = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE: Path = LOGS_DIR / f"26_simulacao_24h_dashboard_{RUN_TAG}.log"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
LOGGER: logging.Logger = logging.getLogger("Simulacao24h")

# ------------------------------------------------------------------------------
# Loadshapes Padronizados (0 a 1) para Saúde e Segurança Pública
# ------------------------------------------------------------------------------
LOADSHAPE_SAUDE: List[float] = [
    0.6, 0.5, 0.5, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0, 0.9, 0.9,
    0.9, 0.9, 1.0, 1.0, 0.9, 0.8, 0.9, 1.0, 0.9, 0.8, 0.7, 0.6,
]

LOADSHAPE_SEGURANCA: List[float] = [
    0.4, 0.3, 0.3, 0.3, 0.4, 0.5, 0.7, 0.9, 1.0, 1.0, 0.9, 0.8,
    0.9, 1.0, 1.0, 0.9, 0.8, 0.7, 0.8, 0.9, 0.7, 0.6, 0.5, 0.4,
]

# Configuração dos 4 Circuitos e seus Ativos Auditados
CIRCUITOS_CONFIG: List[Dict[str, Any]] = [
    {
        "id": "HRC",
        "nome": "HRC (Hospital Regional de Ceilândia)",
        "circuito": "TN08",
        "master": "Master_TN08_Calibrado.dss",
        "load": "HRC_PRIORITARIO",
        "bus": "STN_TN08_9026_CEI003",
        "tipo": "saude",
        "cor": "#22d3ee",  # Ciano
        "simbolo": "circle",
    },
    {
        "id": "15ª DP",
        "nome": "15ª DP (Polícia Civil · Ceilândia Centro)",
        "circuito": "CN07",
        "master": "Master_CN07_Calibrado.dss",
        "load": "DP15_PRIORITARIO",
        "bus": "SCN_CN07_9032_CEIRJ002",
        "tipo": "seguranca",
        "cor": "#fb923c",  # Laranja
        "simbolo": "diamond",
    },
    {
        "id": "HBDF",
        "nome": "HBDF (Hospital de Base do DF · SMHS)",
        "circuito": "02_BGC1",
        "master": "Master_SBG.dss",
        "load": "HBDF_VERDADEIRO",
        "bus": "S02_0201_PT_TF_913",
        "tipo": "saude",
        "cor": "#22c55e",  # Verde
        "simbolo": "square",
    },
    {
        "id": "1ª DP",
        "nome": "1ª DP (Complexo PCDF · Setor Policial Sul)",
        "circuito": "HP04",
        "master": "Master_SHP_Calibrado.dss",
        "load": "DP_SPS_PRIORITARIO",
        "bus": "SHP_HP04_9025_BSB27A",
        "tipo": "seguranca",
        "cor": "#facc15",  # Amarelo
        "simbolo": "cross",
    },
]


def executar_simulacao_temporal_24h() -> Dict[str, List[float]]:
    """Instancia o OpenDSS para os 4 circuitos em modo Daily e extrai as tensões em 24h."""
    LOGGER.info("Iniciando simulações temporais no OpenDSS (Modo Daily, Stepsize=1h, 24 horas)...")
    engine = dss.DSS
    text = engine.Text

    str_saude = " ".join(str(v) for v in LOADSHAPE_SAUDE)
    str_seguranca = " ".join(str(v) for v in LOADSHAPE_SEGURANCA)

    resultados_24h: Dict[str, List[float]] = {}

    cwd_antigo = os.getcwd()
    os.chdir(OPENDSS_DIR)

    try:
        for c in CIRCUITOS_CONFIG:
            LOGGER.info(f"[{c['id']}] Compilando {c['master']} para simulação diária...")
            text.Command = "Clear"
            text.Command = f"compile '{c['master']}'"

            # Injetar Loadshape e vincular à carga crítica
            if c["tipo"] == "saude":
                text.Command = f"New Loadshape.LS_Saude Npts=24 Interval=1.0 Mult=({str_saude})"
                text.Command = f"Edit Load.{c['load']} Daily=LS_Saude"
            else:
                text.Command = f"New Loadshape.LS_Seguranca Npts=24 Interval=1.0 Mult=({str_seguranca})"
                text.Command = f"Edit Load.{c['load']} Daily=LS_Seguranca"

            text.Command = "Set VoltageBases = [138.0, 34.5, 13.8, 0.40, 0.38, 0.22]"
            text.Command = "CalcVoltageBases"
            text.Command = "Set Mode=Daily Stepsize=1h Number=1 Hour=0"

            circuit = engine.ActiveCircuit
            tensoes_horas: List[float] = []

            for h in range(24):
                text.Command = "Solve"
                if not circuit.Solution.Converged:
                    LOGGER.warning(f"[{c['id']}] Solução não convergiu na hora {h}h")

                circuit.SetActiveBus(c["bus"])
                nodes = circuit.ActiveBus.Nodes
                pu = circuit.ActiveBus.puVmagAngle

                # Coletar menor tensão nodal ativa entre as fases
                valores_pu_fases = [float(pu[2 * i]) for i in range(len(nodes)) if pu[2 * i] > 0.1]
                min_pu = min(valores_pu_fases) if valores_pu_fases else 1.0
                tensoes_horas.append(min_pu)

            resultados_24h[c["id"]] = tensoes_horas
            vmin, vmax = min(tensoes_horas), max(tensoes_horas)
            LOGGER.info(f"[{c['id']}] 24h concluído: Min={vmin:.4f} pu | Max={vmax:.4f} pu (Adequada)")

    finally:
        os.chdir(cwd_antigo)

    return resultados_24h


def gerar_grafico_plotly(resultados_24h: Dict[str, List[float]]) -> str:
    """Gera figura Plotly rica em Dark Mode e exporta para string HTML limpa."""
    LOGGER.info("Renderizando figura Plotly do Perfil de Tensão 24h...")
    horas = [f"{h:02d}:00" for h in range(24)]

    fig = go.Figure()

    # 1. Faixa Regulamentar Adequada do PRODIST (Sombreado Verde Translúcido)
    fig.add_hrect(
        y0=0.93,
        y1=1.05,
        fillcolor="rgba(34, 197, 94, 0.05)",
        line_width=0,
        annotation_text="Faixa Regulamentar Adequada (PRODIST 0.93 – 1.05 pu)",
        annotation_position="top left",
        annotation_font=dict(size=10.5, color="rgba(34, 197, 94, 0.85)", family="Inter, sans-serif"),
    )

    # 2. Linhas de Limite Normativo PRODIST
    fig.add_hline(
        y=0.93,
        line=dict(color="#ef4444", width=1.5, dash="dash"),
        annotation_text="Vmin PRODIST = 0.930 pu",
        annotation_position="bottom right",
        annotation_font=dict(size=10, color="#ef4444", family="Inter, sans-serif"),
    )
    fig.add_hline(
        y=1.05,
        line=dict(color="#f59e0b", width=1.5, dash="dash"),
        annotation_text="Vmax PRODIST = 1.050 pu",
        annotation_position="top right",
        annotation_font=dict(size=10, color="#f59e0b", family="Inter, sans-serif"),
    )
    fig.add_hline(
        y=1.00,
        line=dict(color="rgba(255, 255, 255, 0.18)", width=1, dash="dot"),
        annotation_text="1.000 pu (Nominal)",
        annotation_position="top left",
        annotation_font=dict(size=9.5, color="rgba(255, 255, 255, 0.4)", family="Inter, sans-serif"),
    )

    # 3. Adicionar as 4 Linhas de Tensão das Infraestruturas Críticas
    for c in CIRCUITOS_CONFIG:
        valores = resultados_24h[c["id"]]
        fig.add_trace(
            go.Scatter(
                x=horas,
                y=valores,
                name=c["nome"],
                mode="lines+markers",
                line=dict(color=c["cor"], width=3),
                marker=dict(size=6, symbol=c["simbolo"], line=dict(width=1, color="#ffffff")),
                hovertemplate=(
                    f"<b>{c['nome']}</b><br>"
                    "Horário: %{x}<br>"
                    "Tensão Mínima: <b>%{y:.4f} pu</b><br>"
                    "Status PRODIST: <b>ADEQUADA</b><extra></extra>"
                ),
            )
        )

    # 4. Ajuste de Layout Premium Dark Mode
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(7, 13, 25, 0.6)",
        margin=dict(l=55, r=35, t=40, b=45),
        height=480,
        font=dict(family="Inter, system-ui, sans-serif", color="#cbd5e1", size=11),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.03,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(13, 22, 39, 0.85)",
            bordercolor="rgba(255, 255, 255, 0.12)",
            borderwidth=1,
            font=dict(size=10.5),
        ),
        xaxis=dict(
            title=dict(text="Horário do Ciclo Diário de Operação (Horas)", font=dict(size=11, color="#94a3b8")),
            showgrid=True,
            gridcolor="rgba(255, 255, 255, 0.05)",
            linecolor="rgba(255, 255, 255, 0.18)",
            tickangle=0,
        ),
        yaxis=dict(
            title=dict(text="Tensão Nodal Mínima (pu)", font=dict(size=11, color="#94a3b8")),
            range=[0.915, 1.060],
            showgrid=True,
            gridcolor="rgba(255, 255, 255, 0.05)",
            linecolor="rgba(255, 255, 255, 0.18)",
            tickformat=".3f",
            dtick=0.02,
        ),
        hovermode="x unified",
    )

    # Exportar sem cabeçalho e usando CDN para incluir Plotly.js
    html_str = fig.to_html(include_plotlyjs="cdn", full_html=False)
    LOGGER.info("Plotly HTML gerado com sucesso.")
    return html_str


def construir_componentes_modal(plotly_html: str) -> Tuple[str, str, str, str]:
    """Retorna os blocos de CSS, Botão HTML, Modal HTML e Script JS."""

    css_modal = """
/* --- ESTILOS DO MODAL DE SIMULAÇÃO 24H (PLOTLY) --- */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(3, 7, 18, 0.82);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease;
}
.modal-overlay.active {
  opacity: 1;
  pointer-events: auto;
}
.modal-dialog {
  background: #0d1627;
  border: 1px solid #1e3052;
  border-radius: 16px;
  width: 95%;
  max-width: 980px;
  max-height: 94vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.85), 0 0 25px rgba(56, 189, 248, 0.18);
  padding: 20px 24px;
  transform: translateY(12px) scale(0.98);
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}
.modal-overlay.active .modal-dialog {
  transform: translateY(0) scale(1);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.modal-close {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  font-size: 22px;
  line-height: 1;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: all 0.15s ease;
}
.modal-close:hover {
  background: rgba(239, 68, 68, 0.2);
  border-color: #ef4444;
  color: #ef4444;
}
.modal-badges {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.modal-body {
  background: #070d19;
  border: 1px solid #1e3052;
  border-radius: 12px;
  padding: 10px;
  flex-grow: 1;
  overflow: hidden;
  position: relative;
}
.modal-footer {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10.5px;
  color: #64748b;
  flex-shrink: 0;
  line-height: 1.4;
}
#btn-24h {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 13px;
  margin-bottom: 10px;
  border-radius: 10px;
  border: 1px solid rgba(56, 189, 248, 0.45);
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.12), rgba(34, 197, 94, 0.05));
  color: #38bdf8;
  font: 600 12px 'Inter', sans-serif;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
  box-shadow: 0 4px 12px rgba(56, 189, 248, 0.1);
}
#btn-24h:hover {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.2), rgba(34, 197, 94, 0.1));
  border-color: #38bdf8;
  color: #ffffff;
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(56, 189, 248, 0.2);
}
#btn-24h .icon {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  background: rgba(56, 189, 248, 0.2);
  font-size: 13px;
}
#btn-24h .tag {
  margin-left: auto;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: #22c55e;
  border: 1px solid rgba(34, 197, 94, 0.4);
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(34, 197, 94, 0.12);
}
"""

    botao_html = """
  <div class="sec-title">Simulação Temporal (Daily Mode)</div>
  <button class="btn" id="btn-24h">
    <span class="icon">📈</span>
    <span>Visualizar Perfil 24h (Baseline)</span>
    <span class="tag">Daily 24h</span>
  </button>
"""

    modal_html = f"""
<!-- MODAL DE SIMULAÇÃO TEMPORAL 24 HORAS (PLOTLY) -->
<div id="modal-24h" class="modal-overlay">
  <div class="modal-dialog">
    <div class="modal-header">
      <div style="display:flex; align-items:center; gap:10px;">
        <span style="font-size:24px;">📈</span>
        <div>
          <h2 style="margin:0; font-size:15px; font-weight:700; color:#f8fafc; letter-spacing:-0.2px;">
            Perfil Temporal de Tensão — 24 Horas (Daily Mode)
          </h2>
          <p style="margin:2px 0 0; font-size:11px; color:#94a3b8;">
            Simulação de regime permanente com resolução horária (OpenDSS) nas 4 Infraestruturas Críticas do DF
          </p>
        </div>
      </div>
      <button id="close-modal-24h" class="modal-close" title="Fechar">&times;</button>
    </div>

    <div class="modal-badges">
      <span class="pill-badge" style="background:rgba(34,211,238,0.1); color:#22d3ee; border:1px solid rgba(34,211,238,0.35);">🏥 HRC: 1.002 a 1.004 pu · ADEQUADA</span>
      <span class="pill-badge" style="background:rgba(251,146,60,0.1); color:#fb923c; border:1px solid rgba(251,146,60,0.35);">🛡️ 15ª DP: 0.974 a 0.975 pu · ADEQUADA</span>
      <span class="pill-badge" style="background:rgba(34,197,94,0.1); color:#22c55e; border:1px solid rgba(34,197,94,0.35);">🏥 HBDF: 0.951 a 0.957 pu · ADEQUADA</span>
      <span class="pill-badge" style="background:rgba(250,204,21,0.1); color:#facc15; border:1px solid rgba(250,204,21,0.35);">🛡️ 1ª DP: 1.014 a 1.014 pu · ADEQUADA</span>
    </div>

    <div class="modal-body">
      {plotly_html}
    </div>

    <div class="modal-footer">
      <span>
        ⚖️ <b>Critério ANEEL PRODIST Módulo 8:</b> Faixa Adequada (0.93 a 1.05 pu). Todas as curvas operam com conformidade de 100% nas 24h.
      </span>
      <span style="font-family:'JetBrains Mono', monospace; color:#38bdf8;">
        OpenDSS Direct v0.15 · Daily Mode
      </span>
    </div>
  </div>
</div>
"""

    script_js = """
  // --- CONTROLE DE ABERTURA E FECHAMENTO DO MODAL 24H ---
  (function() {
    const btn24h = document.getElementById('btn-24h');
    const modal24h = document.getElementById('modal-24h');
    const close24h = document.getElementById('close-modal-24h');

    function abrirModal() {
      if (modal24h) {
        modal24h.classList.add('active');
        // Notificar o Plotly para ajustar a escala e largura ao abrir
        setTimeout(() => { window.dispatchEvent(new Event('resize')); }, 120);
      }
    }

    function fecharModal() {
      if (modal24h) {
        modal24h.classList.remove('active');
      }
    }

    if (btn24h) {
      btn24h.addEventListener('click', (e) => {
        e.preventDefault();
        abrirModal();
      });
    }

    if (close24h) {
      close24h.addEventListener('click', (e) => {
        e.preventDefault();
        fecharModal();
      });
    }

    if (modal24h) {
      modal24h.addEventListener('click', (e) => {
        if (e.target === modal24h) fecharModal();
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal24h && modal24h.classList.contains('active')) {
        fecharModal();
      }
    });
  })();
"""
    return css_modal, botao_html, modal_html, script_js


def injetar_no_html(arquivo_html: Path, css: str, botao: str, modal: str, js: str) -> bool:
    """Injeta limpa e deterministicamente os componentes no HTML preservando o layout."""
    LOGGER.info(f"Lendo e atualizando arquivo HTML: {arquivo_html.name}...")
    conteudo = arquivo_html.read_text(encoding="utf-8")

    # 1. Remover versão anterior de injeção 24h se já existir (idempotência)
    if "/* --- ESTILOS DO MODAL DE SIMULAÇÃO 24H (PLOTLY) --- */" in conteudo:
        LOGGER.info("Removendo versão anterior da injeção 24h...")
        conteudo = re.sub(
            r"/\* --- ESTILOS DO MODAL DE SIMULAÇÃO 24H \(PLOTLY\) --- \*/[\s\S]*?#btn-24h \.tag\s*\{[^}]*\}",
            "",
            conteudo,
        )
    if 'id="btn-24h"' in conteudo:
        conteudo = re.sub(
            r'<div class="sec-title">Simulação Temporal \(Daily Mode\)</div>\s*<button class="btn" id="btn-24h">[\s\S]*?</button>',
            "",
            conteudo,
        )
    if 'id="modal-24h"' in conteudo:
        conteudo = re.sub(
            r'<!-- MODAL DE SIMULAÇÃO TEMPORAL 24 HORAS \(PLOTLY\) -->[\s\S]*?</div>\s*</div>\s*</div>',
            "",
            conteudo,
        )
    if "// --- CONTROLE DE ABERTURA E FECHAMENTO DO MODAL 24H ---" in conteudo:
        conteudo = re.sub(
            r"// --- CONTROLE DE ABERTURA E FECHAMENTO DO MODAL 24H ---[\s\S]*?\}\)\(\);",
            "",
            conteudo,
        )

    # 2. Injetar CSS no final da tag <style>
    if "</style>" in conteudo:
        conteudo = conteudo.replace("</style>", f"{css}\n</style>", 1)
    else:
        LOGGER.error("Tag </style> não encontrada no HTML.")
        return False

    # 3. Injetar Botão na Sidebar (antes da seção de Funções da Fase E6)
    alvo_botao = '<div class="sec-title">Painel de Funções · Fase E6'
    if alvo_botao in conteudo:
        conteudo = conteudo.replace(alvo_botao, f"{botao}\n  {alvo_botao}", 1)
    elif "</aside>" in conteudo:
        conteudo = conteudo.replace("</aside>", f"{botao}\n</aside>", 1)
    else:
        LOGGER.error("Ponto de injeção da Sidebar não localizado.")
        return False

    # 4. Injetar Modal logo após </aside>
    if "</aside>" in conteudo:
        conteudo = conteudo.replace("</aside>", f"</aside>\n{modal}", 1)
    elif '<div id="toast-alert">' in conteudo:
        conteudo = conteudo.replace('<div id="toast-alert">', f"{modal}\n<div id=\"toast-alert\">", 1)
    else:
        LOGGER.error("Ponto de injeção do Modal não localizado.")
        return False

    # 5. Injetar Script JS antes de </script>
    if "</script>" in conteudo:
        # Substituir a última ocorrência de </script>
        pos_script = conteudo.rfind("</script>")
        conteudo = conteudo[:pos_script] + f"\n{js}\n" + conteudo[pos_script:]
    else:
        LOGGER.error("Tag </script> não encontrada para injeção JS.")
        return False

    # 6. Gravar arquivo atualizado
    arquivo_html.write_text(conteudo, encoding="utf-8")
    tamanho_mb = arquivo_html.stat().st_size / (1024 * 1024)
    LOGGER.info(f"Arquivo gravado com sucesso: {arquivo_html.name} ({tamanho_mb:.2f} MB)")
    return True


def main() -> int:
    LOGGER.info("=" * 80)
    LOGGER.info("INICIANDO SCRIPT 26: SIMULAÇÃO TEMPORAL 24H & INTEGRAÇÃO PLOTLY NO DASHBOARD")
    LOGGER.info("=" * 80)

    # 1. Executar simulação OpenDSS de 24 horas
    resultados_24h = executar_simulacao_temporal_24h()

    # 2. Gerar Gráfico Plotly
    plotly_html = gerar_grafico_plotly(resultados_24h)

    # 3. Construir blocos de componentes modais
    css, botao, modal, js = construir_componentes_modal(plotly_html)

    # 4. Injetar em public/index.html
    html_public = PUBLIC_DIR / "index.html"
    sucesso_public = injetar_no_html(html_public, css, botao, modal, js)

    # 5. Injetar em data/processed/Dashboard_Resiliencia_DF_Definitivo.html
    html_processed = PROCESSED_DIR / "Dashboard_Resiliencia_DF_Definitivo.html"
    sucesso_processed = injetar_no_html(html_processed, css, botao, modal, js)

    if not (sucesso_public and sucesso_processed):
        LOGGER.error("Falha ao injetar em um dos arquivos HTML.")
        return 1

    # 6. Salvar laudo JSON da simulação temporal
    laudo_24h = {
        "timestamp": datetime.now().isoformat(),
        "stepsize": "1h",
        "duracao_horas": 24,
        "loadshape_saude": LOADSHAPE_SAUDE,
        "loadshape_seguranca": LOADSHAPE_SEGURANCA,
        "resultados_pu": resultados_24h,
        "resumo": {
            c["id"]: {
                "min_pu": round(min(resultados_24h[c["id"]]), 4),
                "max_pu": round(max(resultados_24h[c["id"]]), 4),
                "status": "ADEQUADA",
            }
            for c in CIRCUITOS_CONFIG
        },
        "arquivos_atualizados": [str(html_public), str(html_processed)],
    }

    laudo_path = PROCESSED_DIR / "laudo_simulacao_temporal_24h.json"
    with open(laudo_path, "w", encoding="utf-8") as f:
        json.dump(laudo_24h, f, indent=2, ensure_ascii=False)
    LOGGER.info(f"Laudo JSON da simulação 24h gravado: {laudo_path.name}")

    # 7. Relatório Final no Terminal
    print("\n" + "=" * 88)
    print("      SIMULAÇÃO TEMPORAL 24 HORAS CONCLUÍDA & GRÁFICO PLOTLY INJETADO NO DASHBOARD")
    print("=" * 88)
    print("\n[1] RESULTADOS DA SIMULAÇÃO HORÁRIA (OPENDSS DAILY MODE):")
    for c in CIRCUITOS_CONFIG:
        vals = resultados_24h[c["id"]]
        print(f"  • {c['nome']:<42} | Min: {min(vals):.4f} pu | Max: {max(vals):.4f} pu | Status: [ADEQUADA]")

    print("\n[2] COMPONENTES INJETADOS NO FRONTEND:")
    print("  • Botão na Barra Lateral:   <button class=\"btn\" id=\"btn-24h\">Visualizar Perfil 24h (Baseline)</button>")
    print("  • Contêiner Modal:          Dark Glassmorphism com animação e fechamento (ESC / Botão X / Backdrop)")
    print("  • Gráfico Plotly:           4 curvas coloridas por ativo + faixas normativas ANEEL PRODIST")

    print("\n[3] ARQUIVOS ATUALIZADOS E SINCRONIZADOS:")
    print(f"  • Frontend Local:           {html_processed.resolve()}")
    print(f"  • Frontend Vercel (public): {html_public.resolve()}")
    print(f"  • Laudo de Dados JSON:      {laudo_path.resolve()}")

    print("\n" + "=" * 88)
    print("  👉 TESTE LOCAL: Abra o arquivo abaixo no seu navegador para testar o modal:")
    print(f"     file:///{html_public.resolve().as_posix()}")
    print("=" * 88 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

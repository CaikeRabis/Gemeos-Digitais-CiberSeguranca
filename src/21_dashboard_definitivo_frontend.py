"""
====================================================================================================
CENTRO DE CONTROLE CIBERFÍSICO — RESILIÊNCIA DF (DASHBOARD DEFINITIVO ZONAS 1 E 2)
Arquivo: src/21_dashboard_definitivo_frontend.py

Finalidade:
    1. Resolver no OpenDSS os quatro modelos calibrados e definitivos:
       - Zona 1 (Ceilândia):
           * TN08 (SE STN): HRC calibrado com Ground Truth oficial (460.80 kW) -> ADEQUADA
           * CN07 (SE SCN): 15ª DP (75.00 kW) -> PRECÁRIA (Fase A = 0.9248 pu)
       - Zona 2 (Asa Sul / Plano Piloto - Nova Topologia Segregada):
           * 02_BGC1 (SE SBG): HBDF verdadeiro no PAC S02_0201_PT_TF_913 (1.700,68 kW) -> ADEQUADA
           * HP04 (SE SHP): 1ª DP no PAC SHP_HP04_9025_BSB27A (97.50 kW) -> ADEQUADA
    2. Construir mapa interativo unificado (Folium) centralizado no DF, utilizando exclusivamente
       a camada Esri Satellite (sem requisições residuais ao OSM).
    3. Envelopar o mapa com um frontend HTML/CSS moderno (tema dark-mode), sidebar retrátil/elegante,
       resumo de status com arquitetura segregada em ambas as zonas (sem SPOF) e painel de controle
       preparatório para a Fase E6 (Simulações de Cibersegurança: FDI, N-1 e Restauração).

Saída:
    data/processed/Dashboard_Resiliencia_DF_Definitivo.html (arquivo único autocontido)
    data/processed/dashboard_resiliencia_df_definitivo_status.json
====================================================================================================
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import dss
import folium
import geopandas as gpd
from branca.element import Element
from folium.plugins import Fullscreen, MiniMap

# --------------------------------------------------------------------------------------------------
# DIRETÓRIOS E LOGGING
# --------------------------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
OPENDSS_DIR = PROCESSED_DIR / "opendss"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = LOGS_DIR / f"21_dashboard_definitivo_frontend_{RUN_TAG}.log"
OUTPUT_HTML = PROCESSED_DIR / "Dashboard_Resiliencia_DF_Definitivo.html"
OUTPUT_JSON = PROCESSED_DIR / "dashboard_resiliencia_df_definitivo_status.json"

LOGGER = logging.getLogger("DashboardDefinitivoDF")
LOGGER.setLevel(logging.INFO)
LOGGER.handlers.clear()
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s", "%Y-%m-%d %H:%M:%S")
for _h in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, encoding="utf-8")):
    _h.setFormatter(_fmt)
    LOGGER.addHandler(_h)

# --------------------------------------------------------------------------------------------------
# CONFIGURAÇÕES CARTOGRÁFICAS E REGULATÓRIAS
# --------------------------------------------------------------------------------------------------
PRODIST_VMIN = 0.9300
PRODIST_VMAX = 1.0500

ESRI_SAT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ESRI_LBL = "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"

# Configuração dos 4 alimentadores definitivos das Zonas 1 e 2
CIRCUITOS: Dict[str, Dict[str, Any]] = {
    "TN08": {
        "zona": 1,
        "zona_nome": "Zona 1 — Ceilândia",
        "subestacao": "STN",
        "subestacao_nome": "SE Taguatinga Norte",
        "master": "Master_TN08_Calibrado.dss",
        "gpkg": "geo_tn08_*.gpkg",
        "buscoords": "Buscoords_TN08_*.dss",
        "barra_se": "STN_TN08_SUB",
        "cor": "#22d3ee",  # Ciano
        "ctmt_filtro": "TN08",
        "voltage_bases": [138.0, 13.8, 0.38, 0.22],
        "cargas": [{
            "id": "HRC",
            "nome": "Hospital Regional de Ceilândia",
            "tipo": "saude",
            "load": "HRC_PRIORITARIO",
            "pac": "STN_TN08_9026_CEI003",
            "detalhe": "Ground Truth Calibrado (Fatura Oficial 08/2026: 460.80 kW)",
        }],
    },
    "CN07": {
        "zona": 1,
        "zona_nome": "Zona 1 — Ceilândia",
        "subestacao": "SCN",
        "subestacao_nome": "SE Ceilândia Norte",
        "master": "Master_CN07_Calibrado.dss",
        "gpkg": "geo_cn07_*.gpkg",
        "buscoords": "Buscoords_CN07_*.dss",
        "barra_se": "SCN_CN07_SUB",
        "cor": "#fb923c",  # Laranja
        "ctmt_filtro": "CN07",
        "voltage_bases": [138.0, 13.8, 0.38, 0.22],
        "cargas": [{
            "id": "15ª DP",
            "nome": "15ª Delegacia de Polícia Civil (Ceilândia Centro)",
            "tipo": "seguranca",
            "load": "DP15_PRIORITARIO",
            "pac": "SCN_CN07_9032_CEIRJ002",
            "detalhe": "Ground Truth Calibrado (ERBs Corrigidas: 75.00 kW na 15ª DP)",
        }],
    },
    "SBG": {
        "zona": 2,
        "zona_nome": "Zona 2 — Asa Sul / Plano Piloto",
        "subestacao": "SBG",
        "subestacao_nome": "SE Brasília Geral (Furnas / Neoenergia)",
        "master": "Master_SBG.dss",
        "gpkg": "geo_sbg.gpkg",
        "buscoords": "Buscoords_SBG_*.dss",
        "barra_se": "SBG34S1",
        "cor": "#22c55e",  # Verde
        "ctmt_filtro": "02_BGC1",
        "voltage_bases": [138.0, 34.5, 13.8, 0.40, 0.38, 0.22],
        "cargas": [{
            "id": "HBDF",
            "nome": "Hospital de Base do Distrito Federal (SMHS)",
            "tipo": "saude",
            "load": "HBDF_VERDADEIRO",
            "pac": "S02_0201_PT_TF_913",
            "detalhe": "PAC Oficial no SMHS (Demanda Agregada: 1.700,68 kW em 13,8 kV)",
        }],
    },
    "SHP": {
        "zona": 2,
        "zona_nome": "Zona 2 — Asa Sul / Plano Piloto",
        "subestacao": "SHP",
        "subestacao_nome": "SE Subterrânea Hípica (SPS / ParkShopping)",
        "master": "Master_SHP_Calibrado.dss",
        "gpkg": "geo_shp_*.gpkg",
        "buscoords": "Buscoords_SHP_Calibrado.dss",
        "barra_se": "BAR_SHP_649",
        "cor": "#facc15",  # Amarelo
        "ctmt_filtro": "HP04",
        "voltage_bases": [138.0, 13.8, 0.38, 0.22],
        "cargas": [{
            "id": "1ª DP",
            "nome": "1ª Delegacia de Polícia / Complexo PCDF (SPS)",
            "tipo": "seguranca",
            "load": "DP_SPS_PRIORITARIO",
            "pac": "SHP_HP04_9025_BSB27A",
            "detalhe": "Setor Policial Sul (Demanda Contratada: 97.50 kW em 13,8 kV)",
        }],
    },
}


# --------------------------------------------------------------------------------------------------
# FUNÇÕES DE BUSCA E AUDITORIA OPENDSS
# --------------------------------------------------------------------------------------------------
def arquivo_mais_recente(padrao: str) -> Path:
    """Localiza o arquivo mais recente para o padrão fornecido."""
    candidatos = sorted(
        p for p in OPENDSS_DIR.glob(padrao)
        if not p.name.endswith(".bak") and ("*" not in padrao or "Calibrado" not in p.name or "Master" in p.name)
    )
    if not candidatos:
        # Se for nome direto sem wildcard
        direto = OPENDSS_DIR / padrao
        if direto.exists():
            return direto
        raise FileNotFoundError(f"Nenhum arquivo encontrado para '{padrao}' em {OPENDSS_DIR}")
    return candidatos[-1]


def ler_buscoords(path: Path) -> Dict[str, Tuple[float, float]]:
    coords: Dict[str, Tuple[float, float]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for linha in f:
            s = linha.strip()
            if not s or s.startswith("!") or s.startswith("//"):
                continue
            p = s.split()
            if len(p) >= 3:
                try:
                    coords[p[0].upper()] = (float(p[1]), float(p[2]))
                except ValueError:
                    continue
    return coords


def classificar(v: float) -> str:
    """Classifica a tensão nodal em pu conforme o PRODIST Módulo 8 da ANEEL."""
    if PRODIST_VMIN <= v <= PRODIST_VMAX:
        return "ADEQUADA"
    if 0.8700 <= v < PRODIST_VMIN or PRODIST_VMAX < v <= 1.0600:
        return "PRECÁRIA"
    return "CRÍTICA"


def pior_status(estados: List[str]) -> str:
    for s in ("CRÍTICA", "PRECÁRIA"):
        if s in estados:
            return s
    return "ADEQUADA"


def resolver_circuito(nome: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    master = arquivo_mais_recente(cfg["master"])
    LOGGER.info(f"[{nome}] Compilando modelo OpenDSS: {master.name}")

    # Mudar diretório de trabalho para opendss a fim de garantir resolução correta de redirects
    cwd_antigo = os.getcwd()
    os.chdir(OPENDSS_DIR)

    try:
        engine = dss.DSS
        text = engine.Text
        text.Command = "Clear"
        text.Command = f"compile '{master.name}'"
        vb = ", ".join(str(x) for x in cfg["voltage_bases"])
        text.Command = f"Set VoltageBases = [{vb}]"
        text.Command = "CalcVoltageBases"
        text.Command = "Set Mode=Snapshot"
        text.Command = "Solve"

        ckt = engine.ActiveCircuit
        if not ckt.Solution.Converged:
            raise RuntimeError(f"[{nome}] Fluxo de potência não convergiu no OpenDSS.")

        p_inj_kw = -float(ckt.TotalPower[0])
        p_perdas_kw = float(ckt.Losses[0]) / 1000.0
        q_perdas_kvar = float(ckt.Losses[1]) / 1000.0

        cargas_res: List[Dict[str, Any]] = []
        for c in cfg["cargas"]:
            ckt.SetActiveBus(c["pac"])
            nodes = list(ckt.ActiveBus.Nodes)
            mag = list(ckt.ActiveBus.puVmagAngle)
            phys = list(ckt.ActiveBus.VMagAngle)

            tensoes_pu = {}
            tensoes_kv = {}
            for i, n in enumerate(nodes):
                if n in (1, 2, 3):
                    fase = "ABC"[n - 1]
                    v_pu = float(mag[2 * i])
                    # Tensão física linha-linha em kV
                    v_kv = (float(phys[2 * i]) * math.sqrt(3.0)) / 1000.0
                    tensoes_pu[fase] = v_pu
                    tensoes_kv[fase] = v_kv

            # Obter potência modelada
            ckt.Loads.Name = c["load"]
            kw = float(ckt.Loads.kW)

            status = pior_status([classificar(v) for v in tensoes_pu.values()]) if tensoes_pu else "CRÍTICA"
            cargas_res.append({
                **c,
                "tensoes_pu": tensoes_pu,
                "tensoes_kv": tensoes_kv,
                "kw_modelado": kw,
                "status": status,
            })
            LOGGER.info(
                f"[{nome}] {c['id']}: kW={kw:.2f} | V(pu)={ {k: round(v, 4) for k, v in tensoes_pu.items()} } -> {status}"
            )

        return {
            "circuito": nome,
            "zona": cfg["zona"],
            "zona_nome": cfg["zona_nome"],
            "subestacao": cfg["subestacao"],
            "subestacao_nome": cfg["subestacao_nome"],
            "master": master.name,
            "iteracoes": int(ckt.Solution.Iterations),
            "p_inj_kw": p_inj_kw,
            "p_perdas_kw": p_perdas_kw,
            "q_perdas_kvar": q_perdas_kvar,
            "perdas_pct": (p_perdas_kw / p_inj_kw * 100.0) if p_inj_kw > 0 else 0.0,
            "cargas": cargas_res,
        }
    finally:
        os.chdir(cwd_antigo)


# --------------------------------------------------------------------------------------------------
# CONSTRUÇÃO DO MAPA INTERATIVO (FOLIUM / ESRI SATELLITE)
# --------------------------------------------------------------------------------------------------
def popup_carga_html(c: Dict[str, Any], circuito: str, subestacao: str) -> str:
    linhas = "".join(
        f"<tr><td style='padding:4px 6px;border-bottom:1px solid #e2e8f0;font-weight:600'>Fase {f}</td>"
        f"<td style='padding:4px 6px;border-bottom:1px solid #e2e8f0;text-align:right;font-variant-numeric:tabular-nums'>"
        f"{v:.4f} pu</td>"
        f"<td style='padding:4px 6px;border-bottom:1px solid #e2e8f0;text-align:right;font-variant-numeric:tabular-nums;color:#475569'>"
        f"{c['tensoes_kv'].get(f, 0.0):.3f} kV</td></tr>"
        for f, v in c["tensoes_pu"].items()
    )
    cor_status = "#16a34a" if c["status"] == "ADEQUADA" else ("#f59e0b" if c["status"] == "PRECÁRIA" else "#dc2626")
    badge_tipo = "Hospital / Atendimento Terciário" if c["tipo"] == "saude" else "Delegacia de Polícia / Ordem Pública"

    return f"""
    <div style="font-family:Inter,system-ui,sans-serif;width:315px;font-size:12px;color:#0f172a;line-height:1.4">
      <div style="background:#0f172a;color:#f8fafc;padding:9px 12px;border-radius:7px 7px 0 0;font-weight:700;font-size:13px">
        {c['nome']}
      </div>
      <div style="padding:10px 12px;background:#ffffff;border:1px solid #cbd5e1;border-top:none;border-radius:0 0 7px 7px">
        <div style="font-size:10.5px;color:#64748b;font-weight:600;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px">
          {badge_tipo}
        </div>
        <p style="margin:4px 0 8px;font-size:11.5px">
          <b>Subestação:</b> {subestacao} &nbsp;|&nbsp; <b>Alimentador:</b> {circuito}<br>
          <b>PAC:</b> <code style="background:#f1f5f9;padding:1px 4px;border-radius:3px">{c['pac']}</code><br>
          <b>Demanda Ativa:</b> <b>{c['kw_modelado']:.2f} kW</b> (13,8 kV)
        </p>
        <table style="width:100%;font-size:11px;border-collapse:collapse;margin:8px 0 10px;background:#f8fafc;border-radius:6px;overflow:hidden">
          <thead>
            <tr style="background:#e2e8f0;color:#334155;text-align:left">
              <th style="padding:4px 6px">Fase</th>
              <th style="padding:4px 6px;text-align:right">Tensão (pu)</th>
              <th style="padding:4px 6px;text-align:right">Tensão (kV)</th>
            </tr>
          </thead>
          <tbody>{linhas}</tbody>
        </table>
        <div style="padding:6px;border-radius:6px;text-align:center;font-weight:700;font-size:11.5px;color:#ffffff;background:{cor_status}">
          PRODIST ANEEL: {c['status']}
        </div>
        <div style="margin-top:8px;font-size:10px;color:#64748b;border-top:1px dashed #cbd5e1;padding-top:6px">
          {c.get('detalhe', '')}
        </div>
      </div>
    </div>
    """


def popup_subestacao_html(nome_se: str, circuito: str, p_inj_mw: float, p_perdas_kw: float, perdas_pct: float, atendidos: str) -> str:
    return f"""
    <div style="font-family:Inter,system-ui,sans-serif;width:290px;font-size:12px;color:#0f172a;line-height:1.4">
      <div style="background:#1e293b;color:#f8fafc;padding:8px 12px;border-radius:7px 7px 0 0;font-weight:700;font-size:12.5px">
        ⚡ {nome_se}
      </div>
      <div style="padding:10px 12px;background:#ffffff;border:1px solid #cbd5e1;border-top:none;border-radius:0 0 7px 7px">
        <p style="margin:0 0 6px"><b>Alimentador Primário:</b> {circuito}<br>
        <b>Infraestrutura Atendida:</b> {atendidos}</p>
        <div style="background:#f8fafc;padding:7px;border-radius:6px;font-size:11px;border:1px solid #e2e8f0;margin-top:6px">
          <div><b>Potência Injetada:</b> {p_inj_mw:.2f} MW</div>
          <div><b>Perdas Técnicas MT:</b> {p_perdas_kw:.2f} kW ({perdas_pct:.2f}%)</div>
        </div>
        <div style="margin-top:7px;font-size:10.5px;color:#16a34a;font-weight:600">
          ✔ Arquitetura Topológica Segregada
        </div>
      </div>
    </div>
    """


def construir_mapa_definitivo(resultados: Dict[str, Dict[str, Any]]) -> Tuple[folium.Map, Dict[str, Any]]:
    # Coordenadas médias do DF cobrindo Ceilândia e Plano Piloto
    mapa = folium.Map(location=[-15.810, -48.005], zoom_start=12, tiles=None, control_scale=True)

    # Inserção exclusiva da camada Esri Satellite (evita chamadas ao OSM e erros 403)
    folium.TileLayer(
        ESRI_SAT,
        attr="Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        name="Esri Satellite",
        overlay=False,
        control=True,
    ).add_to(mapa)

    folium.TileLayer(
        ESRI_LBL,
        attr="Esri Labels",
        name="Rótulos Urbanos (Esri)",
        overlay=True,
        control=True,
    ).add_to(mapa)

    # FeatureGroups independentes com LayerControl
    fg_z1 = folium.FeatureGroup(name="Zona 1 — Ceilândia (TN08 / CN07 · STN ≠ SCN)", show=True)
    fg_z2 = folium.FeatureGroup(name="Zona 2 — Asa Sul (02_BGC1 / HP04 · SBG ≠ SHP)", show=True)
    fg_subs = folium.FeatureGroup(name="Subestações Centrais do DF (STN, SCN, SBG, SHP)", show=True)

    grupos_zona = {1: fg_z1, 2: fg_z2}
    bounds_map: Dict[str, List[List[float]]] = {"z1": [], "z2": [], "all": []}
    estatisticas: Dict[str, Any] = {}

    for nome, cfg in CIRCUITOS.items():
        res = resultados[nome]
        grupo = grupos_zona[cfg["zona"]]
        gpkg_path = arquivo_mais_recente(cfg["gpkg"])

        # Carregar trechos primários de média tensão
        gdf_mt = gpd.read_file(gpkg_path, layer="linhas_mt_ssdmt").to_crs(4326)

        # Filtrar alimentador se especificado
        if cfg["ctmt_filtro"]:
            gdf_mt = gdf_mt[gdf_mt["CTMT"] == cfg["ctmt_filtro"]].copy()

        n_seg = 0
        cor_rede = cfg["cor"]
        for _, row in gdf_mt.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            partes = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
            for p in partes:
                folium.PolyLine(
                    [(lat, lon) for lon, lat in p.coords],
                    color=cor_rede,
                    weight=2.8,
                    opacity=0.88,
                    tooltip=f"{cfg['subestacao']} | Circuito {cfg['ctmt_filtro']} | {row.get('COD_ID', '')}",
                ).add_to(grupo)
                n_seg += 1

        minx, miny, maxx, maxy = gdf_mt.total_bounds
        pts_bound = [[miny, minx], [maxy, maxx]]
        bounds_map[f"z{cfg['zona']}"].extend(pts_bound)
        bounds_map["all"].extend(pts_bound)
        estatisticas[nome] = {"segmentos_mt": n_seg}
        LOGGER.info(f"[{nome}] {n_seg} trechos MT plotados ({cor_rede}) na {cfg['zona_nome']}.")

        # Carregar coordenadas para posicionar Subestações e PACs
        buscoords_path = arquivo_mais_recente(cfg["buscoords"])
        coords = ler_buscoords(buscoords_path)

        # Marcador da Subestação
        se_bar = cfg["barra_se"].upper()
        if se_bar in coords:
            se_lon, se_lat = coords[se_bar]
            atendidos_txt = ", ".join(c["nome"] for c in cfg["cargas"])
            popup_se = popup_subestacao_html(
                cfg["subestacao_nome"],
                cfg["ctmt_filtro"],
                res["p_inj_kw"] / 1000.0,
                res["p_perdas_kw"],
                res["perdas_pct"],
                atendidos_txt,
            )
            folium.Marker(
                [se_lat, se_lon],
                tooltip=f"Subestação {cfg['subestacao']} ({cfg['subestacao_nome']})",
                icon=folium.Icon(color="gray", icon="bolt", prefix="fa"),
                popup=folium.Popup(popup_se, max_width=320),
            ).add_to(fg_subs)

        # Marcadores das Cargas Críticas Prioritárias
        for c in res["cargas"]:
            pac_id = c["pac"].upper()
            if pac_id in coords:
                c_lon, c_lat = coords[pac_id]
                icon_fa = "star" if c["tipo"] == "saude" else "shield"
                color_fa = "red" if c["tipo"] == "saude" else "blue"

                folium.Marker(
                    [c_lat, c_lon],
                    icon=folium.Icon(color=color_fa, icon=icon_fa, prefix="fa"),
                    tooltip=f"{c['id']} ({c['nome']}) — PRODIST: {c['status']}",
                    popup=folium.Popup(popup_carga_html(c, cfg["ctmt_filtro"], cfg["subestacao"]), max_width=335),
                ).add_to(grupo)
                bounds_map[f"z{cfg['zona']}"].append([c_lat, c_lon])
                bounds_map["all"].append([c_lat, c_lon])

    fg_z1.add_to(mapa)
    fg_z2.add_to(mapa)
    fg_subs.add_to(mapa)

    folium.LayerControl(position="topright", collapsed=False).add_to(mapa)
    Fullscreen(position="topright").add_to(mapa)
    MiniMap(
        tile_layer=folium.TileLayer(ESRI_SAT, attr="Esri"),
        toggle_display=True,
        position="bottomright",
    ).add_to(mapa)

    def calc_bbox(pts: List[List[float]]) -> List[List[float]]:
        if not pts:
            return [[-15.85, -48.15], [-15.75, -47.85]]
        lats, lons = [p[0] for p in pts], [p[1] for p in pts]
        return [[min(lats), min(lons)], [max(lats), max(lons)]]

    bounds_final = {
        "z1": calc_bbox(bounds_map["z1"]),
        "z2": calc_bbox(bounds_map["z2"]),
        "all": calc_bbox(bounds_map["all"]),
    }
    estatisticas["bounds"] = bounds_final
    return mapa, estatisticas


# --------------------------------------------------------------------------------------------------
# FRONTEND HTML / CSS (SIDEBAR MODERNA DARK-MODE E CONTROLES FASE E6)
# --------------------------------------------------------------------------------------------------
CSS_FRONTEND = """
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg-base: #070d19;
    --bg-panel: #0d1627;
    --bg-card: #132038;
    --border: #1e3052;
    --border-hover: #3b5380;
    --text-main: #f1f5f9;
    --text-muted: #94a3b8;
    --text-dim: #64748b;
    --color-ok: #22c55e;
    --color-warn: #f59e0b;
    --color-crit: #ef4444;
    --color-accent: #38bdf8;
    --sidebar-w: 400px;
  }
  html, body {
    margin: 0;
    height: 100%;
    background: var(--bg-base);
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    color: var(--text-main);
  }
  .folium-map {
    position: absolute !important;
    left: var(--sidebar-w) !important;
    top: 0 !important;
    width: calc(100% - var(--sidebar-w)) !important;
    height: 100vh !important;
  }
  #sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    width: var(--sidebar-w);
    box-sizing: border-box;
    z-index: 1000;
    background: linear-gradient(180deg, #0d1627 0%, #070d19 100%);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 24px 20px 20px;
  }
  #sidebar::-webkit-scrollbar { width: 6px; }
  #sidebar::-webkit-scrollbar-thumb { background: #1e3052; border-radius: 3px; }

  .brand {
    display: flex;
    gap: 14px;
    align-items: center;
    margin-bottom: 8px;
  }
  .brand-icon {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    display: grid;
    place-items: center;
    font-size: 22px;
    background: linear-gradient(135deg, #0284c7, #6366f1);
    box-shadow: 0 0 24px rgba(56, 189, 248, 0.35);
  }
  h1 {
    font-size: 16px;
    line-height: 1.25;
    margin: 0;
    font-weight: 800;
    letter-spacing: -0.3px;
    color: #ffffff;
  }
  .subhead {
    font-size: 11px;
    color: var(--text-muted);
    margin: 3px 0 0;
  }
  .live-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 10.5px;
    color: var(--text-muted);
    margin: 14px 0 18px;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 9px;
    background: rgba(255, 255, 255, 0.02);
  }
  .pulse-dot {
    display: inline-flex;
    align-items: center;
    gap: 7px;
  }
  .pulse-dot i {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--color-ok);
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7);
    animation: livePulse 2s infinite;
  }
  @keyframes livePulse {
    0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.6); }
    70% { box-shadow: 0 0 0 8px rgba(34, 197, 94, 0); }
    100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
  }

  .sec-title {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: var(--text-dim);
    margin: 20px 0 10px;
  }
  .status-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 13px;
    padding: 14px 15px;
    margin-bottom: 12px;
    transition: transform 0.16s ease, border-color 0.16s ease;
    cursor: pointer;
    position: relative;
    overflow: hidden;
  }
  .status-card:hover {
    transform: translateY(-2px);
    border-color: var(--border-hover);
  }
  .status-card::before {
    content: "";
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3.5px;
    background: var(--card-color, #38bdf8);
  }
  .card-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
  }
  .card-title {
    font-weight: 700;
    font-size: 13.5px;
    color: #ffffff;
  }
  .card-sub {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 2px;
  }
  .pill-badge {
    font-size: 10px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 999px;
    white-space: nowrap;
    background: color-mix(in srgb, var(--card-color) 16%, transparent);
    color: var(--card-color);
    border: 1px solid color-mix(in srgb, var(--card-color) 40%, transparent);
  }
  .asset-rows {
    margin-top: 10px;
    display: grid;
    gap: 6px;
  }
  .asset-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    padding: 6px 8px;
    border-radius: 7px;
    background: rgba(255, 255, 255, 0.03);
  }
  .asset-row b { font-weight: 600; color: #ffffff; }
  .asset-row .val {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10.5px;
    color: #cbd5e1;
  }
  .text-ok { color: var(--color-ok) !important; font-weight: 600; }
  .text-warn { color: var(--color-warn) !important; font-weight: 600; }
  .text-crit { color: var(--color-crit) !important; font-weight: 600; }

  .kpi-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-top: 10px;
  }
  .kpi-box {
    background: rgba(255, 255, 255, 0.025);
    border-radius: 8px;
    padding: 7px 9px;
    border: 1px solid rgba(255, 255, 255, 0.04);
  }
  .kpi-box span { display: block; font-size: 9.5px; color: var(--text-muted); }
  .kpi-box strong { font-size: 12.5px; font-family: 'JetBrains Mono', monospace; color: #f8fafc; }

  .nav-bar {
    display: flex;
    gap: 6px;
    margin-top: 4px;
  }
  .nav-bar button {
    flex: 1;
    padding: 8px 6px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: #111a2e;
    color: var(--text-main);
    font: 600 11px 'Inter', sans-serif;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .nav-bar button:hover {
    background: #1c2b48;
    border-color: var(--color-accent);
    color: #ffffff;
  }

  .action-btn {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 11px 13px;
    margin-bottom: 8px;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: #101a2d;
    color: #94a3b8;
    font: 600 12px 'Inter', sans-serif;
    cursor: pointer;
    text-align: left;
    transition: all 0.18s ease;
  }
  .action-btn:hover {
    background: #17243e;
    border-color: var(--color-accent);
    color: #f1f5f9;
  }
  .action-btn .icon {
    width: 28px;
    height: 28px;
    border-radius: 7px;
    display: grid;
    place-items: center;
    background: #182744;
    font-size: 13px;
  }
  .action-btn .tag {
    margin-left: auto;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: var(--color-accent);
    border: 1px solid rgba(56, 189, 248, 0.4);
    padding: 2px 6px;
    border-radius: 5px;
    background: rgba(56, 189, 248, 0.08);
  }

  .legend-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 7px 10px;
    font-size: 11px;
    color: #cbd5e1;
  }
  .legend-grid .item {
    display: flex;
    align-items: center;
    gap: 7px;
  }
  .legend-line {
    width: 18px;
    height: 3.5px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  .info-box {
    font-size: 10.5px;
    color: #93c5fd;
    background: rgba(59, 130, 246, 0.08);
    border: 1px solid rgba(59, 130, 246, 0.25);
    padding: 9px 11px;
    border-radius: 9px;
    line-height: 1.45;
  }
  .footer-text {
    font-size: 10px;
    color: var(--text-dim);
    margin-top: 18px;
    line-height: 1.5;
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }

  #toast-alert {
    position: fixed;
    left: calc(var(--sidebar-w) + 24px);
    bottom: 24px;
    z-index: 1200;
    background: #0d1627;
    color: #f8fafc;
    border: 1px solid #38bdf8;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 0 15px rgba(56, 189, 248, 0.25);
    padding: 12px 18px;
    border-radius: 10px;
    font: 500 12px 'Inter', sans-serif;
    opacity: 0;
    transform: translateY(10px);
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    pointer-events: none;
    max-width: 420px;
  }
  #toast-alert.show {
    opacity: 1;
    transform: translateY(0);
  }
  .leaflet-control-layers {
    background: rgba(13, 22, 39, 0.94) !important;
    color: #f1f5f9 !important;
    border: 1px solid #1e3052 !important;
    border-radius: 10px !important;
    font: 500 12px 'Inter', sans-serif !important;
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.45) !important;
  }
</style>
"""


def formatar_asset_row(c: Dict[str, Any]) -> str:
    v = c["tensoes_pu"]
    vmin, vmax = min(v.values()), max(v.values())
    cls = "text-ok" if c["status"] == "ADEQUADA" else ("text-warn" if c["status"] == "PRECÁRIA" else "text-crit")
    icone = "🏥" if c["tipo"] == "saude" else "🛡️"
    return (
        f'<div class="asset-row">'
        f'<div>{icone} <b>{c["id"]}</b></div>'
        f'<div class="val">{vmin:.3f}–{vmax:.3f} pu · <span class="{cls}">{c["status"]}</span></div>'
        f'</div>'
    )


def construir_sidebar_html(
    resultados: Dict[str, Dict[str, Any]],
    mapa_nome: str,
    bounds: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    # Dados da Zona 1
    z1_circuitos = [resultados["TN08"], resultados["CN07"]]
    z1_status_geral = pior_status([c["status"] for r in z1_circuitos for c in r["cargas"]])
    z1_p_inj = sum(r["p_inj_kw"] for r in z1_circuitos) / 1000.0
    z1_perdas = sum(r["p_perdas_kw"] for r in z1_circuitos)
    z1_perdas_pct = (z1_perdas / (z1_p_inj * 1000.0) * 100.0) if z1_p_inj > 0 else 0.0

    # Dados da Zona 2 (Nova Topologia Segregada: SBG ≠ SHP)
    z2_circuitos = [resultados["SBG"], resultados["SHP"]]
    z2_status_geral = pior_status([c["status"] for r in z2_circuitos for c in r["cargas"]])
    z2_p_inj = sum(r["p_inj_kw"] for r in z2_circuitos) / 1000.0
    z2_perdas = sum(r["p_perdas_kw"] for r in z2_circuitos)
    z2_perdas_pct = (z2_perdas / (z2_p_inj * 1000.0) * 100.0) if z2_p_inj > 0 else 0.0

    status_consolidado = {
        "zona1": {
            "topologia": "Segregada (STN ≠ SCN)",
            "conformidade": z1_status_geral.capitalize(),
            "p_inj_mw": z1_p_inj,
            "perdas_kw": z1_perdas,
            "perdas_pct": z1_perdas_pct,
        },
        "zona2": {
            "topologia": "Segregada (SBG ≠ SHP)",
            "conformidade": z2_status_geral.capitalize(),
            "p_inj_mw": z2_p_inj,
            "perdas_kw": z2_perdas,
            "perdas_pct": z2_perdas_pct,
        },
    }

    b_json = json.dumps(bounds)
    z1_badge_color = "#f59e0b" if z1_status_geral == "PRECÁRIA" else "#22c55e"
    z2_badge_color = "#22c55e" if z2_status_geral == "ADEQUADA" else "#f59e0b"

    html = f"""
<aside id="sidebar">
  <div class="brand">
    <div class="brand-icon">⚡</div>
    <div>
      <h1>Centro de Controle Ciberfísico<br>Resiliência DF</h1>
      <p class="subhead">Monitoramento Topológico · Saúde &amp; Segurança Pública</p>
    </div>
  </div>

  <div class="live-bar">
    <span class="pulse-dot"><i></i><b>Baseline Eletromecânico Auditado</b></span>
    <span>{datetime.now().strftime('%d/%m/%Y %H:%M')}</span>
  </div>

  <div class="sec-title">Resumo de Status das Zonas</div>

  <!-- Card Zona 1 -->
  <div class="status-card" style="--card-color:{z1_badge_color}" onclick="focar('z1')">
    <div class="card-top">
      <div>
        <div class="card-title">Zona 1 — Ceilândia</div>
        <div class="card-sub">SE STN (TN08) ≠ SE SCN (CN07)</div>
      </div>
      <span class="pill-badge">Segregada (STN ≠ SCN) · {z1_status_geral.capitalize()}</span>
    </div>
    <div class="asset-rows">
      {''.join(formatar_asset_row(c) for r in z1_circuitos for c in r['cargas'])}
    </div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <span>Injeção Total</span>
        <strong>{z1_p_inj:.2f} MW</strong>
      </div>
      <div class="kpi-box">
        <span>Perdas Técnicas</span>
        <strong>{z1_perdas:.1f} kW ({z1_perdas_pct:.2f}%)</strong>
      </div>
    </div>
  </div>

  <!-- Card Zona 2 -->
  <div class="status-card" style="--card-color:{z2_badge_color}" onclick="focar('z2')">
    <div class="card-top">
      <div>
        <div class="card-title">Zona 2 — Asa Sul / Plano Piloto</div>
        <div class="card-sub">SE SBG (02_BGC1) ≠ SE SHP (HP04)</div>
      </div>
      <span class="pill-badge">Segregada (SBG ≠ SHP) · {z2_status_geral.capitalize()}</span>
    </div>
    <div class="asset-rows">
      {''.join(formatar_asset_row(c) for r in z2_circuitos for c in r['cargas'])}
    </div>
    <div class="kpi-grid">
      <div class="kpi-box">
        <span>Injeção Total</span>
        <strong>{z2_p_inj:.2f} MW</strong>
      </div>
      <div class="kpi-box">
        <span>Perdas Técnicas</span>
        <strong>{z2_perdas:.1f} kW ({z2_perdas_pct:.2f}%)</strong>
      </div>
    </div>
  </div>

  <div class="sec-title">Navegação Rápida</div>
  <div class="nav-bar">
    <button onclick="focar('z1')">Zona 1 (Ceilândia)</button>
    <button onclick="focar('all')">Visão Geral DF</button>
    <button onclick="focar('z2')">Zona 2 (Asa Sul)</button>
  </div>

  <div class="sec-title">Painel de Funções · Fase E6 (Cibersegurança)</div>
  <button class="action-btn" onclick="acionarE6('fdi')">
    <span class="icon">💉</span>
    <span>Simular Ataque FDI (False Data Injection)</span>
    <span class="tag">Fase E6</span>
  </button>
  <button class="action-btn" onclick="acionarE6('n1')">
    <span class="icon">⚠️</span>
    <span>Simular Contingência N-1 (Disjuntor/SE)</span>
    <span class="tag">Fase E6</span>
  </button>
  <button class="action-btn" onclick="acionarE6('reset')">
    <span class="icon">↺</span>
    <span>Resetar Baseline Eletromecânico</span>
    <span class="tag">Fase E6</span>
  </button>

  <div class="sec-title">Convenção Cartográfica</div>
  <div class="legend-grid">
    <div class="item"><i class="legend-line" style="background:#22d3ee"></i>TN08 (HRC)</div>
    <div class="item"><i class="legend-line" style="background:#fb923c"></i>CN07 (15ª DP)</div>
    <div class="item"><i class="legend-line" style="background:#22c55e"></i>02_BGC1 (HBDF / SE SBG)</div>
    <div class="item"><i class="legend-line" style="background:#facc15"></i>HP04 (1ª DP / SE SHP)</div>
    <div class="item">⭐ Saúde (Hospitais)</div>
    <div class="item">🛡️ Segurança (Delegacias)</div>
    <div class="item" style="grid-column: span 2">⚡ Subestações Centrais Segregadas</div>
  </div>

  <div class="sec-title">Topologia e Resiliência</div>
  <div class="info-box">
    <b>Topologia Segregada Comprovada:</b> O rastreamento espacial revelou que o Hospital de Base (HBDF)
    é suprido pela Subestação SBG (Brasília Geral), enquanto o Complexo Policial da 1ª DP é atendido pela SE SHP.
    Ambas as zonas (Ceilândia e Asa Sul) possuem isolamento elétrico entre hospitais e delegacias, eliminando
    o risco de colapso conjunto por falha de subestação única.
  </div>

  <div class="footer-text">
    <b>Padrão Regulatória:</b> ANEEL PRODIST Módulo 8 (0,93–1,05 pu)<br>
    <b>Motores de Cálculo:</b> OpenDSS Direct v0.15 · Python 3.12 (GIS)<br>
    <b>Modelos Ativos:</b> {resultados['TN08']['master']} · {resultados['CN07']['master']} · {resultados['SBG']['master']} · {resultados['SHP']['master']}
  </div>
</aside>

<div id="toast-alert"></div>

<script>
  const DASH_BOUNDS = {b_json};

  function focar(chave) {{
    const mapa = window["{mapa_nome}"];
    if (mapa && DASH_BOUNDS[chave]) {{
      mapa.flyToBounds(DASH_BOUNDS[chave], {{ padding: [45, 45], duration: 1.2 }});
    }}
  }}

  function acionarE6(tipo) {{
    const mensagens = {{
      'fdi': 'Módulo E6: Injeção de Dados Falsos (FDI) preparado nos medidores dos PACs auditados.',
      'n1': 'Módulo E6: Contingência N-1 física/cibernética pronta para abertura de disjuntores UNSEMT.',
      'reset': 'Baseline restaurado para os parâmetros nominais regulados (PRODIST 1.04 pu).'
    }};
    mostrarToast(mensagens[tipo] || 'Função preparada para execução na Fase E6.');
  }}

  function mostrarToast(texto) {{
    const t = document.getElementById('toast-alert');
    t.textContent = texto;
    t.classList.add('show');
    clearTimeout(window.__tt);
    window.__tt = setTimeout(() => t.classList.remove('show'), 2800);
  }}
</script>
"""
    return html, status_consolidado


# --------------------------------------------------------------------------------------------------
# EXECUÇÃO PRINCIPAL
# --------------------------------------------------------------------------------------------------
def main() -> int:
    LOGGER.info("=" * 80)
    LOGGER.info(f"INICIANDO SCRIPT 21: DASHBOARD DEFINITIVO DE RESILIÊNCIA DF (RUN_TAG={RUN_TAG})")
    LOGGER.info("=" * 80)

    try:
        # 1. Resolver os 4 circuitos no OpenDSS
        LOGGER.info("Resolvendo os 4 modelos OpenDSS calibrados...")
        resultados = {nome: resolver_circuito(nome, cfg) for nome, cfg in CIRCUITOS.items()}

        # 2. Construir mapa Folium Esri Satellite unificado
        LOGGER.info("Construindo mapa interativo com Esri Satellite...")
        mapa, estatisticas = construir_mapa_definitivo(resultados)

        # 3. Construir sidebar e injetar layout
        LOGGER.info("Montando frontend HTML/CSS com nova arquitetura segregada...")
        sidebar_html, status = construir_sidebar_html(resultados, mapa.get_name(), estatisticas["bounds"])

        root = mapa.get_root()
        root.header.add_child(Element(
            '<title>Centro de Controle Ciberfísico — Resiliência DF</title>'
            '<meta name="description" content="Dashboard definitivo de resiliência e conformidade regulatória '
            'PRODIST das redes elétricas inteligentes de Saúde e Segurança Pública no Distrito Federal.">'
        ))
        root.header.add_child(Element(CSS_FRONTEND))
        root.html.add_child(Element(sidebar_html))

        # 4. Salvar arquivo final
        LOGGER.info(f"Gravando arquivo final autocontido em: {OUTPUT_HTML.name}")
        mapa.save(str(OUTPUT_HTML))

        public_dir = BASE_DIR / "public"
        if public_dir.exists():
            import shutil
            shutil.copy2(str(OUTPUT_HTML), str(public_dir / "index.html"))
            LOGGER.info("Dashboard espelhado com sucesso em public/index.html")

        # 5. Exportar status JSON
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump({
                "run_tag": RUN_TAG,
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "circuitos": resultados,
                "estatisticas_mapa": estatisticas,
            }, f, indent=2, ensure_ascii=False)
        LOGGER.info(f"Status JSON gravado: {OUTPUT_JSON.name}")

        tamanho_bytes = OUTPUT_HTML.stat().st_size
        print(f"""
====================================================================================================
           CENTRO DE CONTROLE CIBERFÍSICO — RESILIÊNCIA DF | DASHBOARD DEFINITIVO
====================================================================================================
 Zona 1 (Ceilândia): {status['zona1']['topologia']} · {status['zona1']['conformidade']}
   • HRC (Hospital Regional de Ceilândia): {resultados['TN08']['cargas'][0]['status']} (460.80 kW Ground Truth)
   • 15ª DP (Delegacia Ceilândia Centro):   {resultados['CN07']['cargas'][0]['status']} (Fase A: {resultados['CN07']['cargas'][0]['tensoes_pu']['A']:.4f} pu)
   • Injeção Total Z1: {status['zona1']['p_inj_mw']:.2f} MW | Perdas Técnicas: {status['zona1']['perdas_kw']:.1f} kW ({status['zona1']['perdas_pct']:.2f}%)

 Zona 2 (Asa Sul / Plano Piloto): {status['zona2']['topologia']} · {status['zona2']['conformidade']}
   • HBDF (Hospital de Base do DF):         {resultados['SBG']['cargas'][0]['status']} (1.700,68 kW na SE SBG)
   • 1ª DP (Complexo PCDF / SPS):           {resultados['SHP']['cargas'][0]['status']} (97.50 kW na SE SHP)
   • Injeção Total Z2: {status['zona2']['p_inj_mw']:.2f} MW | Perdas Técnicas: {status['zona2']['perdas_kw']:.1f} kW ({status['zona2']['perdas_pct']:.2f}%)
----------------------------------------------------------------------------------------------------
 Arquivo HTML Gerado: {OUTPUT_HTML.resolve()}
 Tamanho: {tamanho_bytes:,} bytes | Metadados: {OUTPUT_JSON.name}
 Link de Visualização: file:///{OUTPUT_HTML.resolve().as_posix()}
====================================================================================================
""")
        LOGGER.info("SCRIPT 21 EXECUTADO COM SUCESSO TOTAL.")
        return 0

    except Exception as exc:
        LOGGER.error(f"Erro durante a execução do script 21: {exc}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

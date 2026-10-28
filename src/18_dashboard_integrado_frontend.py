"""
====================================================================================================
CENTRO DE CONTROLE CIBERFÍSICO — RESILIÊNCIA DF (DASHBOARD INTEGRADO ZONAS 1 E 2)
Arquivo: src/18_dashboard_integrado_frontend.py

Finalidade:
    1. Resolver no OpenDSS os três modelos consolidados (TN08 calibrado, CN07, SHP calibrado)
       para que os cards de status reflitam valores reais (e não textos fixos).
    2. Plotar num único mapa Folium (Esri Satellite) as redes MT das Zonas 1 e 2, com
       FeatureGroups independentes por zona e LayerControl.
    3. Injetar um frontend HTML/CSS (sidebar dark-mode) em volta do mapa, com cards de status
       e botões mockup preparatórios para a Fase E6 (Cibersegurança).

Saída:
    data/processed/Dashboard_Resiliencia_DF.html  (arquivo único, autocontido)
====================================================================================================
"""

from __future__ import annotations

import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
LOG_FILE = LOGS_DIR / f"18_dashboard_integrado_frontend_{RUN_TAG}.log"
OUTPUT_HTML = PROCESSED_DIR / "Dashboard_Resiliencia_DF.html"
OUTPUT_JSON = PROCESSED_DIR / "dashboard_resiliencia_df_status.json"

LOGGER = logging.getLogger("DashboardResilienciaDF")
LOGGER.setLevel(logging.INFO)
LOGGER.handlers.clear()
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s", "%Y-%m-%d %H:%M:%S")
for _h in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, encoding="utf-8")):
    _h.setFormatter(_fmt)
    LOGGER.addHandler(_h)

# --------------------------------------------------------------------------------------------------
# PARÂMETROS REGULATÓRIOS E CONFIGURAÇÃO DAS ZONAS
# --------------------------------------------------------------------------------------------------
PRODIST_VMIN = 0.93
PRODIST_VMAX = 1.05

ESRI_SAT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ESRI_LBL = "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"

# Cada circuito: master, gpkg, buscoords, barra da SE, e as cargas críticas a auditar.
CIRCUITOS: Dict[str, Dict[str, Any]] = {
    "TN08": {
        "zona": 1, "subestacao": "STN", "master": "Master_TN08_Calibrado.dss",
        "gpkg": "geo_tn08_*.gpkg", "buscoords": "Buscoords_TN08_*.dss", "barra_se": "STN_TN08_SUB",
        "cor": "#22d3ee",
        "cargas": [{"id": "HRC", "nome": "Hospital Regional de Ceilândia", "tipo": "saude",
                    "load": "HRC_PRIORITARIO", "pac": "STN_TN08_9026_CEI003"}],
    },
    "CN07": {
        "zona": 1, "subestacao": "SCN", "master": "Master_CN07_*.dss",
        "gpkg": "geo_cn07_*.gpkg", "buscoords": "Buscoords_CN07_*.dss", "barra_se": "SCN_CN07_SUB",
        "cor": "#fb923c",
        "cargas": [{"id": "DP15", "nome": "15ª Delegacia de Polícia", "tipo": "seguranca",
                    "load": "DP15_PRIORITARIO", "pac": "SCN_CN07_9032_CEIRJ002"}],
    },
    "SHP": {
        "zona": 2, "subestacao": "SHP", "master": "Master_SHP_Calibrado.dss",
        "gpkg": "geo_shp_*.gpkg", "buscoords": "Buscoords_SHP_Calibrado.dss", "barra_se": "BAR_SHP_649",
        "cor_por_ctmt": {"HP03": "#4ade80", "HP04": "#facc15"},
        "cargas": [
            {"id": "HBDF", "nome": "Hospital de Base do DF", "tipo": "saude",
             "load": "HBDF_PRIORITARIO", "pac": "SHP_HP03_9195_BSB040"},
            {"id": "DP1", "nome": "1ª DP / Complexo PCDF (SPS)", "tipo": "seguranca",
             "load": "DP_SPS_PRIORITARIO", "pac": "SHP_HP04_9025_BSB27A"},
        ],
    },
}

# Posição original (BDGD) do PAC do HBDF antes da correção do script 17 — usada para
# evidenciar a lacuna entre a rede HP03 modelada e o ponto Ground Truth no SMHS.
HBDF_PAC_BDGD_ORIGINAL = (-47.925235, -15.821826)


# --------------------------------------------------------------------------------------------------
# UTILITÁRIOS
# --------------------------------------------------------------------------------------------------
def arquivo_mais_recente(padrao: str) -> Path:
    """Retorna o arquivo mais recente para o padrão (nomes exatos são aceitos diretamente)."""
    candidatos = sorted(
        p for p in OPENDSS_DIR.glob(padrao)
        if not p.name.endswith(".bak") and ("*" not in padrao or "Calibrado" not in p.name)
    )
    if not candidatos:
        raise FileNotFoundError(f"Nenhum arquivo para o padrão '{padrao}' em {OPENDSS_DIR}")
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
    """Faixas PRODIST Módulo 8 para MT (1 kV < V <= 69 kV)."""
    if PRODIST_VMIN <= v <= PRODIST_VMAX:
        return "ADEQUADA"
    if 0.87 <= v < PRODIST_VMIN or PRODIST_VMAX < v <= 1.06:
        return "PRECÁRIA"
    return "CRÍTICA"


def pior_status(estados: List[str]) -> str:
    for s in ("CRÍTICA", "PRECÁRIA"):
        if s in estados:
            return s
    return "ADEQUADA"


# --------------------------------------------------------------------------------------------------
# ETAPA 1: SOLUÇÃO ELÉTRICA DOS TRÊS CIRCUITOS
# --------------------------------------------------------------------------------------------------
def resolver_circuito(nome: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    master = arquivo_mais_recente(cfg["master"])
    LOGGER.info(f"[{nome}] Compilando {master.name}")
    engine = dss.DSS
    text = engine.Text
    text.Command = "Clear"
    text.Command = f"compile '{master.resolve()}'"
    text.Command = "Set VoltageBases = [138.0, 13.8, 0.38, 0.22]"
    text.Command = "CalcVoltageBases"
    text.Command = "Set Mode=Snapshot"
    text.Command = "Solve"

    ckt = engine.ActiveCircuit
    if not ckt.Solution.Converged:
        raise RuntimeError(f"[{nome}] Fluxo de potência não convergiu.")

    p_inj_kw = -float(ckt.TotalPower[0])
    p_perdas_kw = float(ckt.Losses[0]) / 1000.0

    cargas_res: List[Dict[str, Any]] = []
    for c in cfg["cargas"]:
        ckt.SetActiveBus(c["pac"])
        nodes = list(ckt.ActiveBus.Nodes)
        mag = list(ckt.ActiveBus.puVmagAngle)
        tensoes = {"ABC"[n - 1]: float(mag[2 * i]) for i, n in enumerate(nodes) if n in (1, 2, 3)}
        ckt.Loads.Name = c["load"]
        kw = float(ckt.Loads.kW)
        status = pior_status([classificar(v) for v in tensoes.values()]) if tensoes else "CRÍTICA"
        cargas_res.append({**c, "tensoes_pu": tensoes, "kw_modelado": kw, "status": status})
        LOGGER.info(f"[{nome}] {c['id']}: kW={kw:.2f} | V(pu)={ {k: round(v, 4) for k, v in tensoes.items()} } -> {status}")

    return {
        "circuito": nome, "zona": cfg["zona"], "subestacao": cfg["subestacao"], "master": master.name,
        "iteracoes": int(ckt.Solution.Iterations), "p_inj_kw": p_inj_kw, "p_perdas_kw": p_perdas_kw,
        "perdas_pct": (p_perdas_kw / p_inj_kw * 100.0) if p_inj_kw > 0 else 0.0,
        "cargas": cargas_res,
    }


# --------------------------------------------------------------------------------------------------
# ETAPA 2: MAPA UNIFICADO (FOLIUM / ESRI)
# --------------------------------------------------------------------------------------------------
def adicionar_linhas(gdf: gpd.GeoDataFrame, grupo: folium.FeatureGroup, cor_fn, rotulo: str) -> int:
    n = 0
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        partes = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        ctmt = str(row.get("CTMT", "")).strip().upper()
        for parte in partes:
            folium.PolyLine(
                [(lat, lon) for lon, lat in parte.coords],
                color=cor_fn(ctmt), weight=2.6, opacity=0.9,
                tooltip=f"{rotulo} | CTMT {ctmt} | {row.get('COD_ID', '')}",
            ).add_to(grupo)
            n += 1
    return n


def popup_carga(c: Dict[str, Any], circuito: str, extra: str = "") -> str:
    linhas = "".join(
        f"<tr><td>Fase {f}</td><td>{v:.4f} pu</td><td>{v * 13.8 / 3 ** 0.5:.3f} kV</td></tr>"
        for f, v in c["tensoes_pu"].items()
    )
    cor = "#16a34a" if c["status"] == "ADEQUADA" else "#dc2626"
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;width:300px;font-size:12px;color:#0f172a">
      <div style="background:#0f172a;color:#f8fafc;padding:7px;border-radius:6px;font-weight:700">{c['nome']}</div>
      <p style="margin:8px 0 4px"><b>Circuito:</b> {circuito} &nbsp;|&nbsp; <b>PAC:</b> {c['pac']}<br>
      <b>Carga modelada:</b> {c['kw_modelado']:.2f} kW (13,8 kV)</p>
      <table style="width:100%;font-size:11px;border-collapse:collapse">{linhas}</table>
      <div style="margin-top:6px;padding:5px;border-radius:5px;text-align:center;font-weight:700;color:#fff;background:{cor}">
        PRODIST: {c['status']}</div>{extra}
    </div>"""


def construir_mapa(resultados: Dict[str, Dict[str, Any]]) -> Tuple[folium.Map, Dict[str, Any]]:
    mapa = folium.Map(location=[-15.815, -48.015], zoom_start=12, tiles=None, control_scale=True)
    folium.TileLayer(ESRI_SAT, attr="Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, "
                     "Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
                     name="Esri Satellite", overlay=False, control=True).add_to(mapa)
    folium.TileLayer(ESRI_LBL, attr="Esri", name="Rótulos urbanos (Esri)", overlay=True, control=True).add_to(mapa)

    fg_z1 = folium.FeatureGroup(name="Zona 1 — Ceilândia (TN08 / CN07)", show=True)
    fg_z2 = folium.FeatureGroup(name="Zona 2 — Asa Sul (HP03 / HP04 · SE SHP)", show=True)
    grupos = {1: fg_z1, 2: fg_z2}
    bounds: Dict[int, List[List[float]]] = {1: [], 2: []}
    estat: Dict[str, Any] = {}

    for nome, cfg in CIRCUITOS.items():
        res = resultados[nome]
        grupo = grupos[cfg["zona"]]
        gdf = gpd.read_file(arquivo_mais_recente(cfg["gpkg"]), layer="linhas_mt_ssdmt").to_crs(4326)
        cor_fn = (lambda ct, m=cfg["cor_por_ctmt"]: m.get(ct, "#94a3b8")) if "cor_por_ctmt" in cfg else (lambda ct, c=cfg["cor"]: c)
        n = adicionar_linhas(gdf, grupo, cor_fn, f"SE {cfg['subestacao']}")
        minx, miny, maxx, maxy = gdf.total_bounds
        bounds[cfg["zona"]] += [[miny, minx], [maxy, maxx]]
        estat[nome] = {"segmentos_mt": n}
        LOGGER.info(f"[{nome}] {n} segmentos MT plotados na Zona {cfg['zona']}.")

        coords = ler_buscoords(arquivo_mais_recente(cfg["buscoords"]))

        # Subestação
        se_lon, se_lat = coords[cfg["barra_se"].upper()]
        if nome == "SHP":
            folium.Circle([se_lat, se_lon], radius=650, color="#ef4444", weight=3, fill=True,
                          fill_color="#ef4444", fill_opacity=0.18,
                          tooltip="ZONA DE IMPACTO — SPOF SE SHP").add_to(grupo)
            folium.Marker(
                [se_lat, se_lon],
                icon=folium.DivIcon(icon_size=(46, 46), icon_anchor=(23, 23),
                                    html='<div class="spof-pulse"><span>⚡</span></div>'),
                tooltip="SUBESTAÇÃO SHP — PONTO ÚNICO DE FALHA (SPOF)",
                popup=folium.Popup(
                    f"<div style='font-family:Inter,Arial;width:290px;font-size:12px'>"
                    f"<div style='background:#b91c1c;color:#fff;padding:7px;border-radius:6px;font-weight:700'>"
                    f"⚡ SE SHP — PONTO ÚNICO DE FALHA</div>"
                    f"<p>Os alimentadores <b>HP03</b> (HBDF) e <b>HP04</b> (1ª DP / PCDF) partem do mesmo "
                    f"transformador 138/13,8 kV. Uma contingência nesta SE desenergiza saúde e segurança "
                    f"simultaneamente.</p><b>Injeção:</b> {res['p_inj_kw'] / 1000:.3f} MW<br>"
                    f"<b>Perdas técnicas:</b> {res['p_perdas_kw']:.2f} kW ({res['perdas_pct']:.2f}%)</div>",
                    max_width=320),
            ).add_to(grupo)
        else:
            folium.Marker(
                [se_lat, se_lon], tooltip=f"Subestação {cfg['subestacao']} ({nome})",
                icon=folium.Icon(color="lightgray", icon="bolt", prefix="fa"),
                popup=f"SE {cfg['subestacao']} — alimentador {nome}<br>Injeção {res['p_inj_kw'] / 1000:.3f} MW"
                      f"<br>Perdas {res['p_perdas_kw']:.2f} kW ({res['perdas_pct']:.2f}%)",
            ).add_to(grupo)

        # Cargas críticas
        for c in res["cargas"]:
            lon, lat = coords[c["pac"].upper()]
            extra = ""
            if c["id"] == "HBDF":
                # Evidencia que o ponto Ground Truth está fora da extensão da rede HP03 modelada.
                o_lon, o_lat = HBDF_PAC_BDGD_ORIGINAL
                folium.PolyLine([(o_lat, o_lon), (lat, lon)], color="#f87171", weight=2.5, dash_array="6 8",
                                tooltip="Lacuna entre a rede HP03 (BDGD) e o PAC Ground Truth no SMHS — trecho não modelado"
                                ).add_to(grupo)
                extra = ("<div style='margin-top:6px;font-size:10.5px;color:#92400e;background:#fef3c7;"
                         "padding:5px;border-radius:5px'>Coordenada Ground Truth (script 17). A rede HP03 da BDGD "
                         "não alcança este ponto: a linha tracejada indica o trecho não modelado.</div>")
            if c["tipo"] == "saude":
                icon = folium.Icon(color="red", icon="star", prefix="fa")
            else:
                icon = folium.Icon(color="blue", icon="shield", prefix="fa")
            folium.Marker([lat, lon], icon=icon, tooltip=f"{c['nome']} — {c['status']}",
                          popup=folium.Popup(popup_carga(c, nome, extra), max_width=330)).add_to(grupo)
            bounds[cfg["zona"]].append([lat, lon])

    fg_z1.add_to(mapa)
    fg_z2.add_to(mapa)
    folium.LayerControl(position="topright", collapsed=False).add_to(mapa)
    Fullscreen(position="topright").add_to(mapa)
    MiniMap(toggle_display=True, position="bottomright").add_to(mapa)

    def bbox(pts: List[List[float]]) -> List[List[float]]:
        lats, lons = [p[0] for p in pts], [p[1] for p in pts]
        return [[min(lats), min(lons)], [max(lats), max(lons)]]

    estat["bounds"] = {"z1": bbox(bounds[1]), "z2": bbox(bounds[2]), "all": bbox(bounds[1] + bounds[2])}
    return mapa, estat


# --------------------------------------------------------------------------------------------------
# ETAPA 3: FRONTEND (SIDEBAR + CSS) INJETADO NO DOCUMENTO RAIZ DO FOLIUM
# --------------------------------------------------------------------------------------------------
CSS = """
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root{--bg:#0b1120;--panel:#111a2e;--card:#16213a;--line:#24324f;--txt:#e2e8f0;--mut:#8ea0bf;
        --ok:#22c55e;--warn:#f59e0b;--crit:#ef4444;--acc:#38bdf8;--sw:380px}
  html,body{margin:0;height:100%;background:var(--bg);font-family:Inter,system-ui,sans-serif}
  .folium-map{position:absolute!important;left:var(--sw)!important;top:0!important;
              width:calc(100% - var(--sw))!important;height:100vh!important}
  #sidebar{position:fixed;left:0;top:0;bottom:0;width:var(--sw);box-sizing:border-box;z-index:1000;
           background:linear-gradient(180deg,#0f172a 0%,#0b1120 100%);border-right:1px solid var(--line);
           color:var(--txt);overflow-y:auto;padding:22px 20px 18px}
  #sidebar::-webkit-scrollbar{width:6px}#sidebar::-webkit-scrollbar-thumb{background:#24324f;border-radius:3px}
  .brand{display:flex;gap:12px;align-items:center;margin-bottom:6px}
  .brand-logo{width:42px;height:42px;border-radius:11px;display:grid;place-items:center;font-size:21px;
              background:linear-gradient(135deg,#0ea5e9,#6366f1);box-shadow:0 0 22px rgba(56,189,248,.35)}
  h1{font-size:16.5px;line-height:1.25;margin:0;font-weight:800;letter-spacing:-.2px}
  .sub{font-size:11.5px;color:var(--mut);margin:4px 0 0}
  .meta{display:flex;justify-content:space-between;font-size:10.5px;color:var(--mut);margin:14px 0 18px;
        padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:rgba(255,255,255,.02)}
  .live{display:inline-flex;align-items:center;gap:6px}.live i{width:7px;height:7px;border-radius:50%;
        background:var(--ok);box-shadow:0 0 0 0 rgba(34,197,94,.7);animation:blink 2s infinite}
  @keyframes blink{0%{box-shadow:0 0 0 0 rgba(34,197,94,.6)}70%{box-shadow:0 0 0 8px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
  .sec{font-size:10.5px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--mut);margin:18px 0 9px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:13px 14px;margin-bottom:11px;
        transition:transform .18s ease,border-color .18s ease;cursor:pointer;position:relative;overflow:hidden}
  .card:hover{transform:translateY(-2px);border-color:#3b4f78}
  .card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--c)}
  .card-h{display:flex;justify-content:space-between;align-items:center;gap:8px}
  .card-t{font-weight:700;font-size:13.5px}.card-s{font-size:11px;color:var(--mut);margin-top:2px}
  .pill{font-size:10px;font-weight:700;padding:3px 8px;border-radius:999px;white-space:nowrap;
        background:color-mix(in srgb,var(--c) 18%,transparent);color:var(--c);border:1px solid color-mix(in srgb,var(--c) 45%,transparent)}
  .rows{margin-top:10px;display:grid;gap:6px}
  .row{display:flex;justify-content:space-between;font-size:11.5px;padding:6px 8px;border-radius:7px;background:rgba(255,255,255,.03)}
  .row b{font-weight:600}.row .v{font-variant-numeric:tabular-nums;color:#cbd5e1}
  .ok{color:var(--ok)!important}.bad{color:var(--crit)!important}
  .kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
  .kpi{background:rgba(255,255,255,.03);border-radius:8px;padding:7px 9px}.kpi span{display:block;font-size:10px;color:var(--mut)}
  .kpi strong{font-size:13px;font-variant-numeric:tabular-nums}
  .btn{width:100%;display:flex;align-items:center;gap:10px;padding:11px 13px;margin-bottom:8px;border-radius:10px;
       border:1px solid var(--line);background:#131d33;color:#64748b;font:600 12.5px Inter,sans-serif;cursor:not-allowed;
       text-align:left;position:relative}
  .btn small{margin-left:auto;font-size:9.5px;font-weight:700;letter-spacing:.6px;color:#475569;border:1px dashed #334155;
             padding:2px 6px;border-radius:5px}
  .btn .ic{width:26px;height:26px;border-radius:7px;display:grid;place-items:center;background:#1b2743;font-size:13px;filter:grayscale(.6)}
  .nav{display:flex;gap:6px;margin-top:4px}.nav button{flex:1;padding:8px 6px;border-radius:8px;border:1px solid var(--line);
       background:#131d33;color:var(--txt);font:600 11px Inter,sans-serif;cursor:pointer;transition:all .15s}
  .nav button:hover{background:#1e2b4a;border-color:var(--acc);color:#fff}
  .legend{display:grid;grid-template-columns:1fr 1fr;gap:6px 10px;font-size:11px;color:#cbd5e1}
  .legend i{display:inline-block;width:18px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
  .note{font-size:10.5px;color:#fcd34d;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);
        padding:8px 10px;border-radius:9px;line-height:1.45}
  .foot{font-size:10px;color:#475569;margin-top:16px;line-height:1.5}
  .spof-pulse{width:46px;height:46px;border-radius:50%;background:rgba(239,68,68,.9);display:grid;place-items:center;
              border:3px solid #fff;animation:pulse 1.6s infinite;font-size:20px}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(239,68,68,.75)}70%{box-shadow:0 0 0 26px rgba(239,68,68,0)}100%{box-shadow:0 0 0 0 rgba(239,68,68,0)}}
  .leaflet-control-layers{background:rgba(15,23,42,.92)!important;color:#e2e8f0!important;border:1px solid #24324f!important;
                          border-radius:10px!important;font:500 12px Inter,sans-serif!important}
  #toast{position:fixed;left:calc(var(--sw) + 20px);bottom:22px;z-index:1200;background:#0f172a;color:#e2e8f0;
         border:1px solid #334155;padding:10px 14px;border-radius:10px;font:500 12px Inter;opacity:0;transform:translateY(8px);
         transition:all .25s}#toast.show{opacity:1;transform:none}
</style>
"""


def linhas_carga(c: Dict[str, Any]) -> str:
    v = c["tensoes_pu"]
    vmin, vmax = min(v.values()), max(v.values())
    cls = "ok" if c["status"] == "ADEQUADA" else "bad"
    icone = "🏥" if c["tipo"] == "saude" else "🛡️"
    return (f'<div class="row"><b>{icone} {c["id"]}</b><span class="v">{vmin:.3f}–{vmax:.3f} pu · '
            f'<span class="{cls}">{c["status"]}</span></span></div>')


def construir_sidebar(res: Dict[str, Dict[str, Any]], mapa_nome: str, bounds: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    z1 = [res["TN08"], res["CN07"]]
    z2 = [res["SHP"]]
    z1_tensao = pior_status([c["status"] for r in z1 for c in r["cargas"]])
    z2_tensao = pior_status([c["status"] for r in z2 for c in r["cargas"]])
    z1_ok = z1_tensao == "ADEQUADA"
    z2_ok = z2_tensao == "ADEQUADA"
    z1_segregada = res["TN08"]["subestacao"] != res["CN07"]["subestacao"]
    z2_spof = len({c["id"] for c in res["SHP"]["cargas"]}) > 1  # saúde e segurança na mesma SE

    status = {
        "zona1": {"topologia": "Segregada" if z1_segregada else "SPOF", "tensao": z1_tensao.capitalize()},
        "zona2": {"topologia": "SPOF Crítico" if z2_spof else "Segregada", "tensao": z2_tensao.capitalize()},
    }

    def kpis(rs: List[Dict[str, Any]]) -> str:
        inj = sum(r["p_inj_kw"] for r in rs) / 1000.0
        perd = sum(r["p_perdas_kw"] for r in rs)
        return (f'<div class="kpis"><div class="kpi"><span>Injeção total</span><strong>{inj:.2f} MW</strong></div>'
                f'<div class="kpi"><span>Perdas técnicas</span><strong>{perd:.1f} kW</strong></div></div>')

    z1_pill = f'{status["zona1"]["topologia"]} · {status["zona1"]["tensao"]}'
    z2_pill = f'{status["zona2"]["topologia"]} · {status["zona2"]["tensao"]}'
    b = json.dumps(bounds)

    html = f"""
<aside id="sidebar">
  <div class="brand"><div class="brand-logo">🛰️</div>
    <div><h1>Centro de Controle Ciberfísico<br>Resiliência DF</h1>
    <p class="sub">Infraestruturas críticas · Saúde &amp; Segurança Pública</p></div></div>
  <div class="meta"><span class="live"><i></i>Baseline eletromecânico</span><span>Gerado {datetime.now().strftime('%d/%m/%Y %H:%M')}</span></div>

  <div class="sec">Resumo de Status</div>
  <div class="card" style="--c:{'#22c55e' if z1_ok else '#f59e0b'}" onclick="focar('z1')">
    <div class="card-h"><div><div class="card-t">Zona 1 — Ceilândia</div>
      <div class="card-s">SE STN (TN08) · SE SCN (CN07)</div></div><span class="pill">{z1_pill}</span></div>
    <div class="rows">{''.join(linhas_carga(c) for r in z1 for c in r['cargas'])}</div>{kpis(z1)}
  </div>
  <div class="card" style="--c:{'#f59e0b' if z2_spof else '#22c55e'}" onclick="focar('z2')">
    <div class="card-h"><div><div class="card-t">Zona 2 — Asa Sul</div>
      <div class="card-s">SE SHP (HP03 · HP04) — mesma origem</div></div><span class="pill">{z2_pill}</span></div>
    <div class="rows">{''.join(linhas_carga(c) for r in z2 for c in r['cargas'])}</div>{kpis(z2)}
  </div>

  <div class="sec">Navegação</div>
  <div class="nav"><button onclick="focar('z1')">Zona 1</button><button onclick="focar('all')">Visão DF</button><button onclick="focar('z2')">Zona 2</button></div>

  <div class="sec">Painel de Funções · Fase E6</div>
  <button class="btn" disabled title="Disponível na Fase E6"><span class="ic">💉</span>Simular FDI (False Data Injection)<small>E6</small></button>
  <button class="btn" disabled title="Disponível na Fase E6"><span class="ic">⚠️</span>Simular Contingência N-1<small>E6</small></button>
  <button class="btn" disabled title="Disponível na Fase E6"><span class="ic">↺</span>Resetar Baseline<small>E6</small></button>

  <div class="sec">Legenda</div>
  <div class="legend">
    <span><i style="background:#22d3ee"></i>TN08 (HRC)</span><span><i style="background:#fb923c"></i>CN07 (15ª DP)</span>
    <span><i style="background:#4ade80"></i>HP03 (HBDF)</span><span><i style="background:#facc15"></i>HP04 (1ª DP)</span>
    <span>⭐ Saúde</span><span>🛡️ Segurança</span><span style="grid-column:span 2">🔴 SE SHP — Ponto Único de Falha</span>
  </div>

  <div class="sec">Observação de Modelagem</div>
  <div class="note">O PAC do HBDF usa a coordenada Ground Truth (SMHS) do script 17, mas a rede HP03 da BDGD
  termina ~4,4 km antes. O traço vermelho tracejado no mapa marca esse trecho não modelado.</div>

  <div class="foot">Fontes: BDGD ANEEL / Neoenergia · OpenDSS (Snapshot) · PRODIST Módulo 8 (0,93–1,05 pu)<br>
  Masters: {res['TN08']['master']} · {res['CN07']['master']} · {res['SHP']['master']}</div>
</aside>
<div id="toast"></div>
<script>
  const DASH_BOUNDS = {b};
  function focar(k) {{
    const m = window["{mapa_nome}"];
    if (m) m.flyToBounds(DASH_BOUNDS[k], {{padding:[40,40], duration:1.1}});
  }}
  document.querySelectorAll('.btn').forEach(btn => {{
    btn.addEventListener('mouseenter', () => {{
      const t = document.getElementById('toast');
      t.textContent = 'Função reservada para a Fase E6 (Simulações de Cibersegurança).';
      t.classList.add('show'); clearTimeout(window.__tt); window.__tt = setTimeout(() => t.classList.remove('show'), 1800);
    }});
  }});
</script>
"""
    return html, status


# --------------------------------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------------------------------
def main() -> int:
    LOGGER.info("=" * 80)
    LOGGER.info(f"INICIANDO SCRIPT 18: DASHBOARD INTEGRADO RESILIÊNCIA DF (RUN_TAG={RUN_TAG})")
    LOGGER.info("=" * 80)
    try:
        resultados = {nome: resolver_circuito(nome, cfg) for nome, cfg in CIRCUITOS.items()}

        mapa, estat = construir_mapa(resultados)
        sidebar_html, status = construir_sidebar(resultados, mapa.get_name(), estat["bounds"])

        root = mapa.get_root()
        root.header.add_child(Element(
            '<title>Centro de Controle Ciberfísico — Resiliência DF</title>'
            '<meta name="description" content="Dashboard integrado de resiliência das redes de distribuição '
            'que atendem saúde e segurança pública no Distrito Federal (Ceilândia e Asa Sul).">'
        ))
        root.header.add_child(Element(CSS))
        root.html.add_child(Element(sidebar_html))
        mapa.save(str(OUTPUT_HTML))

        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump({"run_tag": RUN_TAG, "status": status, "circuitos": resultados, "estatisticas_mapa": estat},
                      f, indent=2, ensure_ascii=False)

        tamanho = OUTPUT_HTML.stat().st_size
        print(f"""
====================================================================================================
             CENTRO DE CONTROLE CIBERFÍSICO — RESILIÊNCIA DF | DASHBOARD UNIFICADO
====================================================================================================
 Zona 1 (Ceilândia): {status['zona1']['topologia']} · {status['zona1']['tensao']}
   - TN08 / SE STN: {estat['TN08']['segmentos_mt']} segmentos MT | Perdas {resultados['TN08']['p_perdas_kw']:.2f} kW
   - CN07 / SE SCN: {estat['CN07']['segmentos_mt']} segmentos MT | Perdas {resultados['CN07']['p_perdas_kw']:.2f} kW
 Zona 2 (Asa Sul):   {status['zona2']['topologia']} · {status['zona2']['tensao']}
   - HP03/HP04 / SE SHP: {estat['SHP']['segmentos_mt']} segmentos MT | Perdas {resultados['SHP']['p_perdas_kw']:.2f} kW
----------------------------------------------------------------------------------------------------
 Dashboard gerado: {OUTPUT_HTML.resolve()}
 Tamanho: {tamanho:,} bytes | Status JSON: {OUTPUT_JSON.name}
 Abra no navegador: file:///{OUTPUT_HTML.resolve().as_posix()}
====================================================================================================
""")
        LOGGER.info("SCRIPT 18 CONCLUÍDO COM SUCESSO.")
        return 0
    except Exception as exc:
        LOGGER.error(f"Falha no script 18: {exc}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

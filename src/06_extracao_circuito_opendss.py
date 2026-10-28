"""06_extracao_circuito_opendss.py

Etapa E5: Extracao de Ativos e Geracao de Modelo Eletrico OpenDSS do Alimentador TN08 (SE STN).
Extrai ativos fisicos e eletricos da BDGD e das bases consolidadas de UCs para o circuito TN08
e gera os arquivos nativos do OpenDSS:
- Master_TN08_{RUN_TAG}.dss
- Lines_TN08_{RUN_TAG}.dss
- Transformers_TN08_{RUN_TAG}.dss
- Loads_TN08_{RUN_TAG}.dss
- Buscoords_TN08_{RUN_TAG}.dss
- geo_tn08_{RUN_TAG}.gpkg (Camadas espaciais para QGIS e analise GNN)

Saidas em:
data/processed/opendss/
logs/06_extracao_circuito_opendss_{RUN_TAG}.log
"""

from __future__ import annotations

import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

# Configuracoes de caminhos e RUN_TAG
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
OPENDSS_DIR = PROCESSED_DIR / "opendss"
LOGS_DIR = BASE_DIR / "logs"

LOG_PATH = LOGS_DIR / f"06_extracao_circuito_opendss_{RUN_TAG}.log"
LOGGER = logging.getLogger("06_extracao_opendss")


def setup_logging() -> None:
    """Configura logging em UTF-8 no console e arquivo."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    OPENDSS_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)


def obter_gdb() -> Path:
    """Localiza o banco geodatabase (.gdb) da BDGD."""
    gdbs = sorted(RAW_DIR.glob("*.gdb"))
    if not gdbs:
        raise FileNotFoundError(f"Nenhum arquivo .gdb encontrado em {RAW_DIR}")
    return gdbs[0]


def obter_arquivos_consolidados() -> tuple[Path, Path]:
    """Identifica os arquivos mais recentes de UCMT e UCBT consolidados."""
    mt_files = sorted(PROCESSED_DIR.glob("UCMT_consolidada_*.csv"))
    bt_files = sorted(PROCESSED_DIR.glob("UCBT_consolidada_*.csv"))
    if not mt_files or not bt_files:
        raise FileNotFoundError("Bases consolidadas de UCMT/UCBT nao encontradas em data/processed/")
    return mt_files[-1], bt_files[-1]


def normalizar_fase(fas_con: str | None, default_3ph: bool = True) -> tuple[int, str]:
    """Mapeia o codigo de fases da BDGD para fases OpenDSS (nphases, sufixo de nos)."""
    if not fas_con or pd.isna(fas_con):
        return (3, ".1.2.3") if default_3ph else (1, ".1.0")

    fas = str(fas_con).strip().upper()
    if fas in ["ABC", "ABCN"]:
        return (3, ".1.2.3") if default_3ph else (3, ".1.2.3.0")
    if fas == "AB":
        return (2, ".1.2")
    if fas == "BC":
        return (2, ".2.3")
    if fas == "CA":
        return (2, ".3.1")
    if fas in ["AN", "A"]:
        return (1, ".1.0")
    if fas in ["BN", "B"]:
        return (1, ".2.0")
    if fas in ["CN", "C"]:
        return (1, ".3.0")

    return (3, ".1.2.3") if default_3ph else (1, ".1.0")


def limpar_id(val: Any) -> str:
    """Sanitiza strings de identificadores para sintaxe do OpenDSS."""
    if pd.isna(val) or val is None:
        return "DESCONHECIDO"
    s = str(val).strip().replace(" ", "_").replace("/", "_").replace("-", "_")
    return s


def main() -> int:
    setup_logging()
    LOGGER.info("=" * 80)
    LOGGER.info(f"INICIANDO ETAPA E5: EXTRACAO DE ATIVOS E MODELAGEM OPENDSS DO TN08 (RUN_TAG={RUN_TAG})")
    LOGGER.info("=" * 80)

    gdb_path = obter_gdb()
    mt_path, bt_path = obter_arquivos_consolidados()
    LOGGER.info(f"Base BDGD de origem: {gdb_path.name}")
    LOGGER.info(f"Base UCMT consolidada: {mt_path.name}")
    LOGGER.info(f"Base UCBT consolidada: {bt_path.name}")

    # Definicao dos caminhos de saida
    master_file = OPENDSS_DIR / f"Master_TN08_{RUN_TAG}.dss"
    lines_file = OPENDSS_DIR / f"Lines_TN08_{RUN_TAG}.dss"
    trafos_file = OPENDSS_DIR / f"Transformers_TN08_{RUN_TAG}.dss"
    loads_file = OPENDSS_DIR / f"Loads_TN08_{RUN_TAG}.dss"
    coords_file = OPENDSS_DIR / f"Buscoords_TN08_{RUN_TAG}.dss"
    gpkg_file = OPENDSS_DIR / f"geo_tn08_{RUN_TAG}.gpkg"

    for f in [master_file, lines_file, trafos_file, loads_file, coords_file, gpkg_file]:
        if f.exists():
            raise FileExistsError(f"Arquivo de saida ja existente: {f}")

    # 1. Leitura de Metadados do Circuito e Subestacao
    LOGGER.info("Carregando metadados do circuito CTMT TN08 e Subestacao STN...")
    df_ctmt = pyogrio.read_dataframe(str(gdb_path), layer="CTMT", where="COD_ID = 'TN08'")
    if len(df_ctmt) == 0:
        raise ValueError("Circuito TN08 nao encontrado na camada CTMT.")
    ctmt_info = df_ctmt.iloc[0].to_dict()
    pac_ini = str(ctmt_info.get("PAC_INI", "TN_ALTN08")).strip()
    LOGGER.info(f"Alimentador: TN08 | Subestacao: STN | PAC Inicial: {pac_ini} | Tensao Operacao: 13.8 kV")

    # 2. Leitura Espacial de Segmentos de Rede (SSDMT e SSDBT) via GeoPandas e Pyogrio
    LOGGER.info("Extraindo segmentos de Media Tensao (SSDMT) para CTMT == 'TN08'...")
    gdf_ssdmt = gpd.read_file(str(gdb_path), layer="SSDMT", where="CTMT = 'TN08'", engine="pyogrio")
    LOGGER.info(f"SSDMT extraido: {len(gdf_ssdmt)} trechos de Media Tensao.")

    LOGGER.info("Extraindo segmentos de Baixa Tensao (SSDBT) para CTMT == 'TN08'...")
    gdf_ssdbt = gpd.read_file(str(gdb_path), layer="SSDBT", where="CTMT = 'TN08'", engine="pyogrio")
    LOGGER.info(f"SSDBT extraido: {len(gdf_ssdbt)} trechos de Baixa Tensao.")

    # 3. Leitura de Transformadores MT/BT (UNTRMT e EQTRMT)
    LOGGER.info("Extraindo transformadores de distribuicao (UNTRMT) para CTMT == 'TN08'...")
    gdf_untrmt = gpd.read_file(str(gdb_path), layer="UNTRMT", where="CTMT = 'TN08'", engine="pyogrio")
    LOGGER.info(f"UNTRMT extraido: {len(gdf_untrmt)} transformadores de distribuicao.")

    LOGGER.info("Extraindo parametros eletricos de transformadores (EQTRMT)...")
    df_eqtrmt = pyogrio.read_dataframe(str(gdb_path), layer="EQTRMT")
    eqtrmt_map = {row["UNI_TR_MT"]: row for _, row in df_eqtrmt.iterrows()}

    # 4. Leitura de Condutores (SEGCON)
    LOGGER.info("Extraindo catalogo de cabos e condutores (SEGCON)...")
    df_segcon = pyogrio.read_dataframe(str(gdb_path), layer="SEGCON")
    segcon_map = {row["COD_ID"]: row for _, row in df_segcon.iterrows()}

    # 5. Leitura das Bases de UCs Consolidadas
    LOGGER.info("Carregando UCs de Media Tensao (UCMT)...")
    df_ucmt = pd.read_csv(mt_path, dtype=str)
    ucmt_tn08 = df_ucmt[df_ucmt["CTMT"] == "TN08"].copy()
    LOGGER.info(f"UCMT conectadas ao TN08: {len(ucmt_tn08)} UCs.")

    LOGGER.info("Carregando UCs de Baixa Tensao (UCBT)...")
    bt_cols = [
        "COD_ID", "PAC", "RAMAL", "PN_CON", "UNI_TR_MT", "CTMT", "CAR_INST",
        "FAS_CON", "CLAS_SUB", "CNAE", "ENE_01", "ENE_02", "ENE_03", "ENE_04",
        "ENE_05", "ENE_06", "ENE_07", "ENE_08", "ENE_09", "ENE_10", "ENE_11", "ENE_12"
    ]
    df_ucbt = pd.read_csv(bt_path, dtype=str, usecols=bt_cols)
    ucbt_tn08 = df_ucbt[df_ucbt["CTMT"] == "TN08"].copy()
    LOGGER.info(f"UCBT conectadas ao TN08: {len(ucbt_tn08)} UCs.")

    # Mapeamento de Coordenadas de Barras (para OpenDSS e QGIS/GNN)
    bus_coords: dict[str, tuple[float, float]] = {}

    def registrar_coords_linha(gdf: gpd.GeoDataFrame, col_pac1: str, col_pac2: str) -> None:
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom and not geom.is_empty:
                # Se for MultiLineString ou LineString
                coords = list(geom.geoms[0].coords) if geom.geom_type == "MultiLineString" else list(geom.coords)
                p1 = coords[0]
                p2 = coords[-1]
                pac1 = limpar_id(row[col_pac1])
                pac2 = limpar_id(row[col_pac2])
                if pac1 not in bus_coords:
                    bus_coords[pac1] = (p1[0], p1[1])
                if pac2 not in bus_coords:
                    bus_coords[pac2] = (p2[0], p2[1])

    registrar_coords_linha(gdf_ssdmt, "PAC_1", "PAC_2")
    registrar_coords_linha(gdf_ssdbt, "PAC_1", "PAC_2")

    for _, row in gdf_untrmt.iterrows():
        geom = row.geometry
        if geom and not geom.is_empty:
            p = geom.coords[0] if geom.geom_type == "Point" else geom.geoms[0].coords[0]
            pac1 = limpar_id(row["PAC_1"])
            pac2 = limpar_id(row["PAC_2"])
            if pac1 not in bus_coords:
                bus_coords[pac1] = (p[0], p[1])
            if pac2 not in bus_coords:
                bus_coords[pac2] = (p[0] + 0.00005, p[1] + 0.00005)

    # Subestacao STN Bus Coord
    if pac_ini in bus_coords:
        stn_x, stn_y = bus_coords[pac_ini]
    else:
        stn_x, stn_y = (-48.084481, -15.802744)
        bus_coords[pac_ini] = (stn_x, stn_y)
    bus_coords["STN_138kV"] = (stn_x - 0.0002, stn_y)
    bus_coords["STN_TN08_SUB"] = (stn_x - 0.0001, stn_y)

    # 6. Geracao de LineCodes necessarios
    LOGGER.info("Mapeando LineCodes de condutores de MT e BT...")
    cnd_codes = set(gdf_ssdmt["TIP_CND"].dropna().unique()).union(
        set(gdf_ssdbt["TIP_CND"].dropna().unique())
    )

    linecode_commands: list[str] = []
    for cnd in sorted(cnd_codes):
        cnd_clean = limpar_id(cnd)
        seg = segcon_map.get(cnd)
        if seg is not None:
            r1 = float(seg["R1"]) if pd.notna(seg["R1"]) and float(seg["R1"]) > 0 else 0.35
            x1 = float(seg["X1"]) if pd.notna(seg["X1"]) and float(seg["X1"]) > 0 else 0.38
            cnom = float(seg["CNOM"]) if pd.notna(seg["CNOM"]) and float(seg["CNOM"]) > 0 else 300.0
            cmax = float(seg["CMAX"]) if pd.notna(seg["CMAX"]) and float(seg["CMAX"]) > 0 else 350.0
            descr = str(seg.get("DESCR", "")).strip().replace("\n", " ")
        else:
            r1 = 0.45
            x1 = 0.35
            cnom = 250.0
            cmax = 300.0
            descr = "Parametros Padrao Distribuidora"

        r0 = r1 * 2.8
        x0 = x1 * 2.8
        linecode_commands.append(
            f"New LineCode.{cnd_clean} nphases=3 r1={r1:.5f} x1={x1:.5f} r0={r0:.5f} x0={x0:.5f} "
            f"units=km normamps={cnom:.1f} emergamps={cmax:.1f} ! {descr}"
        )

    # 7. Geracao do Arquivo de Linhas (Lines_TN08.dss)
    LOGGER.info("Gerando arquivo de linhas de transmissao e distribuicao...")
    lines_content: list[str] = [
        f"! OpenDSS Lines - Circuito TN08 (SE STN) | RUN_TAG: {RUN_TAG}",
        f"! Total de Linhas MT: {len(gdf_ssdmt)} | Total de Linhas BT: {len(gdf_ssdbt)}",
        ""
    ]

    # Segmentos de Media Tensao (SSDMT)
    lines_content.append("! ------------------- LINHAS DE MEDIA TENSAO (SSDMT - 13.8 kV) -------------------")
    for _, row in gdf_ssdmt.iterrows():
        cod_id = limpar_id(row["COD_ID"])
        pac1 = limpar_id(row["PAC_1"])
        pac2 = limpar_id(row["PAC_2"])
        cnd = limpar_id(row["TIP_CND"])
        comp = float(row["COMP"]) if pd.notna(row["COMP"]) and float(row["COMP"]) > 0 else 10.0
        nphases, node_suf = normalizar_fase(row.get("FAS_CON"), default_3ph=True)

        lines_content.append(
            f"New Line.MT_{cod_id} Phases={nphases} Bus1={pac1}{node_suf} Bus2={pac2}{node_suf} "
            f"LineCode={cnd} Length={comp:.2f} Units=m"
        )

    # Segmentos de Baixa Tensao (SSDBT)
    lines_content.append("\n! ------------------- LINHAS DE BAIXA TENSAO (SSDBT - 380/220 V) -------------------")
    for _, row in gdf_ssdbt.iterrows():
        cod_id = limpar_id(row["COD_ID"])
        pac1 = limpar_id(row["PAC_1"])
        pac2 = limpar_id(row["PAC_2"])
        cnd = limpar_id(row["TIP_CND"])
        comp = float(row["COMP"]) if pd.notna(row["COMP"]) and float(row["COMP"]) > 0 else 10.0
        nphases, node_suf = normalizar_fase(row.get("FAS_CON"), default_3ph=False)

        lines_content.append(
            f"New Line.BT_{cod_id} Phases={nphases} Bus1={pac1}{node_suf} Bus2={pac2}{node_suf} "
            f"LineCode={cnd} Length={comp:.2f} Units=m"
        )

    with open(lines_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_content) + "\n")
    LOGGER.info(f"Lines gravado com sucesso: {lines_file.name} ({len(gdf_ssdmt) + len(gdf_ssdbt)} linhas)")

    # 8. Geracao do Arquivo de Transformadores (Transformers_TN08.dss)
    LOGGER.info("Gerando arquivo de transformadores MT/BT...")
    trafos_content: list[str] = [
        f"! OpenDSS Transformers - Circuito TN08 (SE STN) | RUN_TAG: {RUN_TAG}",
        f"! Total de Transformadores de Distribuicao MT/BT: {len(gdf_untrmt)}",
        ""
    ]

    ssdbt_nodes = set(gdf_ssdbt["PAC_1"].map(limpar_id)).union(set(gdf_ssdbt["PAC_2"].map(limpar_id)))

    for _, row in gdf_untrmt.iterrows():
        cod_id = limpar_id(row["COD_ID"])
        pac_mt = limpar_id(row["PAC_1"])
        pac_bt = limpar_id(row["PAC_2"])
        pot_nom = float(row["POT_NOM"]) if pd.notna(row["POT_NOM"]) and float(row["POT_NOM"]) > 0 else 75.0
        ten_lin_se = float(row["TEN_LIN_SE"]) if pd.notna(row["TEN_LIN_SE"]) and float(row["TEN_LIN_SE"]) > 0 else 0.38
        if ten_lin_se > 10.0:  # Em caso de valor em Volts
            ten_lin_se = ten_lin_se / 1000.0

        # Parametros de ensaio e impedancia de EQTRMT
        eq = eqtrmt_map.get(row["COD_ID"])
        if eq is not None:
            r = float(eq["R"]) if pd.notna(eq["R"]) and float(eq["R"]) > 0 else 1.45
            xhl = float(eq["XHL"]) if pd.notna(eq["XHL"]) and float(eq["XHL"]) > 0 else 2.50
            per_fer = float(eq["PER_FER"]) if pd.notna(eq["PER_FER"]) else 250.0
            per_tot = float(eq["PER_TOT"]) if pd.notna(eq["PER_TOT"]) else 1400.0
        else:
            r = 1.50
            xhl = 2.50
            per_fer = float(row.get("PER_FER", 250.0))
            per_tot = float(row.get("PER_TOT", 1400.0))

        noloadloss = (per_fer / (pot_nom * 1000.0)) * 100.0 if pot_nom > 0 else 0.3
        loadloss = ((per_tot - per_fer) / (pot_nom * 1000.0)) * 100.0 if pot_nom > 0 and per_tot > per_fer else 1.5

        trafos_content.append(
            f"New Transformer.{cod_id} Phases=3 Windings=2 XHL={xhl:.3f} %loadloss={loadloss:.3f} %noloadloss={noloadloss:.3f}\n"
            f"~ Wdg=1 Bus={pac_mt}.1.2.3 kV=13.8 kVA={pot_nom:.1f} Conn=Delta %r={r/2.0:.3f}\n"
            f"~ Wdg=2 Bus={pac_bt}.1.2.3.0 kV={ten_lin_se:.3f} kVA={pot_nom:.1f} Conn=Wye %r={r/2.0:.3f}"
        )

    with open(trafos_file, "w", encoding="utf-8") as f:
        f.write("\n".join(trafos_content) + "\n")
    LOGGER.info(f"Transformers gravado com sucesso: {trafos_file.name} ({len(gdf_untrmt)} transformadores)")

    # 9. Geracao do Arquivo de Cargas (Loads_TN08.dss)
    LOGGER.info("Gerando arquivo de cargas eletricas (UCMT e UCBT)...")
    loads_content: list[str] = [
        f"! OpenDSS Loads - Circuito TN08 (SE STN) | RUN_TAG: {RUN_TAG}",
        f"! Cargas de Media Tensao: {len(ucmt_tn08)} | Cargas de Baixa Tensao: {len(ucbt_tn08)}",
        ""
    ]

    # 9.1 Cargas de Media Tensao (UCMT)
    loads_content.append("! ==============================================================================")
    loads_content.append("! ------------------- CARGAS DE MEDIA TENSAO (UCMT - 13.8 kV) -------------------")
    loads_content.append("! ==============================================================================")

    pac_hrc_target = "STN_TN08_9026_CEI003"
    hrc_encontrado = False

    for idx, row in ucmt_tn08.iterrows():
        cod_id = str(row["COD_ID"]).strip()
        pac = limpar_id(row["PAC"])
        dem_cont = float(row["DEM_CONT"]) if pd.notna(row["DEM_CONT"]) and float(row["DEM_CONT"]) > 0 else 0.0
        car_inst = float(row["CAR_INST"]) if pd.notna(row["CAR_INST"]) and float(row["CAR_INST"]) > 0 else 0.0

        # Prioridade HRC
        if pac == pac_hrc_target or "01d6dfec" in cod_id:
            hrc_encontrado = True
            kw_hrc = dem_cont if dem_cont > 0 else 110.22
            loads_content.append(
                f"! ------------------------------------------------------------------------------\n"
                f"! CARGA PRIORITARIA CRITICA: HOSPITAL REGIONAL DE CEILANDIA (HRC)\n"
                f"! COD_ID: {cod_id}\n"
                f"! Localizacao: Bairro {row.get('BRR', 'CEILANDIA')} | CEP: {row.get('CEP', '72215-178')}\n"
                f"! CNAE: {row.get('CNAE', '8610-1/01')} | Carga Instalada: {car_inst:.2f} kW | Demanda Contratada: {dem_cont:.2f} kW\n"
                f"! ------------------------------------------------------------------------------\n"
                f"New Load.HRC_PRIORITARIO Bus1={pac}.1.2.3 Phases=3 kV=13.8 kW={kw_hrc:.2f} pf=0.92 Model=1 Class=1 Status=Variable\n"
            )
        else:
            kw_load = dem_cont if dem_cont > 0 else (car_inst if car_inst > 0 else 15.0)
            nphases, node_suf = normalizar_fase(row.get("FAS_CON"), default_3ph=True)
            kv_load = 13.8 if nphases == 3 else 7.967
            load_name = f"UCMT_{cod_id[:16]}"
            loads_content.append(
                f"New Load.{load_name} Bus1={pac}{node_suf} Phases={nphases} kV={kv_load:.3f} "
                f"kW={kw_load:.2f} pf=0.92 Model=1 ! CarInst={car_inst:.1f}kW DemCont={dem_cont:.1f}kW"
            )

    if not hrc_encontrado:
        LOGGER.warning("UC do HRC nao foi encontrada diretamente pelo PAC exato em UCMT; adicionando explicitamente.")
        loads_content.append(
            f"New Load.HRC_PRIORITARIO Bus1={pac_hrc_target}.1.2.3 Phases=3 kV=13.8 kW=110.22 pf=0.92 Model=1 Class=1 Status=Variable\n"
        )

    # 9.2 Cargas de Baixa Tensao (UCBT)
    loads_content.append("\n! ==============================================================================")
    loads_content.append("! ------------------- CARGAS DE BAIXA TENSAO (UCBT - 380/220 V) -------------------")
    loads_content.append("! ==============================================================================")

    trafo_sec_map = dict(zip(gdf_untrmt["COD_ID"].map(limpar_id), gdf_untrmt["PAC_2"].map(limpar_id)))

    total_bt_alocadas = 0
    alocadas_poste = 0
    alocadas_trafo = 0

    for idx, row in ucbt_tn08.iterrows():
        cod_id = str(row["COD_ID"]).strip()
        trafo_id = limpar_id(row["UNI_TR_MT"])
        pn_con = limpar_id(row["PN_CON"])
        node_candidato = f"{trafo_id}_{pn_con}"

        # Alocacao topologica
        if node_candidato in ssdbt_nodes:
            bus_aloc = node_candidato
            alocadas_poste += 1
        elif trafo_id in trafo_sec_map:
            bus_aloc = trafo_sec_map[trafo_id]
            alocadas_trafo += 1
        else:
            # Fallback seguro para o primeiro trafo valido
            bus_aloc = list(trafo_sec_map.values())[0]
            alocadas_trafo += 1

        car_inst = float(row["CAR_INST"]) if pd.notna(row["CAR_INST"]) and float(row["CAR_INST"]) > 0 else 0.0

        # Estimativa de kW da carga
        if 0.5 <= car_inst <= 100.0:
            kw_bt = car_inst * 0.35  # Fator de demanda tipico BT
        else:
            # Media das energias ENE_01..12 em kWh/mes / 720h
            ene_vals = [float(row[f"ENE_{m:02d}"]) for m in range(1, 13) if pd.notna(row.get(f"ENE_{m:02d}"))]
            ene_media = sum(ene_vals) / len(ene_vals) if ene_vals else 250.0
            kw_bt = max((ene_media / 720.0) / 0.95, 0.5)

        nphases, node_suf = normalizar_fase(row.get("FAS_CON"), default_3ph=False)
        kv_bt = 0.38 if nphases == 3 else 0.22

        clean_uid = cod_id[:12] if len(cod_id) >= 12 else str(idx)
        loads_content.append(
            f"New Load.UCBT_{idx}_{clean_uid} Bus1={bus_aloc}{node_suf} Phases={nphases} "
            f"kV={kv_bt:.3f} kW={kw_bt:.2f} pf=0.95 Model=1"
        )
        total_bt_alocadas += 1

    with open(loads_file, "w", encoding="utf-8") as f:
        f.write("\n".join(loads_content) + "\n")

    LOGGER.info(f"Loads gravado com sucesso: {loads_file.name} ({len(ucmt_tn08)} UCMT, {total_bt_alocadas} UCBT)")
    LOGGER.info(f"  * UCBT conectadas no poste da rede BT: {alocadas_poste} ({alocadas_poste/total_bt_alocadas*100:.1f}%)")
    LOGGER.info(f"  * UCBT conectadas no barramento do transformador: {alocadas_trafo} ({alocadas_trafo/total_bt_alocadas*100:.1f}%)")

    # 10. Geracao do Arquivo de Coordenadas de Barras (Buscoords_TN08.dss)
    LOGGER.info(f"Exportando coordenadas de {len(bus_coords)} barras...")
    coords_content: list[str] = [
        f"! OpenDSS Bus Coordinates - Circuito TN08 | RUN_TAG: {RUN_TAG}",
        f"! Formato: BusName X(Longitude) Y(Latitude)",
        ""
    ]
    for bname, (bx, by) in sorted(bus_coords.items()):
        coords_content.append(f"{bname} {bx:.6f} {by:.6f}")

    with open(coords_file, "w", encoding="utf-8") as f:
        f.write("\n".join(coords_content) + "\n")
    LOGGER.info(f"Buscoords gravado com sucesso: {coords_file.name} ({len(bus_coords)} barras)")

    # 11. Geracao do Arquivo Mestre (Master_TN08.dss)
    LOGGER.info("Gerando arquivo Master_TN08.dss...")
    master_content: list[str] = [
        f"! ==============================================================================",
        f"! OPENDSS MASTER FILE: CIRCUITO ALIMENTADOR TN08 - SUBESTACAO STN",
        f"! Neoenergia Distribuicao Brasilia / BDGD ANEEL 2025/2026",
        f"! Gerado por: src/06_extracao_circuito_opendss.py | RUN_TAG: {RUN_TAG}",
        f"! Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"! ==============================================================================",
        "",
        "Clear",
        "Set DefaultBaseFrequency=60",
        "",
        "! --- 1. FONTE EQUIVALENTE DA SUBESTACAO STN (138 kV) ---",
        "New Circuit.TN08 BasekV=138.0 pu=1.02 Angle=0.0 Frequency=60 Phases=3 Bus1=STN_138kV",
        "",
        "! --- 2. TRANSFORMADOR DE SUBESTACAO T-1_STN (138 kV / 13.8 kV - 32 MVA) ---",
        "New Transformer.T1_STN Phases=3 Windings=2 XHL=10.0 %loadloss=0.5 %noloadloss=0.1",
        "~ Wdg=1 Bus=STN_138kV kV=138.0 kVA=32000 Conn=Delta %r=0.25",
        "~ Wdg=2 Bus=STN_TN08_SUB kV=13.8 kVA=32000 Conn=Wye %r=0.25",
        "",
        f"! --- 3. CONEXAO DO BARRAMENTO DA SE AO INICIO DO ALIMENTADOR (PAC_INI: {pac_ini}) ---",
        f"New Line.L_ALIMENTADOR_INICIAL Phases=3 Bus1=STN_TN08_SUB.1.2.3 Bus2={pac_ini}.1.2.3 "
        f"Length=0.001 Units=km r1=0.001 x1=0.001 r0=0.002 x0=0.002",
        "",
        "! --- 4. CATALOGO DE LINECODES (CONDUTORES SEGCON) ---",
    ]
    master_content.extend(linecode_commands)
    master_content.extend([
        "",
        f"! --- 5. REDIRECIONAMENTO DE COMPONENTES MODULARES ---",
        f"Redirect {lines_file.name}",
        f"Redirect {trafos_file.name}",
        f"Redirect {loads_file.name}",
        f"Buscoords {coords_file.name}",
        "",
        "! --- 6. DEFINICAO DE TENSOES BASE E REGIME DE OPERACAO ---",
        "Set VoltageBases = [138.0, 13.8, 0.38, 0.22]",
        "CalcVoltageBases",
        "",
        "! Modo de solucao estatico para fluxo de potencia",
        "Set Mode=Snapshot",
        "Set Maxiterations=100",
        "Set Tolerance=0.0001",
        "",
        "! Comando de solucao (descomentar para resolver imediatamente)",
        "! Solve",
        "! Show Voltages LN Nodes",
        "! Show Powers kVA Elements",
    ])

    with open(master_file, "w", encoding="utf-8") as f:
        f.write("\n".join(master_content) + "\n")
    LOGGER.info(f"Master gravado com sucesso: {master_file.name}")

    # 12. Exportacao Geoespacial (GeoPackage) para QGIS e Analise GNN
    LOGGER.info("Salvando camadas espaciais no GeoPackage geo_tn08.gpkg...")
    gdf_ssdmt.to_file(str(gpkg_file), layer="linhas_mt_ssdmt", driver="GPKG")
    gdf_ssdbt.to_file(str(gpkg_file), layer="linhas_bt_ssdbt", driver="GPKG")
    gdf_untrmt.to_file(str(gpkg_file), layer="trafos_untrmt", driver="GPKG")
    LOGGER.info(f"GeoPackage gravado com sucesso: {gpkg_file.name}")

    # 13. Resumo Consolidado de Componentes
    LOGGER.info("=" * 80)
    LOGGER.info("RESUMO DA EXTRACAO E CONVERSAO DO CIRCUITO TN08 (OPENDSS):")
    LOGGER.info("=" * 80)
    LOGGER.info(f"  * Subestacao: STN (138 kV) -> Trafo T-1_STN (32 MVA, 138/13.8 kV)")
    LOGGER.info(f"  * Segmentos de Média Tensão (SSDMT): {len(gdf_ssdmt)} linhas")
    LOGGER.info(f"  * Segmentos de Baixa Tensão (SSDBT): {len(gdf_ssdbt)} linhas")
    LOGGER.info(f"  * Total de Linhas: {len(gdf_ssdmt) + len(gdf_ssdbt) + 1} (inclui segmento da SE)")
    LOGGER.info(f"  * Transformadores MT/BT (UNTRMT): {len(gdf_untrmt)} transformadores de distribuicao")
    LOGGER.info(f"  * Total de Transformadores: {len(gdf_untrmt) + 1} (inclui T-1_STN)")
    LOGGER.info(f"  * Cargas de Media Tensao (UCMT): {len(ucmt_tn08)} UCs (com HRC Carga Prioritaria)")
    LOGGER.info(f"  * Cargas de Baixa Tensao (UCBT): {len(ucbt_tn08)} UCs")
    LOGGER.info(f"  * Total de Cargas Convertidas: {len(ucmt_tn08) + len(ucbt_tn08)} cargas")
    LOGGER.info(f"  * Catalogo de Condutores (LineCodes): {len(linecode_commands)} codigos")
    LOGGER.info(f"  * Barras Mapeadas com Coordenadas Geograficas: {len(bus_coords)} barras")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Etapa E5 (Extracao OpenDSS do TN08) concluida com exito.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

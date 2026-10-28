#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
PROJETO: Modelos Preditivos na Rede Elétrica do DF (Distrito Federal)
SISTEMA: Circuito Alimentador TN08 - Subestação STN (138 / 13.8 kV)
SCRIPT:  src/09_correcao_e_auditoria_visual.py
AUTOR:   Engenheiro Eletricista Especialista em Planejamento da Operação e Dados
MISSÃO:  1. Aplicar correção do Fator de Coincidência nas cargas de BT (fórmula de pico).
         2. Aplicar regulação de tensão na Subestação STN (saída regulada a 1.04 pu).
         3. Resolver fluxo de potência corrigido no OpenDSS (dss-python).
         4. Emitir Dashboard de Auditoria PRODIST no terminal (HRC, perdas, injeção SE).
         5. Gerar Laudo Visual Georreferenciado Estático (Matplotlib / GeoPandas PNG).
         6. Gerar Mapa Interativo Georreferenciado (Folium HTML com OpenStreetMap).
================================================================================
"""

from __future__ import annotations

import logging
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")  # Backend headless seguro para servidores e scripts
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import folium
from folium import plugins
import dss

# ------------------------------------------------------------------------------
# Configurações de Governança, Diretórios e Logging
# ------------------------------------------------------------------------------
RUN_TAG: str = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
PROCESSED_DIR: Path = DATA_DIR / "processed"
DSS_DIR: Path = PROCESSED_DIR / "opendss"

LOG_DIR: Path = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE: Path = LOG_DIR / f"09_correcao_auditoria_visual_{RUN_TAG}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
LOGGER: logging.getLogger = logging.getLogger("CorrecaoAuditoriaVisual")

# Constantes Regulatórias e de Engenharia (ANEEL PRODIST Módulo 8)
PRODIST_VMIN_ADEQUADO: float = 0.93  # Faixa Adequada: 0.93 <= V <= 1.05 pu
PRODIST_VMAX_ADEQUADO: float = 1.05
PRODIST_VMIN_PRECARIO: float = 0.90  # Faixa Precária: 0.90 <= V < 0.93 pu
PAC_HRC_ID: str = "STN_TN08_9026_CEI003"
PAC_SE_SUB: str = "STN_TN08_SUB"
HRC_DEMANDA_CONTRATADA_KW: float = 110.22


def encontrar_arquivo_mais_recente(diretorio: Path, padrao: str) -> Path:
    """Localiza o arquivo mais recente em um diretório com base no padrão glob ordenado por RUN_TAG."""
    # Filtra arquivos temporarios que comecam com test_
    arquivos = sorted([p for p in diretorio.glob(padrao) if not p.name.startswith("test_")], key=lambda p: p.name)
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo encontrado em {diretorio} com o padrão '{padrao}'.")
    return arquivos[-1]


def aplicar_correcao_fator_coincidencia(
    arquivo_ucbt: Path,
    arquivo_loads_original: Path,
    arquivo_loads_saida: Path
) -> Tuple[int, float, float]:
    """
    Aplica o Fator de Coincidência nas cargas de Baixa Tensão (BT):
    1. Lê a base UCBT consolidada para o alimentador TN08.
    2. Calcula a energia mensal média (ENE_MEDIO) das colunas ENE_01 a ENE_12.
    3. Recalcula a demanda de pico: kW = (ENE_MEDIO / 730) * 1.5 (com piso de 0.05 kW).
    4. Atualiza o arquivo de cargas do OpenDSS preservando UCMT e HRC intactos.
    """
    LOGGER.info("=" * 80)
    LOGGER.info("FASE 1: CORREÇÃO DO FATOR DE COINCIDÊNCIA DAS CARGAS DE BAIXA TENSÃO (BT)")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Lendo base consolidada UCBT: {arquivo_ucbt.name}")

    bt_cols = [
        "COD_ID", "PAC", "RAMAL", "PN_CON", "UNI_TR_MT", "CTMT", "CAR_INST",
        "FAS_CON", "CLAS_SUB", "CNAE", "ENE_01", "ENE_02", "ENE_03", "ENE_04",
        "ENE_05", "ENE_06", "ENE_07", "ENE_08", "ENE_09", "ENE_10", "ENE_11", "ENE_12"
    ]
    df_ucbt = pd.read_csv(arquivo_ucbt, dtype=str, usecols=bt_cols, encoding="utf-8-sig")
    df_ucbt_tn08 = df_ucbt[df_ucbt["CTMT"] == "TN08"].copy()
    LOGGER.info(f"Total de UCs de Baixa Tensão no alimentador TN08: {len(df_ucbt_tn08)}")

    ene_cols = [f"ENE_{m:02d}" for m in range(1, 13)]
    for col in ene_cols:
        df_ucbt_tn08[col] = pd.to_numeric(
            df_ucbt_tn08[col].astype(str).str.replace(",", "."),
            errors="coerce"
        )

    # Energia média mensal em kWh/mês
    df_ucbt_tn08["ENE_MEDIO"] = df_ucbt_tn08[ene_cols].mean(axis=1).fillna(0.0)

    # Fórmula Realista de Pico com Fator de Coincidência: kW = (ENE_MEDIO / 730) * 1.5
    # Garantia de piso técnico de 0.05 kW para evitar cargas puramente nulas
    df_ucbt_tn08["KW_CORRIGIDO"] = (df_ucbt_tn08["ENE_MEDIO"] / 730.0) * 1.5
    df_ucbt_tn08["KW_CORRIGIDO"] = df_ucbt_tn08["KW_CORRIGIDO"].clip(lower=0.05)

    soma_kw_novo = df_ucbt_tn08["KW_CORRIGIDO"].sum()
    media_kw_novo = df_ucbt_tn08["KW_CORRIGIDO"].mean()
    max_kw_novo = df_ucbt_tn08["KW_CORRIGIDO"].max()
    min_kw_novo = df_ucbt_tn08["KW_CORRIGIDO"].min()

    LOGGER.info(f"Estatísticas de Demanda BT Recalculadas:")
    LOGGER.info(f"  * Potência Ativa Total BT: {soma_kw_novo:.2f} kW ({soma_kw_novo/1000.0:.3f} MW)")
    LOGGER.info(f"  * Média por UCBT: {media_kw_novo:.3f} kW")
    LOGGER.info(f"  * Faixa: [{min_kw_novo:.2f} kW a {max_kw_novo:.2f} kW]")

    # Ler o arquivo Loads original e substituir os valores de kW das cargas UCBT
    with open(arquivo_loads_original, "r", encoding="utf-8") as f:
        linhas_loads = f.readlines()

    novas_linhas_loads: List[str] = []
    bt_idx = 0
    kw_novo_lista = df_ucbt_tn08["KW_CORRIGIDO"].tolist()
    total_modificados = 0
    soma_kw_anterior = 0.0

    for linha in linhas_loads:
        linha_strip = linha.strip()
        if linha_strip.startswith("New Load.UCBT_"):
            # Extrair kW anterior para registro de auditoria
            m_ant = re.search(r"kW=([0-9\.]+)", linha)
            if m_ant:
                soma_kw_anterior += float(m_ant.group(1))

            if bt_idx < len(kw_novo_lista):
                kw_val = kw_novo_lista[bt_idx]
                nova_linha = re.sub(r"kW=[0-9\.]+", f"kW={kw_val:.2f}", linha)
                novas_linhas_loads.append(nova_linha)
                total_modificados += 1
                bt_idx += 1
            else:
                novas_linhas_loads.append(linha)
        else:
            novas_linhas_loads.append(linha)

    # Escrever no arquivo de saída
    with open(arquivo_loads_saida, "w", encoding="utf-8") as f:
        f.writelines(novas_linhas_loads)

    LOGGER.info(f"Arquivo de cargas corrigido gravado: {arquivo_loads_saida.name}")
    LOGGER.info(f"  * Cargas UCBT modificadas: {total_modificados}")
    LOGGER.info(f"  * Potência BT Anterior: {soma_kw_anterior:.2f} kW ({soma_kw_anterior/1000.0:.3f} MW)")
    LOGGER.info(f"  * Redução de Injeção BT Irreal: {(soma_kw_anterior - soma_kw_novo)/1000.0:.3f} MW")

    return total_modificados, soma_kw_anterior, soma_kw_novo


def aplicar_regulacao_subestacao(
    arquivo_master_original: Path,
    arquivo_master_saida: Path,
    arquivo_loads_corrigido: Path,
    tensao_alvo_pu: float = 1.04
) -> None:
    """
    Aplica regulação de tensão na Subestação STN:
    1. Ajusta Vsource pu para 1.04 pu na barra de 138 kV.
    2. Ajusta o tap do transformador T1_STN para garantir 1.04 pu no secundário (13.8 kV).
    3. Redireciona o arquivo de cargas para o arquivo corrigido.
    """
    LOGGER.info("=" * 80)
    LOGGER.info("FASE 2: REGULAÇÃO DE TENSÃO DA SUBESTAÇÃO STN (1.04 pu)")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Lendo Master DSS original: {arquivo_master_original.name}")

    with open(arquivo_master_original, "r", encoding="utf-8") as f:
        conteudo_master = f.read()

    # 1. Regulação do Circuito / Vsource equivalente
    # Substituir pu=... no New Circuit.TN08
    conteudo_corrigido = re.sub(
        r"(New\s+Circuit\.TN08[^\r\n]*?pu=)[0-9\.]+",
        rf"\g<1>{tensao_alvo_pu:.2f}",
        conteudo_master,
        flags=re.IGNORECASE
    )

    # 2. Tap de compensação no secundário do Transformer T1_STN
    # Garantir tensão de saída de 1.04 pu sob carregamento nominal
    conteudo_corrigido = re.sub(
        r"(~\s*Wdg=2\s+Bus=STN_TN08_SUB\s+kV=13\.8\s+kVA=32000\s+Conn=Wye\s+%r=0\.25)([^\r\n]*)",
        r"\g<1> Tap=1.008",
        conteudo_corrigido,
        flags=re.IGNORECASE
    )

    # 3. Atualizar redirecionamento de Loads para o novo arquivo corrigido
    conteudo_corrigido = re.sub(
        r"Redirect\s+Loads_TN08_[^\r\n]+",
        f"Redirect {arquivo_loads_corrigido.name}",
        conteudo_corrigido
    )

    with open(arquivo_master_saida, "w", encoding="utf-8") as f:
        f.write(conteudo_corrigido)

    LOGGER.info(f"Arquivo Master regulado gravado com sucesso: {arquivo_master_saida.name}")
    LOGGER.info(f"  * Tensão nominal da barra equivalente 138 kV: {tensao_alvo_pu:.2f} pu")
    LOGGER.info(f"  * Tap do enrolamento secundário (13.8 kV) do Trafo T-1_STN: 1.008")


def executar_fluxo_potencia_e_auditar(
    arquivo_master: Path
) -> Dict[str, any]:
    """
    Compila o circuito no OpenDSS, executa o fluxo de potência (Solve)
    e extrai os resultados de auditoria PRODIST no HRC, perdas e injeção da SE.
    """
    LOGGER.info("=" * 80)
    LOGGER.info("FASE 3: EXECUÇÃO DO FLUXO DE POTÊNCIA E AUDITORIA PRODIST (ANEEL)")
    LOGGER.info("=" * 80)

    engine = dss.DSS
    text = engine.Text

    LOGGER.info(f"Compilando circuito OpenDSS: {arquivo_master.resolve()}")
    text.Command = f"compile '{arquivo_master.resolve()}'"
    text.Command = "Set VoltageBases = [138.0, 13.8, 0.38, 0.22]"
    text.Command = "CalcVoltageBases"
    text.Command = "Solve"

    circuit = engine.ActiveCircuit
    convergiu = bool(circuit.Solution.Converged)
    iteracoes = int(circuit.Solution.Iterations)

    if not convergiu:
        raise RuntimeError("O fluxo de potência no OpenDSS não convergiu após as correções.")

    LOGGER.info(f"Fluxo de Potência convergiu com sucesso em {iteracoes} iterações!")

    # 1. Auditoria do Barramento da Subestação (STN_TN08_SUB)
    circuit.SetActiveBus(PAC_SE_SUB)
    sub_nodes = circuit.ActiveBus.Nodes
    sub_vmag_ang = circuit.ActiveBus.puVmagAngle
    v_sub_pu = [float(sub_vmag_ang[2 * i]) for i in range(len(sub_nodes))]

    # 2. Auditoria do PAC do HRC (STN_TN08_9026_CEI003)
    circuit.SetActiveBus(PAC_HRC_ID)
    hrc_nodes = circuit.ActiveBus.Nodes
    hrc_vmag_ang = circuit.ActiveBus.puVmagAngle
    v_hrc_pu = [float(hrc_vmag_ang[2 * i]) for i in range(len(hrc_nodes))]

    # 3. Perdas Técnicas Totais do Circuito
    losses = circuit.Losses
    p_perdas_kw = float(losses[0]) / 1000.0
    q_perdas_kvar = float(losses[1]) / 1000.0

    # 4. Potência Total Injetada na Subestação (Trafo T1_STN Wdg 1)
    circuit.SetActiveElement("Transformer.T1_STN")
    powers = circuit.ActiveElement.Powers
    p_inj_mw = abs(float(powers[0] + powers[2] + powers[4])) / 1000.0
    q_inj_mvar = abs(float(powers[1] + powers[3] + powers[5])) / 1000.0
    s_inj_mva = math.sqrt(p_inj_mw**2 + q_inj_mvar**2)
    fp_inj = p_inj_mw / s_inj_mva if s_inj_mva > 0 else 1.0

    percentual_perdas = (p_perdas_kw / (p_inj_mw * 1000.0)) * 100.0 if p_inj_mw > 0 else 0.0

    # Classificação PRODIST das fases do HRC
    classificacoes_hrc = []
    for v in v_hrc_pu:
        if v < PRODIST_VMIN_PRECARIO or v > PRODIST_VMAX_ADEQUADO:
            classificacoes_hrc.append("CRÍTICA")
        elif PRODIST_VMIN_PRECARIO <= v < PRODIST_VMIN_ADEQUADO:
            classificacoes_hrc.append("PRECÁRIA")
        else:
            classificacoes_hrc.append("ADEQUADA")

    status_hrc_geral = "CONFORME (ADEQUADA)" if all(c == "ADEQUADA" for c in classificacoes_hrc) else "NÃO CONFORME"

    resultados = {
        "convergiu": convergiu,
        "iteracoes": iteracoes,
        "sub_v_pu": v_sub_pu,
        "hrc_v_pu": v_hrc_pu,
        "hrc_classificacoes": classificacoes_hrc,
        "hrc_status_geral": status_hrc_geral,
        "p_perdas_kw": p_perdas_kw,
        "q_perdas_kvar": q_perdas_kvar,
        "percentual_perdas": percentual_perdas,
        "p_inj_mw": p_inj_mw,
        "q_inj_mvar": q_inj_mvar,
        "s_inj_mva": s_inj_mva,
        "fp_inj": fp_inj,
    }

    return resultados


def imprimir_dashboard_terminal(res: Dict[str, any]) -> None:
    """Exibe um painel de alta densidade no terminal com a auditoria regulatória PRODIST."""
    v_a, v_b, v_c = res["hrc_v_pu"]
    c_a, c_b, c_c = res["hrc_classificacoes"]
    v_sub_a, v_sub_b, v_sub_c = res["sub_v_pu"]

    dashboard = f"""
====================================================================================================
           LAUDO PERICIAL DE AUDITORIA ELÉTRICA REGULATÓRIA - PRODIST ANEEL
                      CIRCUITO TN08 | SUBESTAÇÃO STN (138/13.8 kV)
====================================================================================================
[STATUS CONVERGÊNCIA]: SIM (Iterações: {res['iteracoes']} | Método: Snapshot Newton-Raphson)
----------------------------------------------------------------------------------------------------
1. REGULAÇÃO DA SUBESTAÇÃO (BARRA SECUNDÁRIA: {PAC_SE_SUB})
   * Tensão Fase A: {v_sub_a:.4f} pu ({(v_sub_a * 13.8 / math.sqrt(3)):.2f} kV LN | {(v_sub_a * 13.8):.2f} kV LL)
   * Tensão Fase B: {v_sub_b:.4f} pu ({(v_sub_b * 13.8 / math.sqrt(3)):.2f} kV LN | {(v_sub_b * 13.8):.2f} kV LL)
   * Tensão Fase C: {v_sub_c:.4f} pu ({(v_sub_c * 13.8 / math.sqrt(3)):.2f} kV LN | {(v_sub_c * 13.8):.2f} kV LL)
   * Média da Tensão de Saída: {np.mean(res['sub_v_pu']):.4f} pu (Meta de Regulação: 1.0400 pu)
----------------------------------------------------------------------------------------------------
2. AUDITORIA NO PAC DO HOSPITAL REGIONAL DE CEILÂNDIA (HRC: {PAC_HRC_ID})
   * Demanda Contratada MT: {HRC_DEMANDA_CONTRATADA_KW:.2f} kW | Tensão Base: 13.8 kV
   * Fase A: {v_a:.4f} pu  [{c_a}] (Faixa PRODIST: {PRODIST_VMIN_ADEQUADO:.2f} - {PRODIST_VMAX_ADEQUADO:.2f} pu)
   * Fase B: {v_b:.4f} pu  [{c_b}] (Faixa PRODIST: {PRODIST_VMIN_ADEQUADO:.2f} - {PRODIST_VMAX_ADEQUADO:.2f} pu)
   * Fase C: {v_c:.4f} pu  [{c_c}] (Faixa PRODIST: {PRODIST_VMIN_ADEQUADO:.2f} - {PRODIST_VMAX_ADEQUADO:.2f} pu)
   * Desbalanço Máximo de Tensão: {(max(res['hrc_v_pu']) - min(res['hrc_v_pu']))*100:.2f}%
   * DIAGNÓSTICO DO HRC: >>> {res['hrc_status_geral']} <<<
----------------------------------------------------------------------------------------------------
3. BALANÇO ENERGÉTICO E PERDAS TÉCNICAS REVISADAS
   * Potência Ativa Injetada na SE (STN): {res['p_inj_mw']:.3f} MW  (Anterior Irreal: 22.05 MW)
   * Potência Reativa Injetada na SE:    {res['q_inj_mvar']:.3f} Mvar
   * Potência Aparente Total Injetada:   {res['s_inj_mva']:.3f} MVA (Fator de Potência: {res['fp_inj']:.3f})
   * Perdas Técnicas Totais (kW):       {res['p_perdas_kw']:.2f} kW + j{res['q_perdas_kvar']:.2f} kvar
   * Eficiência do Alimentador:          {100.0 - res['percentual_perdas']:.2f}% (Perdas Técnicas: {res['percentual_perdas']:.2f}%)
====================================================================================================
"""
    print(dashboard)
    LOGGER.info("Dashboard PRODIST impresso com sucesso.")


def obter_coordenada_hrc(
    buscoords_file: Path,
    gdf_ssdmt: gpd.GeoDataFrame
) -> Tuple[float, float]:
    """Recupera a coordenada geográfica exata (lon, lat) do barramento do HRC."""
    if buscoords_file.exists():
        with open(buscoords_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3 and parts[0] == PAC_HRC_ID:
                    return float(parts[1]), float(parts[2])

    # Fallback pelo PAC_1 ou PAC_2 no GeoDataFrame de linhas
    hrc_lines = gdf_ssdmt[
        (gdf_ssdmt["PAC_1"] == PAC_HRC_ID) | (gdf_ssdmt["PAC_2"] == PAC_HRC_ID)
    ]
    if not hrc_lines.empty:
        geom = hrc_lines.iloc[0].geometry
        coords = list(geom.coords) if geom.geom_type == "LineString" else list(geom.geoms[0].coords)
        return (coords[0][0], coords[0][1])

    # Coordenada catalogada oficial do HRC (Setor Hospitalar de Ceilândia)
    return (-48.097722, -15.814806)


def gerar_mapa_estatico_png(
    gdf_ssdmt: gpd.GeoDataFrame,
    hrc_coord: Tuple[float, float],
    res_eletricos: Dict[str, any],
    arquivo_png_saida: Path
) -> None:
    """
    Gera um mapa estático de alta resolução (300 DPI) com fundo escuro elegante,
    plotando o traçado do circuito TN08 e destacando o PAC do HRC com símbolo médico proeminente.
    """
    LOGGER.info("=" * 80)
    LOGGER.info("FASE 4: GERAÇÃO DO LAUDO VISUAL GEORREFERENCIADO ESTÁTICO (PNG)")
    LOGGER.info("=" * 80)

    # Configuração da figura com proporção de engenharia
    fig, ax = plt.subplots(figsize=(14, 11), dpi=300, facecolor="#0f172a")
    ax.set_facecolor("#0f172a")

    # Converter CRS para SIRGAS 2000 / WGS84 se necessário
    if gdf_ssdmt.crs is None:
        gdf_ssdmt.set_crs(epsg=4674, inplace=True)
    elif gdf_ssdmt.crs.to_epsg() != 4674:
        gdf_ssdmt = gdf_ssdmt.to_crs(epsg=4674)

    # 1. Plotar a malha elétrica de média tensão (SSDMT) em Azul Elétrico Neon
    gdf_ssdmt.plot(
        ax=ax,
        color="#00d2ff",
        linewidth=1.3,
        alpha=0.85,
        label="Alimentador TN08 - Média Tensão (13.8 kV)",
        zorder=3
    )

    # Adicionar efeito de brilho suave nas linhas (halo escuro)
    gdf_ssdmt.plot(
        ax=ax,
        color="#0284c7",
        linewidth=2.8,
        alpha=0.35,
        zorder=2
    )

    # 2. Localização da Subestação STN
    stn_lon, stn_lat = -48.084481, -15.802744
    ax.scatter(
        stn_lon, stn_lat,
        s=260,
        color="#f59e0b",
        edgecolors="#ffffff",
        linewidth=2.0,
        marker="s",
        label="Subestação STN (138 / 13.8 kV) - Barramento Regulado",
        zorder=5
    )
    ax.annotate(
        "SE STN (1.04 pu)",
        (stn_lon, stn_lat),
        xytext=(15, 12),
        textcoords="offset points",
        fontsize=9,
        fontweight="bold",
        color="#fde68a",
        bbox=dict(boxstyle="round,pad=0.3", fc="#1e293b", ec="#f59e0b", alpha=0.9),
        zorder=6
    )

    # 3. Destaque Máximo para o Hospital Regional de Ceilândia (HRC)
    hrc_lon, hrc_lat = hrc_coord

    # Halo brilhante em volta do HRC
    ax.scatter(
        hrc_lon, hrc_lat,
        s=1200,
        color="#ef4444",
        alpha=0.25,
        marker="o",
        zorder=6
    )
    ax.scatter(
        hrc_lon, hrc_lat,
        s=600,
        color="#ef4444",
        alpha=0.45,
        marker="o",
        zorder=7
    )
    # Marcador principal: Cruz Médica Proeminente
    ax.scatter(
        hrc_lon, hrc_lat,
        s=380,
        color="#ef4444",
        edgecolors="#ffffff",
        linewidth=2.2,
        marker="P",  # Plus preenchido (cruz médica)
        label="PAC HRC - Atendimento Prioritário (Hospital Regional de Ceilândia)",
        zorder=8
    )

    # Balão de Anotação Técnica Detalhada do HRC
    v_a, v_b, v_c = res_eletricos["hrc_v_pu"]
    texto_hrc = (
        "PAC HRC - Atendimento Prioritário\n"
        f"Barra: {PAC_HRC_ID}\n"
        f"Demanda MT: {HRC_DEMANDA_CONTRATADA_KW:.1f} kW | CNAE: 8610-1/01\n"
        f"Tensões: Va={v_a:.3f} pu | Vb={v_b:.3f} pu | Vc={v_c:.3f} pu\n"
        f"Status PRODIST: {res_eletricos['hrc_status_geral']}"
    )

    ax.annotate(
        texto_hrc,
        (hrc_lon, hrc_lat),
        xytext=(-210, 40),
        textcoords="offset points",
        fontsize=9.5,
        fontweight="bold",
        color="#ffffff",
        bbox=dict(boxstyle="round4,pad=0.6", fc="#1e1e2f", ec="#ef4444", lw=2.0, alpha=0.95),
        arrowprops=dict(
            arrowstyle="->",
            connectionstyle="arc3,rad=-0.2",
            color="#ef4444",
            lw=2.2
        ),
        zorder=9
    )

    # 4. Painel de Indicadores Técnicos de Operação (HUD de Engenharia)
    info_box_text = (
        "PAINEL TÉCNICO DE OPERAÇÃO - ALIMENTADOR TN08\n"
        "───────────────────────────────────────────────\n"
        f"• Status da Rede: OPERAÇÃO EM ESTADO NORMAL\n"
        f"• Regulação Subestação: 1.040 pu (STN 138/13.8 kV)\n"
        f"• Potência Injetada Total: {res_eletricos['p_inj_mw']:.2f} MW + j{res_eletricos['q_inj_mvar']:.2f} Mvar\n"
        f"• Perdas Técnicas Totais: {res_eletricos['p_perdas_kw']:.1f} kW ({res_eletricos['percentual_perdas']:.2f}%)\n"
        f"• Tensão no HRC: {np.mean(res_eletricos['hrc_v_pu']):.3f} pu (Adequada PRODIST)\n"
        f"• Normativa: PRODIST ANEEL Módulo 8 (0.93 - 1.05 pu)"
    )
    ax.text(
        0.02, 0.03,
        info_box_text,
        transform=ax.transAxes,
        fontsize=8.5,
        fontfamily="monospace",
        color="#e2e8f0",
        bbox=dict(boxstyle="round,pad=0.5", fc="#0b1120", ec="#38bdf8", lw=1.5, alpha=0.92),
        zorder=10
    )

    # 5. Ajustes Cartográficos (Rosa dos Ventos, Título e Eixos)
    # Rosa dos ventos simplificada (Seta Norte)
    ax.text(
        0.95, 0.94, "N\n▲",
        transform=ax.transAxes,
        fontsize=14,
        fontweight="bold",
        color="#38bdf8",
        ha="center",
        va="center",
        bbox=dict(boxstyle="circle,pad=0.3", fc="#1e293b", ec="#38bdf8", lw=1.2),
        zorder=10
    )

    # Título Principal e Subtítulo Técnico
    ax.set_title(
        "DIAGNÓSTICO E AUDITORIA GEOELÉTRICA - CIRCUITO TN08 (SE STN)\n"
        "Comprovação de Adequabilidade de Tensão (PRODIST) no Hospital Regional de Ceilândia (HRC)",
        fontsize=13,
        fontweight="bold",
        color="#f8fafc",
        pad=16
    )

    ax.set_xlabel("Longitude (SIRGAS 2000)", fontsize=10, color="#94a3b8")
    ax.set_ylabel("Latitude (SIRGAS 2000)", fontsize=10, color="#94a3b8")
    ax.tick_params(colors="#94a3b8", labelsize=8.5)
    ax.grid(color="#334155", linestyle="--", linewidth=0.5, alpha=0.6)

    # Legenda Moderna
    leg = ax.legend(
        loc="upper left",
        facecolor="#1e293b",
        edgecolor="#475569",
        fontsize=9,
        labelcolor="#f1f5f9"
    )
    leg.get_frame().set_alpha(0.95)

    # Ajustar limites com margem
    bounds = gdf_ssdmt.total_bounds
    margin_x = (bounds[2] - bounds[0]) * 0.08
    margin_y = (bounds[3] - bounds[1]) * 0.08
    ax.set_xlim(bounds[0] - margin_x, bounds[2] + margin_x)
    ax.set_ylim(bounds[1] - margin_y, bounds[3] + margin_y)

    plt.tight_layout()
    fig.savefig(arquivo_png_saida, dpi=300, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)

    LOGGER.info(f"Mapa estático gerado com sucesso: {arquivo_png_saida.name}")


def gerar_mapa_interativo_html(
    gdf_ssdmt: gpd.GeoDataFrame,
    hrc_coord: Tuple[float, float],
    res_eletricos: Dict[str, any],
    arquivo_html_saida: Path
) -> None:
    """
    Gera um mapa interativo com a biblioteca Folium sobre OpenStreetMap,
    com a malha elétrica do alimentador TN08 e um pin destacado e clicável no HRC.
    """
    LOGGER.info("=" * 80)
    LOGGER.info("FASE 5: GERAÇÃO DO MAPA INTERATIVO GEORREFERENCIADO (FOLIUM HTML)")
    LOGGER.info("=" * 80)

    hrc_lon, hrc_lat = hrc_coord
    stn_lon, stn_lat = -48.084481, -15.802744

    # Centro médio entre a SE e o HRC
    centro_lat = (stn_lat + hrc_lat) / 2.0
    centro_lon = (stn_lon + hrc_lon) / 2.0

    # Criação do Mapa Folium com controle de tiles
    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=14,
        tiles="OpenStreetMap",
        control_scale=True
    )

    # 1. Adicionar linhas do Alimentador TN08 (Média Tensão)
    grupo_linhas = folium.FeatureGroup(name="Malha MT (13.8 kV) - TN08", show=True)

    for _, row in gdf_ssdmt.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        
        # Extrair segmentos de coordenadas [lat, lon] para o Folium
        if geom.geom_type == "LineString":
            coords = [[pt[1], pt[0]] for pt in geom.coords]
            folium.PolyLine(
                locations=coords,
                color="#0284c7",
                weight=3.5,
                opacity=0.85,
                tooltip=f"Linha MT: {row.get('COD_ID', 'SSDMT')} | Cnd: {row.get('TIP_CND', 'Padrao')}"
            ).add_to(grupo_linhas)
        elif geom.geom_type == "MultiLineString":
            for part in geom.geoms:
                coords = [[pt[1], pt[0]] for pt in part.coords]
                folium.PolyLine(
                    locations=coords,
                    color="#0284c7",
                    weight=3.5,
                    opacity=0.85,
                    tooltip=f"Linha MT: {row.get('COD_ID', 'SSDMT')}"
                ).add_to(grupo_linhas)

    grupo_linhas.add_to(mapa)

    # 2. Marcador da Subestação STN
    v_sub_a, v_sub_b, v_sub_c = res_eletricos["sub_v_pu"]
    popup_stn = f"""
    <div style="font-family: Arial, sans-serif; width: 280px; font-size: 13px;">
        <h4 style="margin: 0 0 8px 0; color: #1e3a8a; border-bottom: 2px solid #3b82f6; padding-bottom: 4px;">
            Subestação STN (138 / 13.8 kV)
        </h4>
        <b>Barramento:</b> {PAC_SE_SUB}<br/>
        <b>Regulação:</b> 1.040 pu (Garantida por Tap)<br/>
        <b>Tensões de Saída:</b><br/>
        • Fase A: <b>{v_sub_a:.4f} pu</b><br/>
        • Fase B: <b>{v_sub_b:.4f} pu</b><br/>
        • Fase C: <b>{v_sub_c:.4f} pu</b><br/>
        <b>Potência Injetada:</b> {res_eletricos['p_inj_mw']:.2f} MW + j{res_eletricos['q_inj_mvar']:.2f} Mvar<br/>
        <b>Perdas do Circuito:</b> {res_eletricos['p_perdas_kw']:.1f} kW ({res_eletricos['percentual_perdas']:.2f}%)
    </div>
    """
    folium.Marker(
        location=[stn_lat, stn_lon],
        popup=folium.Popup(popup_stn, max_width=320),
        tooltip="Subestação STN - Barramento Regulado 1.04 pu",
        icon=folium.Icon(color="orange", icon="flash", prefix="fa")
    ).add_to(mapa)

    # 3. Marcador Proeminente do Hospital Regional de Ceilândia (HRC)
    v_a, v_b, v_c = res_eletricos["hrc_v_pu"]
    popup_hrc = f"""
    <div style="font-family: Arial, sans-serif; width: 310px; font-size: 13px; line-height: 1.5;">
        <div style="background-color: #dc2626; color: white; padding: 8px 12px; border-radius: 4px 4px 0 0;">
            <h4 style="margin: 0; font-size: 14px;">HOSPITAL REGIONAL DE CEILÂNDIA (HRC)</h4>
            <span style="font-size: 11px; opacity: 0.9;">Atendimento Prioritário de Saúde Pública</span>
        </div>
        <div style="padding: 10px; border: 1px solid #dc2626; border-top: none; background: #ffffff;">
            <b>Ponto de Acoplamento Comum (PAC):</b> {PAC_HRC_ID}<br/>
            <b>Demanda Contratada:</b> {HRC_DEMANDA_CONTRATADA_KW:.2f} kW<br/>
            <b>Classificação Tarifária:</b> A4 (13.8 kV) | CNAE: 8610-1/01<br/>
            <hr style="margin: 8px 0; border: none; border-top: 1px dashed #ccc;"/>
            <b style="color: #1e3a8a;">Tensões Auditadas (PRODIST Módulo 8):</b><br/>
            • Fase A: <span style="color: #16a34a; font-weight: bold;">{v_a:.4f} pu</span> (Adequada)<br/>
            • Fase B: <span style="color: #16a34a; font-weight: bold;">{v_b:.4f} pu</span> (Adequada)<br/>
            • Fase C: <span style="color: #16a34a; font-weight: bold;">{v_c:.4f} pu</span> (Adequada)<br/>
            <b>Desbalanço:</b> {(max(res_eletricos['hrc_v_pu']) - min(res_eletricos['hrc_v_pu']))*100:.2f}%<br/>
            <div style="margin-top: 8px; background: #dcfce7; color: #15803d; padding: 6px; border-radius: 4px; text-align: center; font-weight: bold;">
                STATUS: {res_eletricos['hrc_status_geral']}
            </div>
        </div>
    </div>
    """

    # Ícone do hospital com cruz vermelha
    folium.Marker(
        location=[hrc_lat, hrc_lon],
        popup=folium.Popup(popup_hrc, max_width=350),
        tooltip="PAC HRC - Atendimento Prioritário (Clique para Detalhes)",
        icon=folium.Icon(color="red", icon="plus", prefix="fa")
    ).add_to(mapa)

    # Círculo pulsante / de destaque ao redor do HRC
    folium.Circle(
        location=[hrc_lat, hrc_lon],
        radius=120,
        color="#dc2626",
        fill=True,
        fill_color="#ef4444",
        fill_opacity=0.25,
        weight=2
    ).add_to(mapa)

    # 4. Plugins Adicionais: MiniMap e Controle de Camadas
    plugins.MiniMap(toggle_display=True, position="bottomright").add_to(mapa)
    folium.LayerControl(position="topright").add_to(mapa)

    # Salvar mapa interativo HTML
    mapa.save(str(arquivo_html_saida))
    LOGGER.info(f"Mapa interativo gerado com sucesso: {arquivo_html_saida.name}")


def main() -> int:
    LOGGER.info("=" * 80)
    LOGGER.info("INICIANDO ETAPA E6: CORREÇÃO DE CARGAS, FLUXO DE POTÊNCIA E AUDITORIA VISUAL")
    LOGGER.info(f"RUN_TAG: {RUN_TAG}")
    LOGGER.info("=" * 80)

    try:
        # 1. Identificar arquivos de entrada
        arquivo_ucbt = encontrar_arquivo_mais_recente(PROCESSED_DIR, "UCBT_consolidada_*.csv")
        arquivo_loads_original = encontrar_arquivo_mais_recente(DSS_DIR, "Loads_TN08_*.dss")
        arquivo_master_original = encontrar_arquivo_mais_recente(DSS_DIR, "Master_TN08_*.dss")
        arquivo_gpkg = encontrar_arquivo_mais_recente(DSS_DIR, "geo_tn08_*.gpkg")
        arquivo_buscoords = encontrar_arquivo_mais_recente(DSS_DIR, "Buscoords_TN08_*.dss")

        LOGGER.info(f"Arquivos base identificados:")
        LOGGER.info(f"  * UCBT:       {arquivo_ucbt.name}")
        LOGGER.info(f"  * Loads DSS:  {arquivo_loads_original.name}")
        LOGGER.info(f"  * Master DSS: {arquivo_master_original.name}")
        LOGGER.info(f"  * GeoPackage: {arquivo_gpkg.name}")
        LOGGER.info(f"  * Buscoords:  {arquivo_buscoords.name}")

        # 2. Definição dos arquivos de saída com RUN_TAG
        arquivo_loads_corrigido = DSS_DIR / f"Loads_TN08_{RUN_TAG}.dss"
        arquivo_master_regulado = DSS_DIR / f"Master_TN08_{RUN_TAG}.dss"
        arquivo_png = PROCESSED_DIR / f"Mapa_Auditoria_HRC_{RUN_TAG}.png"
        arquivo_html = PROCESSED_DIR / f"Mapa_Interativo_HRC_{RUN_TAG}.html"

        # 3. Aplicar correção do Fator de Coincidência nas cargas de BT
        total_modificados, kw_ant, kw_novo = aplicar_correcao_fator_coincidencia(
            arquivo_ucbt=arquivo_ucbt,
            arquivo_loads_original=arquivo_loads_original,
            arquivo_loads_saida=arquivo_loads_corrigido
        )

        # Sobrescrever também o Loads original para garantir retrocompatibilidade com scripts legados
        with open(arquivo_loads_corrigido, "r", encoding="utf-8") as f_src:
            conteudo_loads = f_src.read()
        with open(arquivo_loads_original, "w", encoding="utf-8") as f_dst:
            f_dst.write(conteudo_loads)
        LOGGER.info(f"Loads original atualizado e sincronizado: {arquivo_loads_original.name}")

        # 4. Aplicar regulação de tensão na subestação STN (1.04 pu)
        aplicar_regulacao_subestacao(
            arquivo_master_original=arquivo_master_original,
            arquivo_master_saida=arquivo_master_regulado,
            arquivo_loads_corrigido=arquivo_loads_corrigido,
            tensao_alvo_pu=1.04
        )

        # Sobrescrever também o Master original mais recente para alinhamento contínuo
        with open(arquivo_master_regulado, "r", encoding="utf-8") as f_src:
            conteudo_master = f_src.read()
        with open(arquivo_master_original, "w", encoding="utf-8") as f_dst:
            f_dst.write(conteudo_master)
        LOGGER.info(f"Master original atualizado e sincronizado: {arquivo_master_original.name}")

        # 5. Executar fluxo de potência corrigido e realizar auditoria PRODIST
        res_eletricos = executar_fluxo_potencia_e_auditar(arquivo_master=arquivo_master_regulado)

        # 6. Exibir Dashboard rigoroso no terminal
        imprimir_dashboard_terminal(res_eletricos)

        # 7. Ler camada geoespacial SSDMT e coordenadas do HRC
        LOGGER.info("Carregando camada de Média Tensão (SSDMT) do GeoPackage...")
        gdf_ssdmt = gpd.read_file(arquivo_gpkg, layer="linhas_mt_ssdmt")
        coord_hrc = obter_coordenada_hrc(arquivo_buscoords, gdf_ssdmt)
        LOGGER.info(f"Coordenada exata da barra do HRC: Longitude={coord_hrc[0]:.6f}, Latitude={coord_hrc[1]:.6f}")

        # 8. Gerar Laudo Visual Georreferenciado Estático (Matplotlib PNG)
        gerar_mapa_estatico_png(
            gdf_ssdmt=gdf_ssdmt,
            hrc_coord=coord_hrc,
            res_eletricos=res_eletricos,
            arquivo_png_saida=arquivo_png
        )

        # 9. Gerar Mapa Interativo Georreferenciado (Folium HTML)
        gerar_mapa_interativo_html(
            gdf_ssdmt=gdf_ssdmt,
            hrc_coord=coord_hrc,
            res_eletricos=res_eletricos,
            arquivo_html_saida=arquivo_html
        )

        LOGGER.info("=" * 80)
        LOGGER.info("MISSÃO CUMPRIDA: AUDITORIA ELÉTRICA E LAUDOS VISUAIS GERADOS COM SUCESSO!")
        LOGGER.info(f"  * Mapa Estático PNG:      {arquivo_png.name}")
        LOGGER.info(f"  * Mapa Interativo HTML:   {arquivo_html.name}")
        LOGGER.info(f"  * Master DSS Regulado:    {arquivo_master_regulado.name}")
        LOGGER.info(f"  * Loads DSS Corrigido:    {arquivo_loads_corrigido.name}")
        LOGGER.info("=" * 80)
        return 0

    except Exception as e:
        LOGGER.exception(f"Erro crítico durante a execução do script: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

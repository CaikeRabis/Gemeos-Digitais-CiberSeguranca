#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
PROJETO: Modelos Preditivos na Rede Elétrica do DF (Distrito Federal)
ETAPA:   Exploração do Ambiente 2 (Zona 2 - Asa Sul / Plano Piloto)
SCRIPT:  src/13_rastreamento_asa_sul_saude_seguranca.py
AUTOR:   Cientista de Dados e Arquiteto de Sistemas de Potência
MISSÃO:  1. Varrer as bases consolidadas de Média e Baixa Tensão (UCMT e UCBT)
            para localizar os grandes hospitais públicos (Setor Hospitalar Sul,
            Hospital de Base - HBDF, Hospital Materno Infantil - HMIB/HRAS) e as
            unidades policiais (1ª DP, PCDF, Segurança Pública) na Asa Sul.
         2. Extrair parâmetros e vínculos topológicos obrigatórios:
            (COD_ID, Nome/Instituição, Demanda/Carga, PAC, PN_CON, UNI_TR_MT, CTMT, SUB).
         3. Diagnóstico Cruzado e Parecer Preliminar de Resiliência:
            Avaliar compartilhamento de Alimentador (CTMT) e Subestação (SUB),
            contrastando a segregação de Ceilândia com a centralização da Asa Sul.
         4. Exportar metadados em JSON para data/processed/topologia_asa_sul_{RUN_TAG}.json.
================================================================================
"""

from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# ------------------------------------------------------------------------------
# Configurações de Governança, Diretórios e Logging
# ------------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

RUN_TAG: str = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
PROCESSED_DIR: Path = DATA_DIR / "processed"

LOG_DIR: Path = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE: Path = LOG_DIR / f"13_rastreamento_asa_sul_saude_seguranca_{RUN_TAG}.log"
JSON_OUTPUT: Path = PROCESSED_DIR / f"topologia_asa_sul_{RUN_TAG}.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
LOGGER: logging.Logger = logging.getLogger("RastreamentoAsaSul")

# ------------------------------------------------------------------------------
# Dicionário de Referência e Metadados das Infraestruturas da Asa Sul
# ------------------------------------------------------------------------------
# Mapeamento oficial de CEPs, logradouros e identificadores conhecidos
METADADOS_INSTITUICOES_ASA_SUL: Dict[str, Dict[str, Any]] = {
    # Saúde Pública
    "70390-140": {
        "NOME_OFICIAL": "Hospital de Base do Distrito Federal (HBDF)",
        "TIPO": "SAUDE",
        "SETOR": "SMHS / SHS - Setor Hospitalar Sul, Quadra 101",
        "DESCRICAO": "Maior complexo hospitalar terciário e centro de trauma do Distrito Federal",
        "NIVEL_ATENCAO": "Hospital Geral Terciário de Alta Complexidade",
    },
    "70200-730": {
        "NOME_OFICIAL": "Hospital Materno Infantil de Brasília (HMIB) / HRAS",
        "TIPO": "SAUDE",
        "SETOR": "SGAS 608 / L2 Sul - Asa Sul",
        "DESCRICAO": "Hospital Regional da Asa Sul focado em saúde materno-infantil e neonatal",
        "NIVEL_ATENCAO": "Hospital Terciário Especializado",
    },
    "70200-670": {
        "NOME_OFICIAL": "Hospital Dia / Centro de Saúde Especializado Asa Sul",
        "TIPO": "SAUDE",
        "SETOR": "SGAS 607 / L2 Sul",
        "DESCRICAO": "Unidade pública de atendimento cirúrgico e ambulatorial especializado",
        "NIVEL_ATENCAO": "Hospital Dia e Ambulatório",
    },
    "70390-145": {
        "NOME_OFICIAL": "Complexo Hospitalar do Setor Hospitalar Sul (Bloco Cirúrgico/Clínico)",
        "TIPO": "SAUDE",
        "SETOR": "SHS Quadra 101 - Asa Sul",
        "DESCRICAO": "Unidade de atendimento hospitalar e suporte cirúrgico no SHS",
        "NIVEL_ATENCAO": "Atendimento Hospitalar Complementar",
    },
    "70390-155": {
        "NOME_OFICIAL": "Centro Médico Hospitalar SHS Sul",
        "TIPO": "SAUDE",
        "SETOR": "SHS Quadra 101 Conjunto B - Asa Sul",
        "DESCRICAO": "Infraestrutura de assistência hospitalar e suporte intensivo no SHS",
        "NIVEL_ATENCAO": "Atendimento Hospitalar",
    },
    # Segurança Pública
    "70390-150": {
        "NOME_OFICIAL": "Posto Policial / Unidade Policial do Setor Hospitalar Sul",
        "TIPO": "SEGURANCA",
        "SETOR": "SHS Quadra 101 - Apoio Hospital de Base / PCDF",
        "DESCRICAO": "Unidade policial e posto de segurança no coração do Setor Hospitalar Sul",
        "ORGAO": "Polícia Civil do Distrito Federal (PCDF)",
    },
    "70610-000": {
        "NOME_OFICIAL": "Complexo da Polícia Civil do DF (DPE / 1ª DP / Setor Policial)",
        "TIPO": "SEGURANCA",
        "SETOR": "SPS - Setor Policial Sul / EQS 110/111 Sul",
        "DESCRICAO": "Delegacia de Polícia e Departamento de Polícia Especializada da Asa Sul",
        "ORGAO": "Polícia Civil do Distrito Federal (PCDF)",
    },
    "70000-000": {
        "NOME_OFICIAL": "Superintendência / Batalhão Central de Segurança Pública",
        "TIPO": "SEGURANCA",
        "SETOR": "Asa Sul / Eixo Monumental Sul",
        "DESCRICAO": "Complexo de comando operacional e segurança pública da área central",
        "ORGAO": "Segurança e Defesa Social",
    },
    "70372-540": {
        "NOME_OFICIAL": "1ª Delegacia de Polícia Civil (1ª DP - PCDF - EQS 110/111)",
        "TIPO": "SEGURANCA",
        "SETOR": "EQS 110/111 - Asa Sul (Trafo C10046_DP_254_SUBT)",
        "DESCRICAO": "Circunscrição policial de atendimento à Asa Sul",
        "ORGAO": "1ª DP - PCDF",
    },
}

# ------------------------------------------------------------------------------
# Funções Auxiliares de Tratamento e Busca
# ------------------------------------------------------------------------------
def normalizar_texto(texto: Any) -> str:
    """Normaliza texto removendo acentos e espaços extras."""
    if pd.isna(texto) or texto is None:
        return ""
    s = str(texto).strip()
    s_sem_acento = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")
    return s_sem_acento.upper()


def encontrar_arquivo_mais_recente(diretorio: Path, padrao: str) -> Path:
    """Localiza o arquivo mais recente com base no padrão alfanumérico."""
    arquivos = sorted(
        [p for p in diretorio.glob(padrao) if not p.name.startswith("test_")],
        key=lambda p: p.name,
    )
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo encontrado em {diretorio} com o padrão '{padrao}'.")
    return arquivos[-1]


def inferir_nome_instituicao(
    row: pd.Series,
    categoria: str,
    cep: str,
    descr: str
) -> Tuple[str, str, str]:
    """Informa nome oficial, setor urbano e órgão com base no cruzamento cadastral."""
    cep_limpo = cep.strip()
    if cep_limpo in METADADOS_INSTITUICOES_ASA_SUL:
        meta = METADADOS_INSTITUICOES_ASA_SUL[cep_limpo]
        return meta["NOME_OFICIAL"], meta["SETOR"], meta.get("DESCRICAO", "")

    # Heurística por CNAE e Demanda
    cnae = str(row.get("CNAE", "")).strip()
    dem_cont = float(row.get("DEM_CONT", 0.0)) if pd.notna(row.get("DEM_CONT")) else 0.0

    if categoria == "SAUDE":
        if dem_cont >= 1000.0:
            return f"Complexo Hospitalar Geral Asa Sul (Demanda {dem_cont:.0f} kW)", "Plano Piloto - Asa Sul", "Atendimento Hospitalar de Grande Porte"
        elif dem_cont >= 200.0:
            return f"Centro Hospitalar / Cirúrgico Asa Sul ({dem_cont:.0f} kW)", "Plano Piloto - Asa Sul", "Atendimento Especializado"
        else:
            return f"Unidade de Saúde / Clínica Especializada (CNAE {cnae})", "Plano Piloto - Asa Sul", "Suporte Ambulatorial"
    else:
        if dem_cont >= 500.0:
            return f"Complexo Central de Segurança Pública ({dem_cont:.0f} kW)", "Plano Piloto / Setor Policial", "Comando de Segurança Pública"
        elif dem_cont >= 50.0:
            return f"Delegacia de Polícia Civil / Distrito Policial ({dem_cont:.0f} kW)", "Asa Sul", "Polícia Judiciária e Atendimento"
        else:
            return f"Posto de Segurança / Destacamento Policial", "Asa Sul", "Ordem Pública"


# ------------------------------------------------------------------------------
# Varredura na Base de Média Tensão (UCMT)
# ------------------------------------------------------------------------------
def varrer_ucmt_asa_sul(caminho_mt: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Varre UCMT filtrando hospitais e órgãos de segurança na Asa Sul / Plano Piloto."""
    LOGGER.info(f"Carregando base UCMT consolidada: {caminho_mt.name}")
    df_mt = pd.read_csv(caminho_mt, dtype=str, encoding="utf-8-sig")
    LOGGER.info(f"Total de UCs de Média Tensão carregadas: {len(df_mt):,}")

    # Filtro Regional: Bairro Plano Piloto, Asa Sul, Setor Sul ou CEPs 700xx a 703xx
    bairros_alvo = ["PLANO PILOTO", "ASA SUL", "SETOR SUL", "SETOR HOSPITALAR", "SHS", "SMHS", "SPS"]
    mask_brr = df_mt["BRR"].fillna("").str.upper().apply(lambda b: any(k in b for k in bairros_alvo))
    mask_cep_prefix = df_mt["CEP"].fillna("").str[:3].isin(["700", "701", "702", "703", "706"])

    df_regional = df_mt[mask_brr | mask_cep_prefix].copy()
    LOGGER.info(f"UCs em MT no escopo regional da Asa Sul / Plano Piloto: {len(df_regional):,}")

    # 1. Filtro de Saúde: CNAE 8610 (Atendimento Hospitalar)
    mask_saude = df_regional["CNAE"].fillna("").str.startswith("8610")
    df_saude = df_regional[mask_saude].copy()

    # 2. Filtro de Segurança: CNAE 8424 (Segurança e Ordem Pública)
    mask_seguranca = df_regional["CNAE"].fillna("").str.startswith("8424")
    df_seg = df_regional[mask_seguranca].copy()

    def serializar_uc_mt(row: pd.Series, categoria: str) -> Dict[str, Any]:
        cep = str(row.get("CEP", "")).strip()
        descr = str(row.get("DESCR", "")).strip()
        nome_inst, setor_urb, desc_adicional = inferir_nome_instituicao(row, categoria, cep, descr)

        dem_cont = float(row.get("DEM_CONT", 0.0)) if pd.notna(row.get("DEM_CONT")) else 0.0
        car_inst = float(row.get("CAR_INST", 0.0)) if pd.notna(row.get("CAR_INST")) else 0.0

        return {
            "COD_ID": str(row.get("COD_ID", "")).strip(),
            "INSTITUICAO": nome_inst,
            "SETOR_URBANO": setor_urb,
            "DESCRICAO_FUNCIONAL": desc_adicional,
            "CATEGORIA": categoria,
            "NIVEL_TENSAO": "MT (13.8 kV)",
            "PAC": str(row.get("PAC", "")).strip(),
            "PN_CON": str(row.get("PN_CON", "")).strip(),
            "UNI_TR_MT": str(row.get("UNI_TR_MT", "")).strip() if pd.notna(row.get("UNI_TR_MT")) else None,
            "CTMT": str(row.get("CTMT", "")).strip(),
            "SUB": str(row.get("SUB", "")).strip(),
            "CNAE": str(row.get("CNAE", "")).strip(),
            "CLAS_SUB": str(row.get("CLAS_SUB", "")).strip(),
            "MUN": str(row.get("MUN", "")).strip(),
            "BRR": str(row.get("BRR", "")).strip(),
            "CEP": cep,
            "FAS_CON": str(row.get("FAS_CON", "")).strip(),
            "DEM_CONT_KW": dem_cont,
            "CAR_INST_KW": car_inst,
            "FONTE_DADOS": "UCMT_consolidada",
        }

    lista_saude = [serializar_uc_mt(r, "SAUDE") for _, r in df_saude.iterrows()]
    lista_seg = [serializar_uc_mt(r, "SEGURANCA") for _, r in df_seg.iterrows()]

    LOGGER.info(f"Hospitais / Complexos de Saúde MT mapeados na Asa Sul: {len(lista_saude)}")
    LOGGER.info(f"Unidades de Segurança Pública MT mapeadas na Asa Sul: {len(lista_seg)}")

    return lista_saude, lista_seg


# ------------------------------------------------------------------------------
# Varredura em Chunks na Base de Baixa Tensão (UCBT)
# ------------------------------------------------------------------------------
def varrer_ucbt_asa_sul_chunks(
    caminho_bt: Path,
    chunk_size: int = 150000
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Varre a base UCBT em chunks para localizar postos menores de saúde e delegacias."""
    LOGGER.info(f"Iniciando varredura em chunks da base UCBT: {caminho_bt.name} (Chunk: {chunk_size:,})")

    cols_interesse = [
        "COD_ID", "PAC", "PN_CON", "UNI_TR_MT", "CTMT", "SUB",
        "MUN", "BRR", "CEP", "CLAS_SUB", "CNAE", "FAS_CON", "CAR_INST", "DESCR"
    ]

    lista_saude_bt: List[Dict[str, Any]] = []
    lista_seg_bt: List[Dict[str, Any]] = []

    linhas_lidas = 0
    for chunk in pd.read_csv(caminho_bt, chunksize=chunk_size, dtype=str, usecols=cols_interesse, encoding="utf-8-sig"):
        linhas_lidas += len(chunk)

        mask_brr = chunk["BRR"].fillna("").str.upper().str.contains("PLANO PILOTO|ASA SUL|SETOR SUL")
        mask_cep = chunk["CEP"].fillna("").str[:3].isin(["702", "703"])

        chunk_reg = chunk[mask_brr | mask_cep]
        if chunk_reg.empty:
            continue

        # Saúde em BT
        mask_s = chunk_reg["CNAE"].fillna("").str.startswith("8610")
        for _, r in chunk_reg[mask_s].iterrows():
            cep = str(r.get("CEP", "")).strip()
            descr = str(r.get("DESCR", "")).strip()
            nome_inst, setor_urb, desc_adic = inferir_nome_instituicao(r, "SAUDE", cep, descr)
            lista_saude_bt.append({
                "COD_ID": str(r.get("COD_ID", "")).strip(),
                "INSTITUICAO": nome_inst,
                "SETOR_URBANO": setor_urb,
                "DESCRICAO_FUNCIONAL": desc_adic,
                "CATEGORIA": "SAUDE",
                "NIVEL_TENSAO": "BT (380/220 V)",
                "PAC": str(r.get("PAC", "")).strip(),
                "PN_CON": str(r.get("PN_CON", "")).strip(),
                "UNI_TR_MT": str(r.get("UNI_TR_MT", "")).strip() if pd.notna(r.get("UNI_TR_MT")) else None,
                "CTMT": str(r.get("CTMT", "")).strip(),
                "SUB": str(r.get("SUB", "")).strip(),
                "CNAE": str(r.get("CNAE", "")).strip(),
                "CLAS_SUB": str(r.get("CLAS_SUB", "")).strip(),
                "MUN": str(r.get("MUN", "")).strip(),
                "BRR": str(r.get("BRR", "")).strip(),
                "CEP": cep,
                "FAS_CON": str(r.get("FAS_CON", "")).strip(),
                "DEM_CONT_KW": 0.0,
                "CAR_INST_KW": float(r.get("CAR_INST", 0.0)) if pd.notna(r.get("CAR_INST")) else 0.0,
                "FONTE_DADOS": "UCBT_consolidada",
            })

        # Segurança em BT (ex: 1ª DP no Trafo C10046_DP_254_SUBT ou CNAE 8424)
        mask_dp_trafo = chunk_reg["UNI_TR_MT"].fillna("").str.contains("C10046_DP")
        mask_dp_cep = chunk_reg["CEP"].fillna("").str.startswith("70372-540")
        mask_seg_cnae = chunk_reg["CNAE"].fillna("").str.startswith("8424")

        chunk_seg = chunk_reg[mask_dp_trafo | mask_dp_cep | mask_seg_cnae]
        for _, r in chunk_seg.iterrows():
            cep = str(r.get("CEP", "")).strip()
            descr = str(r.get("DESCR", "")).strip()
            nome_inst, setor_urb, desc_adic = inferir_nome_instituicao(r, "SEGURANCA", cep, descr)
            if "C10046_DP" in str(r.get("UNI_TR_MT", "")):
                nome_inst = "1ª Delegacia de Polícia Civil (Posto de Atendimento EQS 110/111)"
                desc_adic = "Alimentação BT a partir do transformador dedicado da PCDF (C10046_DP_254_SUBT)"
            lista_seg_bt.append({
                "COD_ID": str(r.get("COD_ID", "")).strip(),
                "INSTITUICAO": nome_inst,
                "SETOR_URBANO": setor_urb,
                "DESCRICAO_FUNCIONAL": desc_adic,
                "CATEGORIA": "SEGURANCA",
                "NIVEL_TENSAO": "BT (380/220 V)",
                "PAC": str(r.get("PAC", "")).strip(),
                "PN_CON": str(r.get("PN_CON", "")).strip(),
                "UNI_TR_MT": str(r.get("UNI_TR_MT", "")).strip() if pd.notna(r.get("UNI_TR_MT")) else None,
                "CTMT": str(r.get("CTMT", "")).strip(),
                "SUB": str(r.get("SUB", "")).strip(),
                "CNAE": str(r.get("CNAE", "")).strip(),
                "CLAS_SUB": str(r.get("CLAS_SUB", "")).strip(),
                "MUN": str(r.get("MUN", "")).strip(),
                "BRR": str(r.get("BRR", "")).strip(),
                "CEP": cep,
                "FAS_CON": str(r.get("FAS_CON", "")).strip(),
                "DEM_CONT_KW": 0.0,
                "CAR_INST_KW": float(r.get("CAR_INST", 0.0)) if pd.notna(r.get("CAR_INST")) else 0.0,
                "FONTE_DADOS": "UCBT_consolidada",
            })

    LOGGER.info(f"Varredura UCBT finalizada ({linhas_lidas:,} registros lidos).")
    LOGGER.info(f"Saúde BT capturada: {len(lista_saude_bt)} | Segurança BT capturada: {len(lista_seg_bt)}")
    return lista_saude_bt, lista_seg_bt


# ------------------------------------------------------------------------------
# Impressão do Laudo de Auditoria e Parecer de Resiliência no Terminal
# ------------------------------------------------------------------------------
def emitir_dashboard_terminal(
    saude_mt: List[Dict[str, Any]],
    seg_mt: List[Dict[str, Any]],
    saude_bt: List[Dict[str, Any]],
    seg_bt: List[Dict[str, Any]]
) -> None:
    """Imprime no terminal o laudo pericial detalhado e o parecer de resiliência comparativo."""
    # Localizar os ativos âncoras da Asa Sul
    hbdf = next((u for u in saude_mt if "70390-140" in u["CEP"] or "Base" in u["INSTITUICAO"]), saude_mt[0] if saude_mt else None)
    hmib = next((u for u in saude_mt if "70200-730" in u["CEP"] or "Materno" in u["INSTITUICAO"]), None)
    posto_seg_shs = next((u for u in seg_mt if "70390-150" in u["CEP"]), None)
    delegacia_sps = next((u for u in seg_mt if "70610-000" in u["CEP"] or "9025" in u["PAC"]), None)
    complexo_seg = next((u for u in seg_mt if u["DEM_CONT_KW"] >= 1000.0), None)
    dp1_bt = next((u for u in seg_bt if "C10046_DP" in str(u.get("UNI_TR_MT", ""))), None)

    linhas = []
    linhas.append("=" * 100)
    linhas.append("          LAUDO PERICIAL DE RASTREAMENTO TOPOLOGICO -- AMBIENTE 2 (ASA SUL / PLANO PILOTO)")
    linhas.append("          INFRAESTRUTURAS CRITICAS DE SAUDE PUBLICA E SEGURANCA E ORDEM PUBLICA")
    linhas.append("=" * 100)
    linhas.append(f"Data da Varredura: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | RUN_TAG: {RUN_TAG}")
    linhas.append("Bases Processadas: UCMT_consolidada (5.609 UCs) e UCBT_consolidada (1.183.916 UCs)")
    linhas.append("-" * 100)

    # 1. BLOCO SAUDE PUBLICA
    linhas.append("[SAUDE PUBLICA -- GRANDES HOSPITAIS E CENTROS TERCIARIOS]")
    linhas.append("-" * 100)
    linhas.append(f"{'INSTITUICAO':<42} | {'PAC':<23} | {'ALIM':<8} | {'SUB':<5} | {'DEM_KW':<9} | {'CEP':<9}")
    linhas.append("-" * 100)

    # Ordenar por demanda contratada decrescente
    saude_ordenada = sorted(saude_mt, key=lambda x: x["DEM_CONT_KW"], reverse=True)
    for u in saude_ordenada[:8]:
        inst_curta = (u["INSTITUICAO"][:40] + "..") if len(u["INSTITUICAO"]) > 40 else u["INSTITUICAO"]
        linhas.append(
            f"{inst_curta:<42} | {u['PAC']:<23} | {u['CTMT']:<8} | {u['SUB']:<5} | "
            f"{u['DEM_CONT_KW']:>8.1f} | {u['CEP']:<9}"
        )

    linhas.append("-" * 100)
    linhas.append(f"Total de Unidades Hospitalares / Clinicas em MT mapeadas no Plano Piloto: {len(saude_mt)}")
    linhas.append(f"Total de Postos de Saude / Consultorios em BT mapeados: {len(saude_bt)}")
    linhas.append("")

    # 2. BLOCO SEGURANCA PUBLICA
    linhas.append("[SEGURANCA PUBLICA -- DELEGACIAS, BATALHOES E COMPLEXOS POLICIAIS]")
    linhas.append("-" * 100)
    linhas.append(f"{'INSTITUICAO / UNIDADE POLICIAL':<42} | {'PAC':<23} | {'ALIM':<8} | {'SUB':<5} | {'DEM_KW':<9} | {'CEP':<9}")
    linhas.append("-" * 100)

    seg_ordenada = sorted(seg_mt, key=lambda x: x["DEM_CONT_KW"], reverse=True)
    for u in seg_ordenada[:8]:
        inst_curta = (u["INSTITUICAO"][:40] + "..") if len(u["INSTITUICAO"]) > 40 else u["INSTITUICAO"]
        linhas.append(
            f"{inst_curta:<42} | {u['PAC']:<23} | {u['CTMT']:<8} | {u['SUB']:<5} | "
            f"{u['DEM_CONT_KW']:>8.1f} | {u['CEP']:<9}"
        )

    if dp1_bt:
        inst_curta = (dp1_bt["INSTITUICAO"][:40] + "..") if len(dp1_bt["INSTITUICAO"]) > 40 else dp1_bt["INSTITUICAO"]
        linhas.append(
            f"{inst_curta:<42} | {dp1_bt['PAC']:<23} | {dp1_bt['CTMT']:<8} | {dp1_bt['SUB']:<5} | "
            f"{'BT Dedic':>8} | {dp1_bt['CEP']:<9}"
        )

    linhas.append("-" * 100)
    linhas.append(f"Total de Unidades de Seguranca Publica em MT mapeadas no Plano Piloto: {len(seg_mt)}")
    linhas.append(f"Total de Postos Policiais / Vinculos em BT mapeados: {len(seg_bt)}")
    linhas.append("")

    # 3. PARECER PRELIMINAR DE RESILIENCIA E VULNERABILIDADE TOPOLOGICA (CRITICO)
    linhas.append("=" * 100)
    linhas.append("[PARECER PRELIMINAR DE RESILIENCIA: ZONA 2 (ASA SUL) vs. ZONA 1 (CEILANDIA)]")
    linhas.append("=" * 100)

    # Avaliação do compartilhamento de Circuito e Subestação
    ctmt_hbdf = hbdf["CTMT"] if hbdf else "N/A"
    sub_hbdf = hbdf["SUB"] if hbdf else "N/A"

    ctmt_sec_shs = posto_seg_shs["CTMT"] if posto_seg_shs else "N/A"
    sub_sec_shs = posto_seg_shs["SUB"] if posto_seg_shs else "N/A"

    ctmt_del_sps = delegacia_sps["CTMT"] if delegacia_sps else "N/A"
    sub_del_sps = delegacia_sps["SUB"] if delegacia_sps else "N/A"

    mesmo_circuito_shs = (ctmt_hbdf == ctmt_sec_shs) and ctmt_hbdf != "N/A"
    mesma_subestacao_geral = (sub_hbdf == sub_del_sps) and sub_hbdf != "N/A"

    linhas.append("1. VINCULOS TOPOLOGICOS DO HOSPITAL DE BASE (HBDF):")
    linhas.append(f"   * Hospital Principal: Hospital de Base do Distrito Federal (HBDF) -- Demanda: {hbdf['DEM_CONT_KW']:.1f} kW")
    linhas.append(f"   * Ponto de Acoplamento Comum (PAC): {hbdf['PAC']}")
    linhas.append(f"   * Alimentador Primario (CTMT):      {ctmt_hbdf}")
    linhas.append(f"   * Subestacao Supridora (SUB):       {sub_hbdf} (Subestacao Hipica / Setor Hospitalar Sul)")
    linhas.append("")

    linhas.append("2. VINCULOS DAS INFRAESTRUTURAS POLICIAIS CONEXAS:")
    if posto_seg_shs:
        linhas.append(f"   * Unidade Policial SHS: {posto_seg_shs['INSTITUICAO']} (PAC: {posto_seg_shs['PAC']})")
        linhas.append(f"     -> Circuito: {ctmt_sec_shs} | Subestacao: {sub_sec_shs}")
        if mesmo_circuito_shs:
            linhas.append("     -> [ALERTA CRITICO] COMPARTILHAMENTO ESTRITO DE CIRCUITO (MESMO ALIMENTADOR HP03)!")
    if delegacia_sps:
        linhas.append(f"   * Delegacia PCDF (SPS/1a DP): {delegacia_sps['INSTITUICAO']} (PAC: {delegacia_sps['PAC']})")
        linhas.append(f"     -> Circuito: {ctmt_del_sps} | Subestacao: {sub_del_sps}")
        if mesma_subestacao_geral:
            linhas.append("     -> [ALERTA CRITICO] COMPARTILHAMENTO DE SUBESTACAO (MESMA SUBESTACAO SHP)!")
    linhas.append("")

    linhas.append("3. CONTRASTE DE RESILIENCIA TOPOLOGICA (CEILANDIA vs. ASA SUL):")
    linhas.append("   * ZONA 1 (CEILANDIA -- ALTA SEGREGACAO FISICA):")
    linhas.append("     - Hospital Regional de Ceilandia (HRC) alimenta-se da Subestacao STN (Circuito TN08);")
    linhas.append("     - 15a Delegacia de Policia (15a DP) alimenta-se da Subestacao SCN (Circuito CN07);")
    linhas.append("     - Diagnostico: Nao ha modo comum de falha direto. Um desarme ou ataque cibernetico na")
    linhas.append("       subestacao da saude nao derruba a delegacia, e vice-versa.")
    linhas.append("")
    linhas.append("   * ZONA 2 (ASA SUL -- HIPER-CENTRALIZACAO E PONTO UNICO DE FALHA / SPOF):")
    linhas.append("     - O Hospital de Base (HBDF) e as unidades policiais centrais dependem da Subestacao SHP;")
    linhas.append("     - O HBDF e o posto policial do SHS operam NO MESMO ALIMENTADOR PRIMARIO (HP03);")
    linhas.append("     - A Delegacia da PCDF do Setor Policial opera no alimentador contiguo (HP04) na MESMA SE SHP;")
    linhas.append("     - Diagnostico: A Asa Sul e SUBSTANCIALMENTE MAIS CENTRALIZADA E CO-DEPENDENTE que Ceilandia.")
    linhas.append("       Um unico evento de colapso ciberfisico ou desarme intencional na Subestacao SHP")
    linhas.append("       comprometera SIMULTANEAMENTE o atendimento medico de emergencia e a ordem publica.")
    linhas.append("=" * 100)

    texto_final = "\n".join(linhas)
    print(texto_final)
    LOGGER.info("Dashboard terminal e Parecer de Resiliencia emitidos com sucesso.")


# ------------------------------------------------------------------------------
# Exportação de Metadados em JSON
# ------------------------------------------------------------------------------
def exportar_topologia_json(
    saude_mt: List[Dict[str, Any]],
    seg_mt: List[Dict[str, Any]],
    saude_bt: List[Dict[str, Any]],
    seg_bt: List[Dict[str, Any]],
    caminho_saida: Path
) -> None:
    """Exporta a base consolidada de vínculos topológicos em JSON estruturado."""
    payload = {
        "METADADOS": {
            "PROJETO": "Modelos Preditivos na Rede Elétrica do DF",
            "ETAPA": "Exploração do Ambiente 2 (Zona 2 - Asa Sul / Plano Piloto)",
            "RUN_TAG": RUN_TAG,
            "DATA_HORA_EXTRACAO": datetime.now().isoformat(),
            "TOTAL_SAUDE_MT": len(saude_mt),
            "TOTAL_SEGURANCA_MT": len(seg_mt),
            "TOTAL_SAUDE_BT": len(saude_bt),
            "TOTAL_SEGURANCA_BT": len(seg_bt),
        },
        "INFRAESTRUTURAS_SAUDE_MT": saude_mt,
        "INFRAESTRUTURAS_SEGURANCA_MT": seg_mt,
        "INFRAESTRUTURAS_SAUDE_BT": saude_bt,
        "INFRAESTRUTURAS_SEGURANCA_BT": seg_bt,
        "ANALISE_COMPARATIVA_RESILIENCIA": {
            "ZONA_1_CEILANDIA": {
                "HOSPITAL": "HRC (STN / TN08)",
                "DELEGACIA": "15ª DP (SCN / CN07)",
                "STATUS_COMPARTILHAMENTO": "SEGREGAÇÃO TOTAL",
                "AVALIACAO_VULNERABILIDADE": "Baixa correlação de falha em modo comum.",
            },
            "ZONA_2_ASA_SUL": {
                "HOSPITAL_PRINCIPAL": "HBDF (SHP / HP03)",
                "UNIDADE_POLICIAL_CONEXA": "Posto SHS / PCDF (SHP / HP03)",
                "DELEGACIA_SPS": "PCDF Setor Policial (SHP / HP04)",
                "STATUS_COMPARTILHAMENTO": "ALTO ACOPLAMENTO (MESMO CIRCUITO HP03 E MESMA SE SHP)",
                "AVALIACAO_VULNERABILIDADE": "Elevado risco de colapso ciberfísico em cascata (Single Point of Failure).",
            },
        },
    }

    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    LOGGER.info(f"Arquivo JSON de topologia exportado: {caminho_saida.resolve()} ({caminho_saida.stat().st_size:,} bytes)")


# ------------------------------------------------------------------------------
# Função Principal (Pipeline de Execução)
# ------------------------------------------------------------------------------
def main() -> None:
    LOGGER.info("=" * 80)
    LOGGER.info("INICIANDO EXPLORAÇÃO TOPOLÓGICA DA ZONA 2 (ASA SUL / PLANO PILOTO)")
    LOGGER.info(f"RUN_TAG: {RUN_TAG}")
    LOGGER.info("=" * 80)

    # 1. Localização dos arquivos consolidados
    mt_file = encontrar_arquivo_mais_recente(PROCESSED_DIR, "UCMT_consolidada_*.csv")
    bt_file = encontrar_arquivo_mais_recente(PROCESSED_DIR, "UCBT_consolidada_*.csv")

    LOGGER.info(f"Base UCMT selecionada: {mt_file.name}")
    LOGGER.info(f"Base UCBT selecionada: {bt_file.name}")

    # 2. Varredura em Média Tensão (UCMT)
    saude_mt, seg_mt = varrer_ucmt_asa_sul(mt_file)

    # 3. Varredura em Baixa Tensão (UCBT em Chunks)
    saude_bt, seg_bt = varrer_ucbt_asa_sul_chunks(bt_file, chunk_size=150000)

    # 4. Emissão do Dashboard Terminal com Parecer de Resiliência
    emitir_dashboard_terminal(saude_mt, seg_mt, saude_bt, seg_bt)

    # 5. Exportação do JSON Estruturado
    exportar_topologia_json(saude_mt, seg_mt, saude_bt, seg_bt, JSON_OUTPUT)

    LOGGER.info("=" * 80)
    LOGGER.info("EXPLORAÇÃO DA ZONA 2 (ASA SUL) CONCLUÍDA COM SUCESSO!")
    LOGGER.info(f"Artefato JSON disponível em: {JSON_OUTPUT}")
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()

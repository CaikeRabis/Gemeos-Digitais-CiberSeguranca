"""05_rastreamento_hrc.py

Etapa E4: Rastreamento Topologico do Hospital Regional de Ceilandia (HRC).
Varre as bases consolidadas de Media Tensao (UCMT) e Baixa Tensao (UCBT)
em data/processed/ para identificar a Unidade Consumidora (UC) do HRC e extrair
sua cadeia de conexao fisica a rede de distribuicao:
UC -> RAMAL -> PAC -> UNI_TR_MT -> CTMT -> SUB.

Saidas:
- data/processed/hrc_topologia_{RUN_TAG}.json
- logs/05_rastreamento_hrc_{RUN_TAG}.log
"""

from __future__ import annotations

import json
import logging
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Configuracoes de caminhos e RUN_TAG
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR = BASE_DIR / "logs"

LOG_PATH = LOGS_DIR / f"05_rastreamento_hrc_{RUN_TAG}.log"
JSON_SAIDA = PROCESSED_DIR / f"hrc_topologia_{RUN_TAG}.json"

LOGGER = logging.getLogger("05_rastreamento_hrc")


def setup_logging() -> None:
    """Configura logging simultaneo no console e em arquivo com codificacao UTF-8."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
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


def obter_arquivos_consolidados() -> tuple[Path, Path]:
    """Identifica dinamicamente os arquivos consolidados mais recentes de MT e BT."""
    mt_files = sorted(PROCESSED_DIR.glob("UCMT_consolidada_*.csv"))
    bt_files = sorted(PROCESSED_DIR.glob("UCBT_consolidada_*.csv"))

    if not mt_files:
        LOGGER.error("Nenhum arquivo UCMT_consolidada_*.csv encontrado em %s", PROCESSED_DIR)
        sys.exit(1)
    if not bt_files:
        LOGGER.error("Nenhum arquivo UCBT_consolidada_*.csv encontrado em %s", PROCESSED_DIR)
        sys.exit(1)

    caminho_mt = mt_files[-1]
    caminho_bt = bt_files[-1]

    LOGGER.info("Arquivo UCMT consolidado mais recente: %s", caminho_mt.name)
    LOGGER.info("Arquivo UCBT consolidado mais recente: %s", caminho_bt.name)
    return caminho_mt, caminho_bt


def normalizar_texto(texto: Any) -> str:
    """Normaliza texto para maiusculo, sem acentos e sem espacos excedentes."""
    if pd.isna(texto) or texto is None:
        return ""
    s = str(texto).strip()
    s_sem_acento = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")
    return s_sem_acento.upper()


def buscar_candidatas_ucmt(caminho_mt: Path) -> list[dict[str, Any]]:
    """Varre a base consolidada de Media Tensao buscando candidatas compativeis com o HRC."""
    LOGGER.info("Iniciando varredura na base de Media Tensao: %s", caminho_mt.name)
    df_mt = pd.read_csv(caminho_mt, dtype=str)
    LOGGER.info("Total de registros em UCMT_consolidada: %d", len(df_mt))

    candidatas: list[dict[str, Any]] = []

    for _, row in df_mt.iterrows():
        brr = normalizar_texto(row.get("BRR", ""))
        cep = str(row.get("CEP", "")).strip()
        cnae = str(row.get("CNAE", "")).strip()
        clas_sub = str(row.get("CLAS_SUB", "")).strip().upper()
        descr = normalizar_texto(row.get("DESCR", ""))

        pontuacao = 0
        evidencias: list[str] = []

        # 1. Filtro geografico / Bairro
        if "CEILANDIA" in brr:
            pontuacao += 30
            evidencias.append(f"Bairro: {brr}")

        # 2. CEP exato do HRC (72215-178 - Area Especial QNM 27)
        if cep == "72215-178":
            pontuacao += 50
            evidencias.append(f"CEP exato do HRC: {cep}")
        elif cep.startswith("72215"):
            pontuacao += 20
            evidencias.append(f"Setor do HRC (CEP {cep})")

        # 3. CNAE Hospitalar (8610) ou Saude (86)
        if cnae.startswith("8610"):
            pontuacao += 60
            evidencias.append(f"CNAE Hospitalar: {cnae}")
        elif cnae.startswith("86"):
            pontuacao += 25
            evidencias.append(f"CNAE de Saude: {cnae}")

        # 4. Potencia instalada de grande porte
        try:
            car_inst = float(str(row.get("CAR_INST", "0")).replace(",", "."))
            if car_inst > 10000.0:
                pontuacao += 40
                evidencias.append(f"Potencia Instalada de Grande Porte: {car_inst:.1f} kW")
            elif car_inst > 1000.0:
                pontuacao += 15
                evidencias.append(f"Potencia Instalada Media: {car_inst:.1f} kW")
        except (ValueError, TypeError):
            pass

        # 5. Termos textuais diretos
        texto_geral = f"{brr} {descr}"
        if "HOSPITAL" in texto_geral:
            pontuacao += 50
            evidencias.append("Termo HOSPITAL identificado")

        # Se houver pontuacao relevante, acumula candidata
        if pontuacao >= 70:
            item = row.to_dict()
            item["_tabela_origem"] = "UCMT"
            item["_score_aderencia"] = pontuacao
            item["_evidencias"] = evidencias
            candidatas.append(item)

    candidatas.sort(key=lambda x: x["_score_aderencia"], reverse=True)
    LOGGER.info("UCMT: %d candidatas com aderencia relevante identificadas.", len(candidatas))
    return candidatas


def buscar_candidatas_ucbt(caminho_bt: Path) -> list[dict[str, Any]]:
    """Varre a base consolidada de Baixa Tensao em chunks buscando candidatas compativeis."""
    LOGGER.info("Iniciando varredura particionada em Baixa Tensao: %s", caminho_bt.name)
    candidatas: list[dict[str, Any]] = []
    linhas_lidas = 0

    colunas_busca = ["COD_ID", "BRR", "CEP", "CNAE", "CLAS_SUB", "DESCR", "PAC", "RAMAL", "PN_CON", "UNI_TR_MT", "CTMT", "SUB", "CAR_INST"]

    for chunk in pd.read_csv(caminho_bt, chunksize=100000, dtype=str, usecols=lambda c: c in colunas_busca):
        linhas_lidas += len(chunk)

        # Filtrar registros em Ceilandia com CNAE de saude ou CEP do HRC
        mask = (
            (chunk["CEP"] == "72215-178")
            | (chunk["CNAE"].fillna("").str.startswith("8610") & (chunk["BRR"].fillna("").str.upper() == "CEILANDIA"))
        )
        sub = chunk.loc[mask]

        for _, row in sub.iterrows():
            brr = normalizar_texto(row.get("BRR", ""))
            cep = str(row.get("CEP", "")).strip()
            cnae = str(row.get("CNAE", "")).strip()

            pontuacao = 0
            evidencias: list[str] = []

            if "CEILANDIA" in brr:
                pontuacao += 20
                evidencias.append(f"Bairro: {brr}")
            if cep == "72215-178":
                pontuacao += 40
                evidencias.append(f"CEP do HRC: {cep}")
            if cnae.startswith("8610"):
                pontuacao += 40
                evidencias.append(f"CNAE Hospitalar: {cnae}")

            item = row.to_dict()
            item["_tabela_origem"] = "UCBT"
            item["_score_aderencia"] = pontuacao
            item["_evidencias"] = evidencias
            candidatas.append(item)

    candidatas.sort(key=lambda x: x["_score_aderencia"], reverse=True)
    LOGGER.info("UCBT: %d candidatas identificadas apos leitura de %d linhas.", len(candidatas), linhas_lidas)
    return candidatas


def extrair_topologia(uc_data: dict[str, Any]) -> dict[str, Any]:
    """Extrai rigorosamente o dicionario de chaves topologicas da UC identificada."""
    tabela = uc_data.get("_tabela_origem", "UCMT")
    cid = str(uc_data.get("COD_ID", "")).strip()
    pac = str(uc_data.get("PAC", "")).strip()
    pn_con = str(uc_data.get("PN_CON", "")).strip()
    ctmt = str(uc_data.get("CTMT", "")).strip()
    sub = str(uc_data.get("SUB", "")).strip()
    uni_tr_at = str(uc_data.get("UNI_TR_AT", "")).strip()

    if tabela == "UCMT":
        ramal = "N/A (Conexao Direta MT)"
        uni_tr_mt = "N/A (Subestacao Propria / Barramento MT)"
    else:
        ramal = str(uc_data.get("RAMAL", "")).strip() or "N/A"
        uni_tr_mt = str(uc_data.get("UNI_TR_MT", "")).strip() or "N/A"

    diagrama = f"UC [{cid}] -> RAMAL [{ramal}] -> PAC [{pac}] -> UNI_TR_MT [{uni_tr_mt}] -> CTMT [{ctmt}] -> SUB [{sub}]"

    return {
        "COD_ID": cid,
        "RAMAL": ramal,
        "PAC": pac,
        "PN_CON": pn_con,
        "UNI_TR_MT": uni_tr_mt,
        "CTMT": ctmt,
        "UNI_TR_AT": uni_tr_at,
        "SUB": sub,
        "DIAGRAMA_CADEIA": diagrama,
    }


def main() -> None:
    setup_logging()

    LOGGER.info("================================================================================")
    LOGGER.info("INICIANDO ETAPA E4: RASTREAMENTO TOPOLOGICO DO HRC (RUN_TAG=%s)", RUN_TAG)
    LOGGER.info("================================================================================")

    caminho_mt, caminho_bt = obter_arquivos_consolidados()

    # 1. Busca em Media Tensao
    candidatas_mt = buscar_candidatas_ucmt(caminho_mt)

    # 2. Busca em Baixa Tensao (complementar/contingencial)
    candidatas_bt = buscar_candidatas_ucbt(caminho_bt)

    # Avaliacao da UC Primaria do HRC
    if not candidatas_mt:
        LOGGER.error("Nenhuma candidata compativel localizada em Media Tensao.")
        sys.exit(1)

    uc_primaria = candidatas_mt[0]
    score = uc_primaria["_score_aderencia"]

    LOGGER.info("================================================================================")
    LOGGER.info("UNIDADE CONSUMIDORA DO HRC LOCALIZADA COM SUCESSO!")
    LOGGER.info("================================================================================")
    LOGGER.info("COD_ID: %s (Score de Aderencia: %d/100)", uc_primaria["COD_ID"], score)
    LOGGER.info("Origem: %s | Bairro: %s | CEP: %s", uc_primaria["_tabela_origem"], uc_primaria.get("BRR"), uc_primaria.get("CEP"))
    LOGGER.info("CNAE: %s (Atividades de Atendimento Hospitalar)", uc_primaria.get("CNAE"))
    LOGGER.info("Classe / Grupo Tarifario: %s / %s (Media Tensao A4)", uc_primaria.get("CLAS_SUB"), uc_primaria.get("GRU_TAR"))
    LOGGER.info("Carga Instalada: %s kW | Demanda Contratada: %s kW", uc_primaria.get("CAR_INST"), uc_primaria.get("DEM_CONT"))
    LOGGER.info("Evidencias cruzadas: %s", "; ".join(uc_primaria["_evidencias"]))

    # Extrair topologia fisica
    topologia = extrair_topologia(uc_primaria)

    LOGGER.info("================================================================================")
    LOGGER.info("DIAGRAMA TOPOLOGICO EM CADEIA DA ALIMENTACAO ELETRICA DO HRC:")
    LOGGER.info("================================================================================")
    LOGGER.info("%s", topologia["DIAGRAMA_CADEIA"])
    LOGGER.info("--------------------------------------------------------------------------------")
    LOGGER.info("  * SUBESTACAO ALIMENTADORA (SUB): %s", topologia["SUB"])
    LOGGER.info("  * CIRCUITO DE MEDIA TENSAO (CTMT): %s", topologia["CTMT"])
    LOGGER.info("  * TRANSFORMADOR AT/MT (UNI_TR_AT): %s", topologia["UNI_TR_AT"])
    LOGGER.info("  * PONTO DE ACESSO (PAC): %s", topologia["PAC"])
    LOGGER.info("  * POSTE DE CONEXAO (PN_CON): %s", topologia["PN_CON"])
    LOGGER.info("================================================================================")

    # Montar estrutura JSON completa
    dados_exportacao = {
        "run_tag": RUN_TAG,
        "timestamp": datetime.now().isoformat(),
        "objetivo": "Rastreamento Topologico do Hospital Regional de Ceilandia (HRC) - Etapa E4",
        "hrc_uc_primaria": {
            "topologia_cadeia": topologia,
            "dados_cadastrais_completos": {
                k: v for k, v in uc_primaria.items() if not k.startswith("_")
            },
            "metadados_rastreamento": {
                "score_aderencia": uc_primaria["_score_aderencia"],
                "evidencias": uc_primaria["_evidencias"],
            },
        },
        "candidatas_adicionais_mt": [
            {
                "COD_ID": c.get("COD_ID"),
                "CNAE": c.get("CNAE"),
                "CEP": c.get("CEP"),
                "CAR_INST": c.get("CAR_INST"),
                "CTMT": c.get("CTMT"),
                "SUB": c.get("SUB"),
                "PAC": c.get("PAC"),
                "PN_CON": c.get("PN_CON"),
                "score": c.get("_score_aderencia"),
                "evidencias": c.get("_evidencias"),
            }
            for c in candidatas_mt[1:]
        ],
        "candidatas_baixa_tensao_bt_entorno": [
            {
                "COD_ID": c.get("COD_ID"),
                "CNAE": c.get("CNAE"),
                "CEP": c.get("CEP"),
                "CTMT": c.get("CTMT"),
                "SUB": c.get("SUB"),
                "score": c.get("_score_aderencia"),
            }
            for c in candidatas_bt[:10]
        ],
    }

    # Salvar JSON formatado
    with JSON_SAIDA.open("w", encoding="utf-8") as f:
        json.dump(dados_exportacao, f, indent=2, ensure_ascii=False)

    LOGGER.info("Artefato JSON gravado com sucesso em: %s", JSON_SAIDA)
    LOGGER.info("Log registrado em: %s", LOG_PATH)
    LOGGER.info("Etapa E4 concluida com exito.")


if __name__ == "__main__":
    main()

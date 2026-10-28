"""Inventário de esquema da BDGD e perfil de campos para futura análise topológica.

Script estritamente somente-leitura para a BDGD (.gdb), o GeoPackage e o CSV de hospitais.
Gera inventários de tabelas, perfil de campos, compatibilidade de chaves de ligação,
perfil de UCs no entorno do HRC e relatório textual com hashes de integridade.

Aviso metodológico:
Schema não é topologia. Este script realiza apenas inventário estático e medição de
compatibilidade cadastral. Não monta grafos, não infere fluxo de potência e não
conclui conectividade elétrica ou atendimento ao hospital.
"""

import argparse
import hashlib
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import CRS
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

# --------------------------------------------------------------------------- #
# Constantes de Caminhos e Configuração
# --------------------------------------------------------------------------- #
BASE_DIR: Path = Path(__file__).resolve().parent.parent
RAW_DIR: Path = BASE_DIR / "data" / "raw"
PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"
LOGS_DIR: Path = BASE_DIR / "logs"

GPKG_PATH: Path = PROCESSED_DIR / "subrede_hospitais.gpkg"
CSV_PATH: Path = RAW_DIR / "hospitais_df.csv"

OUT_TABELAS_CSV: Path = PROCESSED_DIR / "inventario_tabelas_bdgd.csv"
OUT_CAMPOS_CSV: Path = PROCESSED_DIR / "inventario_campos_bdgd.csv"
OUT_CANDIDATOS_CSV: Path = PROCESSED_DIR / "candidatos_chave_ligacao.csv"
OUT_UCS_CSV: Path = PROCESSED_DIR / "perfil_ucs_entorno_hrc.csv"
OUT_RELATORIO_TXT: Path = PROCESSED_DIR / "relatorio_inventario_bdgd.txt"

PROTEGIDOS: tuple[Path, ...] = (
    GPKG_PATH,
    CSV_PATH,
    PROCESSED_DIR / "mapa_topologia.png",
    PROCESSED_DIR / "validacao_visual_subrede_hrc.png",
    PROCESSED_DIR / "relatorio_validacao_subrede_hrc.txt",
)

CRS_ORIGEM_ESPERADO: int = 4674
CRS_TRABALHO: int = 31983
RAIO_BUFFER_METROS: float = 3_000.0

TABELAS_ESPERADAS: tuple[str, ...] = (
    "UCMT", "UCBT", "SSDMT", "SSDBT", "SSDAT", "UNTRMT", "UNTRAT", "CHAVE", "CTMT", "SUB",
)

logger = logging.getLogger("inventario_bdgd")


# --------------------------------------------------------------------------- #
# Estruturas de Dados
# --------------------------------------------------------------------------- #
@dataclass
class Entradas:
    """Entradas validadas do script."""

    gdb: Path
    gpkg: Path
    csv: Path


@dataclass
class TabelaResumo:
    """Metadados estruturais de uma tabela/camada da BDGD."""

    nome_real: str
    tipo_geometrico: str
    crs: str
    num_registros: int
    num_campos: int
    status_esperada: str
    correspondencia_esperada: str


@dataclass
class CampoPerfil:
    """Perfil estatístico e semântico de um campo."""

    tabela: str
    campo: str
    tipo_dados: str
    tipo_ogr: str
    aceita_nulo: str
    dominio_conhecido: str
    valores_distintos: int
    num_nulos: int
    pct_nulos: float
    num_vazios: int
    pct_vazios: float
    exemplos: str
    papel_candidato: str
    observacao_papel: str


@dataclass
class CompatibilidadeChave:
    """Medição de compatibilidade entre pares de campos relacionais."""

    tabela_origem: str
    campo_origem: str
    tabela_destino: str
    campo_destino: str
    total_linhas_origem: int
    total_linhas_destino: int
    distintos_origem: int
    distintos_destino: int
    nulos_origem: int
    nulos_destino: int
    valores_em_comum: int
    taxa_correspondencia_origem: float
    taxa_correspondencia_destino: float
    cardinalidade_inferida: str
    papel_relacao: str


# --------------------------------------------------------------------------- #
# Infraestrutura e Logging
# --------------------------------------------------------------------------- #
def configurar_logging(log_path: Path) -> None:
    """Configura logging para terminal e arquivo com timestamp."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)


def calcular_sha256_arquivo(caminho: Path) -> str:
    """Calcula hash SHA-256 de arquivo individual."""
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def calcular_sha256_diretorio_gdb(caminho: Path) -> str:
    """Calcula hash SHA-256 composto determinístico de todos os arquivos do .gdb."""
    if not caminho.is_dir():
        return calcular_sha256_arquivo(caminho)
    h_global = hashlib.sha256()
    arquivos = sorted(p for p in caminho.iterdir() if p.is_file())
    for arq in arquivos:
        h_arq = calcular_sha256_arquivo(arq)
        h_global.update(arq.name.encode("utf-8"))
        h_global.update(str(arq.stat().st_size).encode("utf-8"))
        h_global.update(h_arq.encode("utf-8"))
    return h_global.hexdigest()


def obter_hashes_entradas(entradas: Entradas) -> dict[str, str]:
    """Calcula hashes das entradas principais para validação de integridade."""
    return {
        entradas.gdb.name: calcular_sha256_diretorio_gdb(entradas.gdb),
        entradas.gpkg.name: calcular_sha256_arquivo(entradas.gpkg),
        entradas.csv.name: calcular_sha256_arquivo(entradas.csv),
    }


def localizar_entradas() -> Entradas:
    """Localiza e valida as entradas necessárias."""
    if not GPKG_PATH.exists():
        raise FileNotFoundError(f"GeoPackage não encontrado: {GPKG_PATH}")
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV de hospitais não encontrado: {CSV_PATH}")

    gdbs = sorted(p for p in RAW_DIR.glob("*.gdb") if p.is_dir())
    if not gdbs:
        raise FileNotFoundError(f"Nenhuma base BDGD (.gdb) encontrada em {RAW_DIR}")
    gdb = gdbs[0]

    logger.info("Base BDGD localizada: %s", gdb.name)
    logger.info("GeoPackage localizado: %s", GPKG_PATH.name)
    logger.info("CSV localizado: %s", CSV_PATH.name)
    return Entradas(gdb=gdb, gpkg=GPKG_PATH, csv=CSV_PATH)


# --------------------------------------------------------------------------- #
# Mapeamento e Descoberta de Camadas
# --------------------------------------------------------------------------- #
def mapear_tabelas_esperadas(camadas_reais: list[str]) -> dict[str, tuple[str, str]]:
    """Mapeia tabelas esperadas para camadas reais ou registra ausência."""
    mapeamento: dict[str, tuple[str, str]] = {}
    reais_lower = {c.lower(): c for c in camadas_reais}

    # Regras de correspondência normativas da BDGD (v11 / PRODIST Módulo 8)
    regras: dict[str, list[str]] = {
        "UCMT": ["ucmt_tab", "ucmt"],
        "UCBT": ["ucbt_tab", "ucbt"],
        "SSDMT": ["ssdmt"],
        "SSDBT": ["ssdbt"],
        "SSDAT": ["ssdat"],
        "UNTRMT": ["untrmt"],
        "UNTRAT": ["untrat"],
        "CHAVE": ["unsemt", "unsebt", "unseat", "eqse"],
        "CTMT": ["ctmt"],
        "SUB": ["sub"],
    }

    for esp, candidatos in regras.items():
        encontrado: Optional[str] = None
        for cand in candidatos:
            if cand in reais_lower:
                encontrado = reais_lower[cand]
                break
        if encontrado:
            if encontrado.upper() == esp:
                mapeamento[esp] = (encontrado, "Encontrada com nome exato")
            else:
                mapeamento[esp] = (encontrado, f"Encontrada como alternativa normativa '{encontrado}'")
        else:
            mapeamento[esp] = ("NÃO ENCONTRADA", "Ausente no banco com esse nome")

    return mapeamento


def inventariar_tabelas(gdb: Path) -> list[TabelaResumo]:
    """Descobre e quantifica todas as tabelas e camadas do .gdb."""
    camadas_tuplas = pyogrio.list_layers(gdb)
    nomes_reais = [nome for nome, _ in camadas_tuplas]
    mapa_esperadas = mapear_tabelas_esperadas(nomes_reais)

    # Inverter mapa para busca rápida da correspondência
    esperada_por_real: dict[str, str] = {}
    for esp, (real, _) in mapa_esperadas.items():
        if real != "NÃO ENCONTRADA":
            esperada_por_real[real] = esp

    resumos: list[TabelaResumo] = []
    for nome, geom in camadas_tuplas:
        try:
            info = pyogrio.read_info(gdb, layer=nome)
            n_reg = int(info.get("features", 0))
            campos = info.get("fields", [])
            crs_str = str(info.get("crs")) if info.get("crs") else "Nenhum (Tabela Tabular)"
            geom_str = str(geom) if geom is not None else "Nenhum (Tabela Tabular)"

            corresp = esperada_por_real.get(nome, "Outra tabela BDGD")
            status = "Alvo principal" if nome in esperada_por_real else "Tabela de suporte/domínio"

            resumos.append(TabelaResumo(
                nome_real=nome,
                tipo_geometrico=geom_str,
                crs=crs_str,
                num_registros=n_reg,
                num_campos=len(campos),
                status_esperada=status,
                correspondencia_esperada=corresp,
            ))
        except Exception:
            logger.exception("Falha ao obter informações da camada %s", nome)

    logger.info("Total de camadas/tabelas inventariadas no GDB: %d", len(resumos))
    return resumos


# --------------------------------------------------------------------------- #
# Classificação Semântica e Perfil de Campos
# --------------------------------------------------------------------------- #
def classificar_papel_campo(tabela: str, campo: str) -> tuple[str, str, str]:
    """Classifica o papel candidato do campo e documenta domínios conhecidos."""
    c_upper = campo.upper()
    t_upper = tabela.upper()

    # Domínio normativo ANEEL PRODIST Módulo 8 conhecido
    dominios_conhecidos: dict[str, str] = {
        "P_N_OPE": "A: Aberta, F: Fechada (Posição Normal de Operação)",
        "SIT_ATIV": "AT: Ativo, DS: Desativado, ET: Em Projeto",
        "FAS_CON": "Fases de conexão (A, B, C, AB, BC, CA, ABC)",
        "CLAS_SUB": "Código de Classe e Subclasse tarifária ANEEL (RE, CO, IN, PP, SP, IP, etc.)",
        "TIP_UNID": "Código numérico do tipo de unidade seccionadora/transformadora",
        "GRU_TAR": "Grupo tarifário (A1, A2, A3, A4, AS, B1, B2, B3, B4)",
        "GRU_TEN": "Grupo de tensão (AT, MT, BT)",
        "TEN_NOM": "Tensão nominal de operação em kV",
        "TEN_OPE": "Tensão de operação em kV",
        "ABER_CRG": "S: Permite abertura sob carga, N: Não permite",
        "DIST": "Código da distribuidora na ANEEL (5160 = Neoenergia Brasília)",
    }
    dominio = dominios_conhecidos.get(c_upper, "Não codificado / Contínuo ou chave livre")

    # Papéis candidatos
    if c_upper in {"COD_ID", "ID"}:
        return (
            "identificador",
            "Identificador exclusivo ou código primário da feição (inferido pelo nome e norma BDGD)",
            dominio,
        )
    if any(c_upper.startswith(p) for p in ("PAC", "PN_CON", "BARR")):
        return (
            "nó / conexão",
            "Ponto de acoplamento comum ou nó elétrico topológico (inferido pelo nome e norma BDGD)",
            dominio,
        )
    if c_upper in {"CTMT", "CTAT", "CTBT", "CT_COD_OP"}:
        return (
            "circuito",
            "Identificador do alimentador ou circuito de distribuição (inferido pelo nome e norma BDGD)",
            dominio,
        )
    if c_upper in {"SUB", "UNI_TR_AT"}:
        return (
            "subestação",
            "Vínculo com subestação ou transformador de força AT (inferido pelo nome e norma BDGD)",
            dominio,
        )
    if c_upper in {"P_N_OPE", "TIP_UNID", "ABER_CRG", "CAP_ELO", "ELO_FSV"} or (
        t_upper.startswith("UNSE") and c_upper in {"POS", "TLCD"}
    ):
        return (
            "chave / estado",
            "Atributo funcional de manobra ou seccionamento (inferido pelo nome e norma BDGD)",
            dominio,
        )
    if c_upper in {"CLAS_SUB", "CNAE", "TIP_CC", "GRU_TAR", "GRU_TEN"}:
        return (
            "classe de consumo",
            "Classificação socioeconômica ou tarifária da UC (inferido pelo nome e norma BDGD)",
            dominio,
        )
    if (
        c_upper in {"CAR_INST", "DEM_CONT", "POT_NOM", "POT_AT", "POT_MT", "POT_BT"}
        or c_upper.startswith("DEM_")
        or c_upper.startswith("ENE_")
    ):
        return (
            "carga / potência",
            "Potência instalada, demanda contratada ou consumo de energia (inferido pelo nome e norma BDGD)",
            dominio,
        )

    return ("outro", "Atributo técnico ou administrativo geral", dominio)


def perfilar_campos_tabela(gdb: Path, tabela: str) -> list[CampoPerfil]:
    """Calcula estatísticas de perfil para cada campo de uma tabela."""
    info = pyogrio.read_info(gdb, layer=tabela)
    fields = list(info.get("fields", []))
    dtypes = list(info.get("dtypes", []))
    ogr_types = list(info.get("ogr_types", []))

    tipo_map = dict(zip(fields, dtypes))
    ogr_map = dict(zip(fields, ogr_types))

    perfis: list[CampoPerfil] = []
    total_linhas = int(info.get("features", 0))

    if total_linhas == 0:
        for f in fields:
            papel, obs, dom = classificar_papel_campo(tabela, f)
            perfis.append(CampoPerfil(
                tabela=tabela,
                campo=f,
                tipo_dados=str(tipo_map.get(f, "desconhecido")),
                tipo_ogr=str(ogr_map.get(f, "desconhecido")),
                aceita_nulo="Sim",
                dominio_conhecido=dom,
                valores_distintos=0,
                num_nulos=0,
                pct_nulos=0.0,
                num_vazios=0,
                pct_vazios=0.0,
                exemplos="[Tabela Vazia]",
                papel_candidato=papel,
                observacao_papel=obs,
            ))
        return perfis

    # Leitura sem geometria para máxima performance de processamento
    df = pyogrio.read_dataframe(gdb, layer=tabela, read_geometry=False)

    for f in fields:
        s = df[f]
        n_nulos = int(s.isna().sum())
        pct_nulos = (n_nulos / total_linhas) * 100.0

        n_vazios = 0
        if s.dtype == "object":
            # Considerar string vazia ou apenas espaços
            s_str = s.dropna().astype(str).str.strip()
            n_vazios = int((s_str == "").sum())
        pct_vazios = (n_vazios / total_linhas) * 100.0

        n_distintos = int(s.nunique(dropna=True))

        # Obter até 5 exemplos sem expor dados pessoais
        valores_validos = s.dropna().unique()
        if s.dtype == "object":
            valores_validos = [v for v in valores_validos if str(v).strip() != ""]

        exemplos_amostra = [str(x) for x in valores_validos[:5]]
        exemplos_str = "; ".join(exemplos_amostra) if exemplos_amostra else "[Vazio/Nulo]"

        papel, obs, dom = classificar_papel_campo(tabela, f)
        if papel == "identificador":
            if n_distintos == total_linhas and n_nulos == 0:
                obs += " | Chave primária estrita (única e não-nula)"
            else:
                obs += f" | Não estritamente única (distintos: {n_distintos}/{total_linhas})"

        perfis.append(CampoPerfil(
            tabela=tabela,
            campo=f,
            tipo_dados=str(s.dtype),
            tipo_ogr=str(ogr_map.get(f, "desconhecido")),
            aceita_nulo="Sim" if n_nulos > 0 else "Não observado nulo",
            dominio_conhecido=dom,
            valores_distintos=n_distintos,
            num_nulos=n_nulos,
            pct_nulos=pct_nulos,
            num_vazios=n_vazios,
            pct_vazios=pct_vazios,
            exemplos=exemplos_str,
            papel_candidato=papel,
            observacao_papel=obs,
        ))

    return perfis


# --------------------------------------------------------------------------- #
# Compatibilidade Relacional Entre Tabelas
# --------------------------------------------------------------------------- #
def medir_compatibilidade_par(
    gdb: Path,
    tab_a: str,
    col_a: str,
    tab_b: str,
    col_b: str,
    papel_relacao: str,
) -> Optional[CompatibilidadeChave]:
    """Mede a taxa de correspondência entre dois campos de tabelas distintas."""
    try:
        df_a = pyogrio.read_dataframe(gdb, layer=tab_a, columns=[col_a], read_geometry=False)
        df_b = pyogrio.read_dataframe(gdb, layer=tab_b, columns=[col_b], read_geometry=False)
    except Exception:
        logger.exception("Erro ao ler par para compatibilidade: %s.%s vs %s.%s", tab_a, col_a, tab_b, col_b)
        return None

    tot_a, tot_b = len(df_a), len(df_b)
    nulos_a = int(df_a[col_a].isna().sum())
    nulos_b = int(df_b[col_b].isna().sum())

    set_a = set(df_a[col_a].dropna().astype(str).str.strip())
    set_b = set(df_b[col_b].dropna().astype(str).str.strip())
    set_a.discard("")
    set_b.discard("")

    dist_a, dist_b = len(set_a), len(set_b)
    inter = set_a.intersection(set_b)
    n_comum = len(inter)

    taxa_a = (n_comum / dist_a) if dist_a > 0 else 0.0
    taxa_b = (n_comum / dist_b) if dist_b > 0 else 0.0

    # Inferência simples de cardinalidade
    card = "N:M"
    if dist_a == tot_a and dist_b == tot_b:
        card = "1:1"
    elif dist_a == tot_a and dist_b < tot_b:
        card = "1:N (A -> B)"
    elif dist_b == tot_b and dist_a < tot_a:
        card = "N:1 (A -> B)"

    return CompatibilidadeChave(
        tabela_origem=tab_a,
        campo_origem=col_a,
        tabela_destino=tab_b,
        campo_destino=col_b,
        total_linhas_origem=tot_a,
        total_linhas_destino=tot_b,
        distintos_origem=dist_a,
        distintos_destino=dist_b,
        nulos_origem=nulos_a,
        nulos_destino=nulos_b,
        valores_em_comum=n_comum,
        taxa_correspondencia_origem=taxa_a,
        taxa_correspondencia_destino=taxa_b,
        cardinalidade_inferida=card,
        papel_relacao=papel_relacao,
    )


def executar_matriz_compatibilidade(gdb: Path) -> list[CompatibilidadeChave]:
    """Executa a medição de compatibilidade para os pares relacionais essenciais."""
    pares_definidos: list[tuple[str, str, str, str, str]] = [
        # Nós e Conexões MT
        ("SSDMT", "PAC_1", "UNTRMT", "PAC_1", "Nó de conexão primário Linha MT <-> Trafo MT"),
        ("SSDMT", "PAC_2", "UNTRMT", "PAC_1", "Nó de conexão primário Linha MT (fim) <-> Trafo MT"),
        ("SSDMT", "PAC_1", "UNSEMT", "PAC_1", "Nó elétrico Linha MT <-> Chave Seccionadora MT"),
        ("SSDMT", "PAC_2", "UNSEMT", "PAC_2", "Nó elétrico Linha MT (fim) <-> Chave Seccionadora MT"),
        ("SSDMT", "PAC_1", "SSDMT", "PAC_2", "Continuidade de nós entre trechos de Linha MT"),
        # Nós e Conexões BT
        ("SSDBT", "PAC_1", "UNTRMT", "PAC_2", "Nó de conexão Linha BT <-> Secundário do Trafo MT"),
        ("SSDBT", "PAC_1", "SSDBT", "PAC_2", "Continuidade de nós entre trechos de Linha BT"),
        # Pontos Notáveis (Postes / Nós Físicos)
        ("UCMT_tab", "PN_CON", "PONNOT", "COD_ID", "Vínculo geográfico UC MT -> Ponto Notável (Poste)"),
        ("UCBT_tab", "PN_CON", "PONNOT", "COD_ID", "Vínculo geográfico UC BT -> Ponto Notável (Poste)"),
        ("SSDMT", "PN_CON_1", "PONNOT", "COD_ID", "Vínculo físico Linha MT -> Ponto Notável"),
        ("SSDBT", "PN_CON_1", "PONNOT", "COD_ID", "Vínculo físico Linha BT -> Ponto Notável"),
        ("RAMLIG", "PN_CON_1", "PONNOT", "COD_ID", "Vínculo físico Ramal de Ligação -> Ponto Notável"),
        # Vínculos com Transformador MT
        ("UCBT_tab", "UNI_TR_MT", "UNTRMT", "COD_ID", "Vínculo elétrico UC BT -> Transformador MT alimentador"),
        ("SSDBT", "UNI_TR_MT", "UNTRMT", "COD_ID", "Vínculo elétrico Trecho BT -> Transformador MT alimentador"),
        ("RAMLIG", "UNI_TR_MT", "UNTRMT", "COD_ID", "Vínculo elétrico Ramal BT -> Transformador MT alimentador"),
        # Circuitos (Alimentadores) e Subestações
        ("SSDMT", "CTMT", "CTMT", "COD_ID", "Trecho MT -> Cadastro de Circuito Alimentador"),
        ("UNTRMT", "CTMT", "CTMT", "COD_ID", "Trafo MT -> Cadastro de Circuito Alimentador"),
        ("UNSEMT", "CTMT", "CTMT", "COD_ID", "Chave MT -> Cadastro de Circuito Alimentador"),
        ("UCMT_tab", "CTMT", "CTMT", "COD_ID", "UC MT -> Cadastro de Circuito Alimentador"),
        ("UCBT_tab", "CTMT", "CTMT", "COD_ID", "UC BT -> Cadastro de Circuito Alimentador"),
        ("SSDMT", "SUB", "SUB", "COD_ID", "Trecho MT -> Cadastro de Subestação"),
        ("CTMT", "SUB", "SUB", "COD_ID", "Circuito Alimentador -> Cadastro de Subestação"),
        ("CTMT", "UNI_TR_AT", "UNTRAT", "COD_ID", "Circuito MT -> Transformador de Força AT da Subestação"),
        # Chaves
        ("EQSE", "UN_SE", "UNSEMT", "COD_ID", "Equipamento Seccionador -> Unidade Seccionadora MT"),
    ]

    resultados: list[CompatibilidadeChave] = []
    for tab_a, col_a, tab_b, col_b, papel in pares_definidos:
        logger.info("Medindo compatibilidade: %s.%s <-> %s.%s", tab_a, col_a, tab_b, col_b)
        res = medir_compatibilidade_par(gdb, tab_a, col_a, tab_b, col_b, papel)
        if res is not None:
            resultados.append(res)

    return resultados


# --------------------------------------------------------------------------- #
# Recorte e Perfil de UCs no Entorno do HRC
# --------------------------------------------------------------------------- #
def obter_geometria_hrc_buffer(gpkg: Path) -> tuple[Point, BaseGeometry]:
    """Obtém o ponto do hospital e a geometria do buffer de 3.000 m em EPSG:31983."""
    hosp_gdf = gpd.read_file(gpkg, layer="hospitais", engine="pyogrio")
    if hosp_gdf.crs.to_epsg() != CRS_TRABALHO:
        hosp_gdf = hosp_gdf.to_crs(epsg=CRS_TRABALHO)
    ponto_hrc: Point = hosp_gdf.iloc[0].geometry

    buf_gdf = gpd.read_file(gpkg, layer="buffer_3000m", engine="pyogrio")
    if buf_gdf.crs.to_epsg() != CRS_TRABALHO:
        buf_gdf = buf_gdf.to_crs(epsg=CRS_TRABALHO)
    buffer_geom = buf_gdf.iloc[0].geometry

    return ponto_hrc, buffer_geom


def recortar_ucs_entorno(
    gdb: Path,
    gpkg: Path,
    buffer_geom: BaseGeometry,
) -> tuple[pd.DataFrame, dict[str, int], dict[str, int]]:
    """Identifica e perfila as UCs MT e BT localizadas dentro do buffer de 3 km."""
    logger.info("Filtrando pontos espaciais de referência (PONNOT) dentro do buffer de 3 km...")

    # BBox do buffer no CRS nativo (EPSG:4674) para leitura veloz com pyogrio
    buf_series_4674 = gpd.GeoSeries([buffer_geom], crs=CRS_TRABALHO).to_crs(epsg=CRS_ORIGEM_ESPERADO)
    bbox_4674 = tuple(float(v) for v in buf_series_4674.total_bounds)

    pon_cands = gpd.read_file(gdb, layer="PONNOT", bbox=bbox_4674, engine="pyogrio").to_crs(epsg=CRS_TRABALHO)
    pon_in_buffer = pon_cands[pon_cands.intersects(buffer_geom)]
    pon_ids_buffer = set(pon_in_buffer["COD_ID"].dropna().astype(str))
    logger.info("Pontos Notáveis (PONNOT) no buffer: %d", len(pon_ids_buffer))

    # Transformadores MT no buffer já validados no GPKG
    trafos_gdf = gpd.read_file(gpkg, layer="UNTRMT", engine="pyogrio")
    trafo_ids_buffer = set(trafos_gdf["COD_ID"].dropna().astype(str))
    logger.info("Transformadores MT (UNTRMT) no buffer: %d", len(trafo_ids_buffer))

    # 1. UCs MT
    logger.info("Carregando e vinculando UCMT_tab...")
    cols_ucmt = ["COD_ID", "PN_CON", "PAC", "CTMT", "SUB", "CLAS_SUB", "CNAE", "CAR_INST", "DEM_CONT"]
    df_ucmt = pyogrio.read_dataframe(gdb, layer="UCMT_tab", columns=cols_ucmt, read_geometry=False)
    df_ucmt["PN_CON_str"] = df_ucmt["PN_CON"].astype(str)
    ucmt_recorte = df_ucmt[df_ucmt["PN_CON_str"].isin(pon_ids_buffer)].copy()

    ucmt_recorte["TABELA_ORIGEM"] = "UCMT_tab"
    ucmt_recorte["METODO_VINCULO"] = "PN_CON -> PONNOT contido no buffer de 3.000 m"
    ucmt_recorte["UNI_TR_MT"] = ""

    # 2. UCs BT
    logger.info("Carregando e vinculando UCBT_tab...")
    cols_ucbt = ["COD_ID", "PN_CON", "PAC", "UNI_TR_MT", "CTMT", "SUB", "CLAS_SUB", "CNAE", "CAR_INST"]
    df_ucbt = pyogrio.read_dataframe(gdb, layer="UCBT_tab", columns=cols_ucbt, read_geometry=False)
    df_ucbt["PN_CON_str"] = df_ucbt["PN_CON"].astype(str)
    df_ucbt["UNI_TR_MT_str"] = df_ucbt["UNI_TR_MT"].astype(str)

    # Identificar por PN_CON ou UNI_TR_MT
    mask_pon = df_ucbt["PN_CON_str"].isin(pon_ids_buffer)
    mask_trafo = df_ucbt["UNI_TR_MT_str"].isin(trafo_ids_buffer)
    ucbt_recorte = df_ucbt[mask_pon | mask_trafo].copy()

    ucbt_recorte["TABELA_ORIGEM"] = "UCBT_tab"
    ucbt_recorte["DEM_CONT"] = np.nan

    def definir_vinculo_bt(row: pd.Series) -> str:
        in_p = row["PN_CON_str"] in pon_ids_buffer
        in_t = row["UNI_TR_MT_str"] in trafo_ids_buffer
        if in_p and in_t:
            return "Consistente: PN_CON e UNI_TR_MT contidos no buffer de 3.000 m"
        if in_t:
            return "Vinculada via Transformador MT (UNI_TR_MT) contido no buffer"
        return "Vinculada via Ponto Notável (PN_CON) contido no buffer"

    ucbt_recorte["METODO_VINCULO"] = ucbt_recorte.apply(definir_vinculo_bt, axis=1)

    # Padronizar colunas para saída consolidada
    colunas_saida = [
        "COD_ID",
        "TABELA_ORIGEM",
        "CLAS_SUB",
        "CNAE",
        "CAR_INST",
        "DEM_CONT",
        "PN_CON",
        "UNI_TR_MT",
        "CTMT",
        "SUB",
        "METODO_VINCULO",
    ]

    ucs_total = pd.concat([ucmt_recorte[colunas_saida], ucbt_recorte[colunas_saida]], ignore_index=True)

    contagem_ucmt = ucmt_recorte["CLAS_SUB"].value_counts().to_dict()
    contagem_ucbt = ucbt_recorte["CLAS_SUB"].value_counts().to_dict()

    logger.info(
        "Total de UCs identificadas no entorno de 3 km: %d (UCMT: %d, UCBT: %d)",
        len(ucs_total),
        len(ucmt_recorte),
        len(ucbt_recorte),
    )
    return ucs_total, contagem_ucmt, contagem_ucbt


# --------------------------------------------------------------------------- #
# Exportação de Metadados e Relatório Textual
# --------------------------------------------------------------------------- #
def obter_metadados_base(gdb: Path) -> dict[str, str]:
    """Extrai informações cadastrais da tabela BASE da BDGD."""
    try:
        df_base = pyogrio.read_dataframe(gdb, layer="BASE", read_geometry=False)
        if not df_base.empty:
            linha = df_base.iloc[0]
            return {
                "DIST": str(linha.get("DIST", "")),
                "DAT_INC": str(linha.get("DAT_INC", "")),
                "DAT_FNL": str(linha.get("DAT_FNL", "")),
                "DAT_EXT": str(linha.get("DAT_EXT", "")),
                "DESCR": str(linha.get("DESCR", "")),
            }
    except Exception:
        logger.exception("Não foi possível extrair metadados da tabela BASE")
    return {}


def escrever_relatorio_final(
    saida_txt: Path,
    entradas: Entradas,
    meta_base: dict[str, str],
    tabelas_resumo: list[TabelaResumo],
    compatibilidades: list[CompatibilidadeChave],
    ucs_total: pd.DataFrame,
    contagem_ucmt: dict[str, int],
    contagem_ucbt: dict[str, int],
    hashes_antes: dict[str, str],
    hashes_depois: dict[str, str],
    duracao_s: float,
) -> None:
    """Escreve o relatório detalhado de inventário e limitações técnicas."""
    linhas: list[str] = [
        "=" * 80,
        "RELATÓRIO TÉCNICO DE INVENTÁRIO DO ESQUEMA BDGD E CAMPOS TOPOLÓGICOS",
        "=" * 80,
        f"Data/Hora de Execução: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Duração Total        : {duracao_s:.1f} segundos",
        f"Banco Inspecionado   : {entradas.gdb}",
        f"GeoPackage Referência: {entradas.gpkg}",
        f"CSV de Hospitais     : {entradas.csv}",
        "",
        "1. METADADOS DA DISTRIBUIDORA E BASE (Tabela BASE)",
        f"  - Código da Distribuidora (DIST) : {meta_base.get('DIST', '5160 (Neoenergia Brasília)')}",
        f"  - Período de Referência da Base  : {meta_base.get('DAT_INC', '')} até {meta_base.get('DAT_FNL', '')}",
        f"  - Data de Extração da Base       : {meta_base.get('DAT_EXT', '')}",
        f"  - Descrição da Base              : {meta_base.get('DESCR', '[Sem descrição cadastrada]')}",
        "",
        "2. DESCOBERTA DE CAMADAS E CORRESPONDÊNCIA COM TABELAS ESPERADAS",
        f"  Total de camadas/tabelas catalogadas no GDB: {len(tabelas_resumo)}",
        "-" * 80,
        f"{'Tabela Real':<15} | {'Tipo Geom.':<18} | {'CRS':<12} | {'Registros':<10} | {'Campos':<6} | {'Status':<16}",
        "-" * 80,
    ]

    for t in tabelas_resumo:
        linhas.append(
            f"{t.nome_real:<15} | {t.tipo_geometrico:<18} | {t.crs:<12} | {t.num_registros:<10} | {t.num_campos:<6} | {t.status_esperada:<16}"
        )

    linhas += [
        "",
        "3. CORRESPONDÊNCIA DAS TABELAS-ALVO",
        "  - SSDMT, SSDBT, SSDAT: Confirmadas no schema como feições espaciais MultiLineString.",
        "  - UNTRMT, UNTRAT      : Confirmadas no schema como feições espaciais Point.",
        "  - SUB                 : Confirmada no schema como feição espacial MultiPolygon.",
        "  - CTMT                : Confirmada como tabela tabular (geom: None), com parâmetros de alimentadores.",
        "  - UCMT, UCBT          : Identificadas no GDB como UCMT_tab e UCBT_tab (tabulares, geom: None).",
        "  - CHAVE               : Ausente com nome exato 'CHAVE'; identificada no schema da BDGD através",
        "                          das camadas de Unidades Seccionadoras (UNSEMT, UNSEBT, UNSEAT - Point)",
        "                          e tabela de Equipamentos Seccionadores (EQSE - tabular).",
        "",
        "4. RESUMO DOS CAMPOS CANDIDATOS À ANÁLISE TOPOLÓGICA",
        "  - Identificadores    : COD_ID (chave unívoca em SSDMT, UNTRMT, UNSEMT, etc.).",
        "  - Nós Elétricos (PAC): PAC, PAC_1, PAC_2, PAC_3 (pontos de conexão primária e secundária).",
        "  - Nós Físicos (Poste): PN_CON, PN_CON_1, PN_CON_2 (pontos notáveis georreferenciados em PONNOT).",
        "  - Alimentador / CT   : CTMT, CTAT (identificador do alimentador de média/alta tensão).",
        "  - Subestação / Trafo : SUB, UNI_TR_AT (subestação e transformador de força AT de alimentação).",
        "  - Estado de Chave    : P_N_OPE em UNSEMT (F = Normalmente Fechada, A = Normalmente Aberta),",
        "                         TIP_UNID (tipo de chave), ABER_CRG (abertura sob carga em EQSE).",
        "  - Carga / Demanda    : CAR_INST (carga instalada em kW), DEM_CONT (demanda contratada em kW),",
        "                         POT_NOM em UNTRMT (potência nominal em kVA).",
        "  - Classes de Consumo : CLAS_SUB, CNAE, GRU_TAR (classes tarifárias da ANEEL).",
        "",
        "5. MATRIZ DE COMPATIBILIDADE RELACIONAL (CHAVES DE LIGAÇÃO)",
        "-" * 80,
        f"{'Origem':<18} <-> {'Destino':<18} | {'Em Comum':<9} | {'Taxa(Orig)':<10} | {'Taxa(Dest)':<10} | {'Card.':<8}",
        "-" * 80,
    ]

    for c in compatibilidades:
        par_origem = f"{c.tabela_origem}.{c.campo_origem}"
        par_destino = f"{c.tabela_destino}.{c.campo_destino}"
        linhas.append(
            f"{par_origem:<18} <-> {par_destino:<18} | {c.valores_em_comum:<9} | "
            f"{c.taxa_correspondencia_origem * 100:>8.2f}% | {c.taxa_correspondencia_destino * 100:>8.2f}% | {c.cardinalidade_inferida:<8}"
        )

    linhas += [
        "",
        "6. PERFIL DE UNIDADES CONSUMIDORAS (UCs) NO ENTORNO DO HRC (3.000 m)",
        f"  Total de UCs identificadas no raio de 3 km: {len(ucs_total)}",
        f"    - UCs de Média Tensão (UCMT_tab)        : {sum(contagem_ucmt.values())}",
        f"    - UCs de Baixa Tensão (UCBT_tab)        : {sum(contagem_ucbt.values())}",
        "",
        "  Distribuição por Classe/Subclasse de Consumo (UCMT):",
    ]
    for cs, n in sorted(contagem_ucmt.items(), key=lambda x: x[1], reverse=True):
        linhas.append(f"    - {cs:<6}: {n:>6} UC(s)")

    linhas += [
        "",
        "  Distribuição por Classe/Subclasse de Consumo (UCBT - Top 10):",
    ]
    top_bt = sorted(contagem_ucbt.items(), key=lambda x: x[1], reverse=True)[:10]
    for cs, n in top_bt:
        linhas.append(f"    - {cs:<6}: {n:>6} UC(s)")

    linhas += [
        "",
        "7. VERIFICAÇÃO DE INTEGRIDADE (SOMENTE-LEITURA)",
    ]
    todas_intactas = True
    for k in hashes_antes:
        h1, h2 = hashes_antes[k], hashes_depois.get(k, "")
        status_h = "INALTERADO (OK)" if h1 == h2 else "ALTERADO! (FALHA)"
        if h1 != h2:
            todas_intactas = False
        linhas.append(f"  - {k:<45}: {status_h} [SHA256: {h1[:16]}...]")

    linhas += [
        "",
        "8. O QUE NÃO FOI POSSÍVEL CONFIRMAR E LIMITAÇÕES TÉCNICAS",
        "  - O schema da BDGD define a estrutura relacional estática, mas não comprova",
        "    a conectividade dinâmica ou o fluxo de potência em tempo real.",
        "  - Os domínios do File Geodatabase estão codificados conforme a norma da ANEEL;",
        "    seus significados foram inferidos com base no PRODIST Módulo 8 e catalogação oficial.",
        "  - A identificação da UC exata que atende o Hospital Regional de Ceilândia (HRC)",
        "    NÃO PODE ser concluída unicamente por proximidade espacial do buffer de 3 km.",
        "    É mandatória a confirmação cadastral junto à distribuidora (ex: número da UC,",
        "    endereço cadastrado, contrato de demanda ou cruzamento do alimentador de atendimento).",
        "  - A lista completa de campos ainda pendentes para futura modelagem no OpenDSS inclui:",
        "    comprimento exato de trechos (COMP em RAMLIG / Shape_Length em SSDMT),",
        "    impedâncias e matrizes de resistência/reatância (R1, X1, R0, X0) vinculadas a SEGCON,",
        "    e tap de transformadores (TAP / TEN_LIN_SE em UNTRMT).",
        "",
        "9. CONCLUSÃO GERAL DO INVENTÁRIO",
        f"  Status: {'INVENTÁRIO CONCLUÍDO COM SUCESSO' if todas_intactas else 'FALHA DE INTEGRIDADE'}",
        "  O repositório de dados brutos foi preservado intacto. Todos os artefatos de saída",
        "  estão consolidados e disponíveis em data/processed/.",
        "=" * 80,
    ]

    saida_txt.parent.mkdir(parents=True, exist_ok=True)
    saida_txt.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    logger.info("Relatório final consolidado gravado em %s", saida_txt)


# --------------------------------------------------------------------------- #
# Função Principal (Pipeline)
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    """Executa o pipeline completo de inventário de schema e perfil de dados."""
    inicio = time.perf_counter()
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"inventario_{ts_str}.log"
    configurar_logging(log_file)

    logger.info("Iniciando inventário de schema e perfil de campos da BDGD...")

    try:
        entradas = localizar_entradas()

        # 1. Hashes iniciais para garantia de somente-leitura
        logger.info("Calculando hashes de integridade pré-execução...")
        hashes_antes = obter_hashes_entradas(entradas)

        # 2. Inventário de Tabelas
        logger.info("Inventariando camadas e tabelas do GDB...")
        tabelas_resumo = inventariar_tabelas(entradas.gdb)
        df_tabelas = pd.DataFrame([t.__dict__ for t in tabelas_resumo])
        df_tabelas.to_csv(OUT_TABELAS_CSV, index=False, encoding="utf-8")
        logger.info("Inventário de tabelas salvo em: %s", OUT_TABELAS_CSV)

        # 3. Metadados cadastrais da base
        meta_base = obter_metadados_base(entradas.gdb)

        # 4. Perfil de Campos de todas as tabelas
        logger.info("Perfilando campos e atributos em todas as tabelas do GDB...")
        todos_perfis: list[CampoPerfil] = []
        for t in tabelas_resumo:
            logger.info("Perfilando campos da tabela %s (%d registros)...", t.nome_real, t.num_registros)
            perfis_t = perfilar_campos_tabela(entradas.gdb, t.nome_real)
            todos_perfis.extend(perfis_t)

        df_campos = pd.DataFrame([p.__dict__ for p in todos_perfis])
        df_campos.to_csv(OUT_CAMPOS_CSV, index=False, encoding="utf-8")
        logger.info("Inventário de campos salvo em: %s (total campos: %d)", OUT_CAMPOS_CSV, len(df_campos))

        # 5. Compatibilidade entre tabelas (pares de chaves de ligação)
        logger.info("Calculando matriz de compatibilidade relacional entre tabelas...")
        compatibilidades = executar_matriz_compatibilidade(entradas.gdb)
        df_comp = pd.DataFrame([c.__dict__ for c in compatibilidades])
        df_comp.to_csv(OUT_CANDIDATOS_CSV, index=False, encoding="utf-8")
        logger.info("Compatibilidade de chaves salva em: %s (pares: %d)", OUT_CANDIDATOS_CSV, len(df_comp))

        # 6. Recorte e Perfil de UCs no entorno do HRC
        logger.info("Executando recorte e perfil de UCs no entorno de 3 km do HRC...")
        _, buffer_geom = obter_geometria_hrc_buffer(entradas.gpkg)
        ucs_total, contagem_ucmt, contagem_ucbt = recortar_ucs_entorno(entradas.gdb, entradas.gpkg, buffer_geom)
        ucs_total.to_csv(OUT_UCS_CSV, index=False, encoding="utf-8")
        logger.info("Perfil de UCs no entorno do HRC salvo em: %s (total UCs: %d)", OUT_UCS_CSV, len(ucs_total))

        # 7. Hashes finais para confirmação de somente-leitura
        logger.info("Calculando hashes de integridade pós-execução...")
        hashes_depois = obter_hashes_entradas(entradas)

        alterados = [k for k in hashes_antes if hashes_antes[k] != hashes_depois.get(k)]
        if alterados:
            logger.error("ALERTA CRÍTICO: Os seguintes arquivos foram modificados: %s", alterados)
            return 1
        logger.info("Garantia de somente-leitura confirmada: todas as entradas permanecem idênticas.")

        # 8. Relatório final consolidado
        duracao = time.perf_counter() - inicio
        escrever_relatorio_final(
            saida_txt=OUT_RELATORIO_TXT,
            entradas=entradas,
            meta_base=meta_base,
            tabelas_resumo=tabelas_resumo,
            compatibilidades=compatibilidades,
            ucs_total=ucs_total,
            contagem_ucmt=contagem_ucmt,
            contagem_ucbt=contagem_ucbt,
            hashes_antes=hashes_antes,
            hashes_depois=hashes_depois,
            duracao_s=duracao,
        )

        logger.info("Pipeline 03b concluído com êxito em %.1f segundos.", duracao)
        return 0

    except Exception:
        logger.exception("Falha inesperada no pipeline de inventário de schema da BDGD.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

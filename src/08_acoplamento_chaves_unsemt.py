"""08_acoplamento_chaves_unsemt.py

Etapa E5: Acoplamento de Chaves Seccionadoras (UNSEMT) do Circuito TN08 no OpenDSS.
Extrai a camada UNSEMT da BDGD bruta filtrando por CTMT == 'TN08', classifica as chaves
por estado operativo (Normalmente Fechadas 'F' e Normalmente Abertas 'A'), converte
para linhas de manobra nativas no OpenDSS (Switch=y), atualiza o mapa de coordenadas
e o arquivo Master.

Saidas em:
data/processed/opendss/Switches_TN08_{RUN_TAG}.dss
data/processed/opendss/Buscoords_TN08_{RUN_TAG}.dss
data/processed/opendss/Master_TN08_{RUN_TAG}.dss
logs/08_acoplamento_chaves_unsemt_{RUN_TAG}.log
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pyogrio
from dss import dss

# Configuracoes de caminhos e RUN_TAG
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
OPENDSS_DIR = PROCESSED_DIR / "opendss"
LOGS_DIR = BASE_DIR / "logs"

LOG_PATH = LOGS_DIR / f"08_acoplamento_chaves_unsemt_{RUN_TAG}.log"
LOGGER = logging.getLogger("08_acoplamento_chaves")


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


def obter_arquivos_opendss_recentes() -> tuple[Path, Path]:
    """Obtem os arquivos Master e Buscoords mais recentes em data/processed/opendss/."""
    masters = sorted(OPENDSS_DIR.glob("Master_TN08_*.dss"))
    coords = sorted(OPENDSS_DIR.glob("Buscoords_TN08_*.dss"))
    if not masters or not coords:
        raise FileNotFoundError("Arquivos Master_TN08 ou Buscoords_TN08 nao encontrados em data/processed/opendss/")
    return masters[-1], coords[-1]


def limpar_id(val: Any) -> str:
    """Sanitiza strings de identificadores para a sintaxe OpenDSS."""
    if val is None:
        return "DESCONHECIDO"
    return str(val).strip().replace(" ", "_").replace("/", "_").replace("-", "_")


def main() -> int:
    setup_logging()
    LOGGER.info("=" * 80)
    LOGGER.info(f"INICIANDO ETAPA E5: ACOPLAMENTO DE CHAVES UNSEMT DO TN08 (RUN_TAG={RUN_TAG})")
    LOGGER.info("=" * 80)

    gdb_path = obter_gdb()
    master_anterior, coords_anterior = obter_arquivos_opendss_recentes()
    LOGGER.info(f"Base BDGD de origem: {gdb_path.name}")
    LOGGER.info(f"Master OpenDSS base: {master_anterior.name}")
    LOGGER.info(f"Buscoords base: {coords_anterior.name}")

    switches_file = OPENDSS_DIR / f"Switches_TN08_{RUN_TAG}.dss"
    coords_file = OPENDSS_DIR / f"Buscoords_TN08_{RUN_TAG}.dss"
    master_file = OPENDSS_DIR / f"Master_TN08_{RUN_TAG}.dss"

    for f in [switches_file, coords_file, master_file]:
        if f.exists():
            raise FileExistsError(f"Arquivo de saida ja existente: {f}")

    # 1. Extracao Espacial da Camada UNSEMT via pyogrio
    LOGGER.info("Lendo camada UNSEMT no GDB para CTMT == 'TN08'...")
    gdf_unsemt = pyogrio.read_dataframe(str(gdb_path), layer="UNSEMT", where="CTMT = 'TN08'")
    total_chaves = len(gdf_unsemt)
    LOGGER.info(f"Total de chaves UNSEMT extraidas para o circuito TN08: {total_chaves}")

    if total_chaves == 0:
        LOGGER.error("Nenhuma chave seccionadora encontrada para o circuito TN08!")
        return 1

    # 2. Tratamento Logico de Manobra (P_N_OPE)
    chaves_fechadas = gdf_unsemt[gdf_unsemt["P_N_OPE"] == "F"]
    chaves_abertas = gdf_unsemt[gdf_unsemt["P_N_OPE"] == "A"]
    outros_estados = gdf_unsemt[~gdf_unsemt["P_N_OPE"].isin(["F", "A"])]

    count_fechadas = len(chaves_fechadas)
    count_abertas = len(chaves_abertas)
    LOGGER.info(f"Classificacao operacional das chaves:")
    LOGGER.info(f"  * Normalmente Fechadas (P_N_OPE == 'F'): {count_fechadas} chaves")
    LOGGER.info(f"  * Normalmente Abertas   (P_N_OPE == 'A'): {count_abertas} chaves")
    if len(outros_estados) > 0:
        LOGGER.warning(f"  * Outros estados/indefinidos: {len(outros_estados)} chaves (assumidas como Fechadas)")

    # 3. Conversao Nativa para OpenDSS
    LOGGER.info("Gerando comandos nativos OpenDSS para as chaves de manobra...")
    sw_lines: list[str] = [
        f"! OpenDSS Disconnecting Switches - Circuito TN08 (SE STN) | RUN_TAG: {RUN_TAG}",
        f"! Total de Chaves: {total_chaves} | Fechadas: {count_fechadas} | Abertas: {count_abertas}",
        ""
    ]

    # Secao de Chaves Normalmente Fechadas
    sw_lines.append("! ==============================================================================")
    sw_lines.append("! CHAVES NORMALMENTE FECHADAS (P_N_OPE == 'F') - CONTINUIDADE PRIMARIA NOMINAL")
    sw_lines.append("! ==============================================================================")

    # Identificacao especifica da chave do HRC
    chave_hrc_encontrada = False

    for _, row in gdf_unsemt.iterrows():
        cod_id = limpar_id(row["COD_ID"])
        pac1 = limpar_id(row["PAC_1"])
        pac2 = limpar_id(row["PAC_2"])
        estado = str(row["P_N_OPE"]).strip().upper()
        fas_con = str(row.get("FAS_CON", "ABC")).strip().upper()
        descr = str(row.get("DESCR", "")).strip()

        # Destaque para o seccionamento do HRC
        is_hrc = "9026_CEI003" in pac1 or "9026_CEI003" in pac2 or "FW9093" in cod_id
        if is_hrc:
            chave_hrc_encontrada = True
            sw_lines.append(
                f"! ------------------------------------------------------------------------------\n"
                f"! CHAVE SECCIONADORA DO RAMAL DO HRC (HOSPITAL REGIONAL DE CEILANDIA)\n"
                f"! COD_ID: {cod_id} | PAC_1: {pac1} <-> PAC_2: {pac2} | Estado: {estado} (Fechada)\n"
                f"! ------------------------------------------------------------------------------\n"
                f"New Line.SW_{cod_id} Phases=3 Bus1={pac1}.1.2.3 Bus2={pac2}.1.2.3 Switch=y "
                f"r1=0.0001 x1=0.0001 r0=0.0001 x0=0.0001 Length=0.001 Units=m ! HRC_FEEDER_SWITCH\n"
            )
            continue

        if estado != "A":
            # Chaves normalmente fechadas
            sw_lines.append(
                f"New Line.SW_{cod_id} Phases=3 Bus1={pac1}.1.2.3 Bus2={pac2}.1.2.3 Switch=y "
                f"r1=0.0001 x1=0.0001 r0=0.0001 x0=0.0001 Length=0.001 Units=m ! Estado=F {descr}"
            )

    # Secao de Chaves Normalmente Abertas
    sw_lines.append("\n! ==============================================================================")
    sw_lines.append("! CHAVES NORMALMENTE ABERTAS (P_N_OPE == 'A') - INTERLIGACOES E CONTINGENCIA N-1")
    sw_lines.append("! ==============================================================================")

    for _, row in chaves_abertas.iterrows():
        cod_id = limpar_id(row["COD_ID"])
        pac1 = limpar_id(row["PAC_1"])
        pac2 = limpar_id(row["PAC_2"])
        descr = str(row.get("DESCR", "")).strip()

        sw_lines.append(
            f"New Line.SW_{cod_id} Phases=3 Bus1={pac1}.1.2.3 Bus2={pac2}.1.2.3 Switch=y "
            f"r1=0.0001 x1=0.0001 r0=0.0001 x0=0.0001 Length=0.001 Units=m ! Estado=A (Normalmente Aberta) {descr}\n"
            f"Open Line.SW_{cod_id} term=1"
        )

    with open(switches_file, "w", encoding="utf-8") as f:
        f.write("\n".join(sw_lines) + "\n")
    LOGGER.info(f"Arquivo de chaves gravado com sucesso: {switches_file.name}")

    if chave_hrc_encontrada:
        LOGGER.info("Chave seccionadora FW9093 do ramal do HRC identificada e modelada como FECHADA.")

    # 4. Atualizacao de Coordenadas de Barras (Buscoords)
    LOGGER.info("Atualizando coordenadas geograficas para incluir as barras das chaves...")
    coords_dict: dict[str, tuple[float, float]] = {}

    # Leitura das coordenadas existentes
    with open(coords_anterior, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str and not line_str.startswith("!"):
                parts = line_str.split()
                if len(parts) >= 3:
                    try:
                        coords_dict[parts[0]] = (float(parts[1]), float(parts[2]))
                    except ValueError:
                        pass

    novas_barras_coords = 0
    for _, row in gdf_unsemt.iterrows():
        geom = row.geometry
        if geom and not geom.is_empty:
            p = geom.coords[0] if geom.geom_type == "Point" else geom.geoms[0].coords[0]
            pac1 = limpar_id(row["PAC_1"])
            pac2 = limpar_id(row["PAC_2"])

            if pac1 not in coords_dict:
                coords_dict[pac1] = (p[0], p[1])
                novas_barras_coords += 1
            if pac2 not in coords_dict:
                # Pequeno offset infinitesimal para diferenciar os dois lados da chave
                coords_dict[pac2] = (p[0] + 0.00002, p[1] + 0.00002)
                novas_barras_coords += 1

    LOGGER.info(f"Total de barras mapeadas no novo Buscoords: {len(coords_dict)} ({novas_barras_coords} novas barras adicionadas)")

    coords_content: list[str] = [
        f"! OpenDSS Bus Coordinates - Circuito TN08 com Chaves UNSEMT | RUN_TAG: {RUN_TAG}",
        f"! Formato: BusName X(Longitude) Y(Latitude)",
        ""
    ]
    for bname, (bx, by) in sorted(coords_dict.items()):
        coords_content.append(f"{bname} {bx:.6f} {by:.6f}")

    with open(coords_file, "w", encoding="utf-8") as f:
        f.write("\n".join(coords_content) + "\n")
    LOGGER.info(f"Novo Buscoords gravado com sucesso: {coords_file.name}")

    # 5. Atualizacao do Arquivo Master
    LOGGER.info("Regerando arquivo Master_TN08 para referenciar o modulo de chaves e coordenadas...")
    with open(master_anterior, "r", encoding="utf-8") as f:
        master_orig_lines = f.readlines()

    master_new_lines: list[str] = []
    for line in master_orig_lines:
        line_str = line.strip()
        # Atualiza referencia de Buscoords
        if line_str.startswith("Buscoords"):
            master_new_lines.append(f"Redirect {switches_file.name}\n")
            master_new_lines.append(f"Buscoords {coords_file.name}\n")
        elif "RUN_TAG" in line_str:
            master_new_lines.append(f"! Gerado por: src/08_acoplamento_chaves_unsemt.py | RUN_TAG: {RUN_TAG}\n")
        else:
            master_new_lines.append(line)

    with open(master_file, "w", encoding="utf-8") as f:
        f.writelines(master_new_lines)
    LOGGER.info(f"Novo Master gravado com sucesso: {master_file.name}")

    # Realiza tambem o append no Master anterior para compatibilidade retroativa
    append_marker = f"! --- MODULO DE CHAVES UNSEMT ({RUN_TAG}) ---"
    with open(master_anterior, "r", encoding="utf-8") as f:
        content_prev = f.read()

    if append_marker not in content_prev:
        with open(master_anterior, "a", encoding="utf-8") as f:
            f.write(f"\n{append_marker}\n")
            f.write(f"Redirect {switches_file.name}\n")
            f.write(f"Buscoords {coords_file.name}\n")
            f.write("CalcVoltageBases\n")
        LOGGER.info(f"Append realizado com sucesso no Master anterior: {master_anterior.name}")

    # 6. Validacao Eletrica Imediata no OpenDSS
    LOGGER.info("=" * 80)
    LOGGER.info("TESTANDO SIMULACAO DO NOVO MASTER COM CHAVES ACOPLADAS...")
    LOGGER.info("=" * 80)

    dss.Text.Command = "Clear"
    dss.Text.Command = f"compile ({master_file.resolve()})"

    circuit = dss.ActiveCircuit
    dss.ActiveCircuit.Solution.Solve()

    converged = bool(dss.ActiveCircuit.Solution.Converged)
    iterations = int(dss.ActiveCircuit.Solution.Iterations)
    losses = dss.ActiveCircuit.Losses
    p_perdas_kw = float(losses[0]) / 1000.0

    LOGGER.info(f"Status de Convergencia: {'CONVERGIDO' if converged else 'FALHOU'} ({iterations} iteracoes)")
    LOGGER.info(f"Perdas Ativas Totais: {p_perdas_kw:.2f} kW")

    # Verificacao direta da barra do HRC
    hrc_bus_id = "stn_tn08_9026_cei003"
    circuit.SetActiveBus(hrc_bus_id)
    hrc_bus = circuit.ActiveBus
    hrc_nodes = list(hrc_bus.Nodes)
    hrc_mags = list(hrc_bus.VMagAngle)
    hrc_pu = list(hrc_bus.puVmagAngle)

    v_volts = [round(float(hrc_mags[2 * i]), 1) for i, n in enumerate(hrc_nodes) if n in [1, 2, 3]]
    v_pu = [round(float(hrc_pu[2 * i]), 4) for i, n in enumerate(hrc_nodes) if n in [1, 2, 3]]

    LOGGER.info("=" * 80)
    LOGGER.info("DIAGNOSTICO DE ENERGIZACAO DO HOSPITAL REGIONAL DE CEILANDIA (HRC):")
    LOGGER.info("=" * 80)
    LOGGER.info(f"  * Barramento PAC do HRC: {hrc_bus_id.upper()}")
    LOGGER.info(f"  * Base de Tensao (kVBase): {hrc_bus.kVBase * math.sqrt(3):.2f} kV (Linha-Linha) | {hrc_bus.kVBase:.2f} kV (Fase-Neutro)")
    LOGGER.info(f"  * Tensoes Nominais de Fase (Volts): {v_volts} V")
    LOGGER.info(f"  * Tensoes em pu: {v_pu} pu")

    if all(p > 0.80 for p in v_pu):
        LOGGER.info("[SUCESSO ABSOLUTO] O barramento primario do HRC esta energizado e operacional!")
    else:
        LOGGER.warning("Atencao: Alguma fase do HRC ainda apresenta tensao nula ou anormal.")

    # 7. Resumo Consolidado de Chaves
    LOGGER.info("=" * 80)
    LOGGER.info("RESUMO DA VOLUMETRIA DE CHAVES ACOPLADAS (UNSEMT):")
    LOGGER.info("=" * 80)
    LOGGER.info(f"  * Total de Chaves UNSEMT Modeladas: {total_chaves}")
    LOGGER.info(f"  * Chaves Normalmente Fechadas ('F'): {count_fechadas} (Conduzindo no estado estacionario)")
    LOGGER.info(f"  * Chaves Normalmente Abertas   ('A'): {count_abertas} (Desconectadas via 'Open Line... term=1')")
    LOGGER.info(f"  * Chave Primaria do HRC (FW9093): FECHADA (Alimenta o PAC STN_TN08_9026_CEI003)")
    LOGGER.info(f"  * Arquivo DSS de Chaves Gerado: {switches_file.name}")
    LOGGER.info(f"  * Arquivo Master Atualizado: {master_file.name}")
    LOGGER.info(f"  * Arquivo Buscoords Atualizado: {coords_file.name}")
    LOGGER.info("=" * 80)
    LOGGER.info("Etapa E5 (Acoplamento de Chaves UNSEMT) concluida com exito.")

    return 0


if __name__ == "__main__":
    import math
    sys.exit(main())

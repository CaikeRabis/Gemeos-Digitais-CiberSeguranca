"""07_validacao_baseline_eletrica.py

Etapa E5: Suíte de Smoke Tests e Validação de Baseline Elétrica do Circuito TN08 (SE STN).
Inicializa o OpenDSS via dss-python, compila o arquivo Master mais recente em data/processed/opendss/,
resolve o fluxo de potência em regime nominal e executa auditorias de qualidade:
1. Teste 1: Convergência do Fluxo de Potência (Solution.Converged)
2. Teste 2: Regulação de Tensão ANEEL PRODIST (0.93 <= V <= 1.05 pu)
3. Teste 3: Sobrecarga Térmica de Linhas e Transformadores (> 100%)
4. Teste 4: Balanço de Potência e Eficiência (% de Perdas Técnicas)

Saída em:
logs/07_validacao_baseline_eletrica_{RUN_TAG}.log
"""

from __future__ import annotations

import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dss import dss

# Configuracao de caminhos e RUN_TAG
RUN_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
BASE_DIR = Path(__file__).resolve().parent.parent
OPENDSS_DIR = BASE_DIR / "data" / "processed" / "opendss"
LOGS_DIR = BASE_DIR / "logs"

LOG_PATH = LOGS_DIR / f"07_validacao_baseline_eletrica_{RUN_TAG}.log"
LOGGER = logging.getLogger("07_validacao_baseline")


def setup_logging() -> None:
    """Configura logging simultaneo no console e arquivo com UTF-8."""
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


def obter_arquivo_master() -> Path:
    """Identifica o arquivo Master_TN08 mais recente em data/processed/opendss/."""
    masters = sorted(OPENDSS_DIR.glob("Master_TN08_*.dss"))
    if not masters:
        raise FileNotFoundError(f"Nenhum arquivo Master_TN08_*.dss encontrado em {OPENDSS_DIR}")
    return masters[-1]


def main() -> int:
    setup_logging()
    LOGGER.info("=" * 80)
    LOGGER.info(f"INICIANDO ETAPA E5: SUITE DE SMOKE TESTS E VALIDACAO DE BASELINE ELETRICA (RUN_TAG={RUN_TAG})")
    LOGGER.info("=" * 80)

    # Identificacao da versao do motor OpenDSS
    version_info = getattr(dss, "Version", "DSS C-API")
    LOGGER.info(f"Motor OpenDSS Carregado: {version_info.strip()}")

    master_file = obter_arquivo_master()
    LOGGER.info(f"Arquivo Master para compilacao: {master_file.name}")

    # Inicializacao e compilacao
    dss.Text.Command = "Clear"
    dss.Text.Command = f"compile ({master_file.resolve()})"

    circuit = getattr(dss, "ActiveCircuit", None) or getattr(dss, "Circuit", None)
    if circuit is None:
        LOGGER.error("Falha critica: O circuito nao foi instanciado pelo OpenDSS.")
        return 1

    LOGGER.info(f"Circuito compilado com sucesso: {circuit.Name.upper()}")
    LOGGER.info(f"Total de Barras: {circuit.NumBuses} | Total de Elementos de Circuito: {circuit.NumCktElements}")

    # --------------------------------------------------------------------------
    # TESTE 1: RESOLUCAO E CONVERGENCIA DO FLUXO DE POTENCIA
    # --------------------------------------------------------------------------
    LOGGER.info("-" * 80)
    LOGGER.info("TESTE 1: RESOLUCAO E CONVERGENCIA DO FLUXO DE POTENCIA (SNAPSHOT)")
    LOGGER.info("-" * 80)

    solution = getattr(circuit, "Solution", None) or getattr(dss, "Solution", None)
    if solution is None:
        LOGGER.error("Falha critica: Interface de solucao nao disponivel.")
        return 1

    solution.Solve()
    converged = bool(solution.Converged)
    iterations = int(solution.Iterations)

    if not converged:
        LOGGER.error(f"[TESTE 1 FALHOU] O fluxo de potencia NAO convergiu apos {iterations} iteracoes!")
        return 1

    LOGGER.info(f"[TESTE 1 APROVADO] Fluxo de potencia convergiu com sucesso em {iterations} iteracoes.")

    # --------------------------------------------------------------------------
    # TESTE 2: AUDITORIA DE PERFIL DE TENSAO (REGULACAO ANEEL PRODIST)
    # --------------------------------------------------------------------------
    LOGGER.info("-" * 80)
    LOGGER.info("TESTE 2: AUDITORIA DO PERFIL DE TENSAO (NORMATIVA ANEEL PRODIST: 0.93 <= V <= 1.05 pu)")
    LOGGER.info("-" * 80)

    all_bus_names = circuit.AllBusNames
    node_pu_list: list[tuple[str, int, float, float]] = []  # (bus, node, pu, kvbase)
    violation_under_093: list[tuple[str, int, float, float]] = []
    violation_over_105: list[tuple[str, int, float, float]] = []

    for bname in all_bus_names:
        circuit.SetActiveBus(bname)
        active_bus = circuit.ActiveBus
        kv_base = float(active_bus.kVBase)
        nodes = list(active_bus.Nodes)
        mag_ang = list(active_bus.puVmagAngle)

        for i, node in enumerate(nodes):
            if node in [1, 2, 3]:  # Fases ativas
                pu_val = float(mag_ang[2 * i])
                if pu_val > 0.05:  # Filtra nos desenergizados ou de retorno
                    node_pu_list.append((bname, node, pu_val, kv_base))
                    if pu_val < 0.93:
                        violation_under_093.append((bname, node, pu_val, kv_base))
                    elif pu_val > 1.05:
                        violation_over_105.append((bname, node, pu_val, kv_base))

    total_nos_analisados = len(node_pu_list)
    if total_nos_analisados == 0:
        LOGGER.error("Nenhum no ativo encontrado para auditoria de tensao.")
        return 1

    pus_only = [x[2] for x in node_pu_list]
    v_min = min(pus_only)
    v_max = max(pus_only)

    LOGGER.info(f"Total de nos de fase analisados: {total_nos_analisados}")
    LOGGER.info(f"Tensao Minima Absoluta: {v_min:.4f} pu")
    LOGGER.info(f"Tensao Maxima Absoluta: {v_max:.4f} pu")
    LOGGER.info(f"Nos com Subtensao (V < 0.93 pu): {len(violation_under_093)} ({len(violation_under_093)/total_nos_analisados*100:.2f}%)")
    LOGGER.info(f"Nos com Sobretensao (V > 1.05 pu): {len(violation_over_105)} ({len(violation_over_105)/total_nos_analisados*100:.2f}%)")

    # Auditoria especifica da barra do HRC
    hrc_bus_target = "stn_tn08_9026_cei003"
    circuit.SetActiveBus(hrc_bus_target)
    hrc_bus = circuit.ActiveBus
    hrc_nodes = list(hrc_bus.Nodes)
    hrc_mag_ang = list(hrc_bus.puVmagAngle)
    hrc_pus = [float(hrc_mag_ang[2 * i]) for i, n in enumerate(hrc_nodes) if n in [1, 2, 3]]
    LOGGER.info(f"Tensao nas Fases do PAC do HRC ({hrc_bus_target.upper()}): {[round(p, 4) for p in hrc_pus]} pu")

    if any(p < 0.93 or p > 1.05 for p in hrc_pus):
        LOGGER.warning(f"PAC do HRC opera fora da faixa ideal ANEEL (0.93 - 1.05 pu) no baseline nominal.")
    else:
        LOGGER.info(f"[HRC CONFORME] PAC do HRC opera rigorosamente dentro dos padroes ANEEL PRODIST.")

    LOGGER.info(f"[TESTE 2 CONCLUIDO] Perfil de tensao quantificado conforme diretrizes ANEEL.")

    # --------------------------------------------------------------------------
    # TESTE 3: AUDITORIA DE CARREGAMENTO (LOADING DE LINHAS E TRAFOS)
    # --------------------------------------------------------------------------
    LOGGER.info("-" * 80)
    LOGGER.info("TESTE 3: AUDITORIA DE CARREGAMENTO E SOBRECARGA (> 100% DA CAPACIDADE)")
    LOGGER.info("-" * 80)

    # 3.1 Linhas
    lines = circuit.Lines
    total_lines = int(lines.Count)
    overloaded_lines: list[tuple[str, float, float, float]] = []  # (name, max_i, norm_amps, loading_pct)
    all_lines_loading: list[tuple[str, float, float, float]] = []

    lines.First
    for _ in range(total_lines):
        lname = lines.Name
        norm_amps = float(lines.NormAmps)
        currents = list(circuit.ActiveCktElement.CurrentsMagAng)
        n_cond = int(circuit.ActiveCktElement.NumConductors)
        mags_term1 = [float(currents[2 * i]) for i in range(n_cond)]
        max_i = max(mags_term1) if mags_term1 else 0.0
        loading_pct = (max_i / norm_amps * 100.0) if norm_amps > 0 else 0.0

        all_lines_loading.append((lname, max_i, norm_amps, loading_pct))
        if loading_pct > 100.0:
            overloaded_lines.append((lname, max_i, norm_amps, loading_pct))
        lines.Next

    # 3.2 Transformadores
    trafos = circuit.Transformers
    total_trafos = int(trafos.Count)
    overloaded_trafos: list[tuple[str, float, float, float]] = []  # (name, total_s, kva, loading_pct)
    all_trafos_loading: list[tuple[str, float, float, float]] = []

    trafos.First
    for _ in range(total_trafos):
        tname = trafos.Name
        kva_nom = float(trafos.kva)
        powers = list(circuit.ActiveCktElement.Powers)
        n_phases = int(circuit.ActiveCktElement.NumPhases)
        total_s = sum(
            math.sqrt(float(powers[2 * p]) ** 2 + float(powers[2 * p + 1]) ** 2)
            for p in range(n_phases)
        )
        loading_pct = (total_s / kva_nom * 100.0) if kva_nom > 0 else 0.0

        all_trafos_loading.append((tname, total_s, kva_nom, loading_pct))
        if loading_pct > 100.0:
            overloaded_trafos.append((tname, total_s, kva_nom, loading_pct))
        trafos.Next

    LOGGER.info(f"Total de Linhas Auditadas: {total_lines}")
    LOGGER.info(f"Linhas Sobrecarregadas (> 100%): {len(overloaded_lines)} ({len(overloaded_lines)/total_lines*100:.2f}%)")
    LOGGER.info(f"Total de Transformadores Auditados: {total_trafos}")
    LOGGER.info(f"Transformadores Sobrecarregados (> 100%): {len(overloaded_trafos)} ({len(overloaded_trafos)/total_trafos*100:.2f}%)")

    # Top 5 Linhas mais carregadas
    LOGGER.info("Top 5 Linhas Mais Carregadas:")
    for name, i_max, i_nom, pct in sorted(all_lines_loading, key=lambda x: x[3], reverse=True)[:5]:
        LOGGER.info(f"  * Line.{name}: {pct:.2f}% (I_max={i_max:.1f} A | I_nom={i_nom:.1f} A)")

    # Top 5 Transformadores mais carregados
    LOGGER.info("Top 5 Transformadores Mais Carregados:")
    for name, s_tot, s_nom, pct in sorted(all_trafos_loading, key=lambda x: x[3], reverse=True)[:5]:
        LOGGER.info(f"  * Trafo.{name}: {pct:.2f}% (S={s_tot:.1f} kVA | Nominal={s_nom:.1f} kVA)")

    LOGGER.info(f"[TESTE 3 CONCLUIDO] Carregamento termico dos ativos mapeado.")

    # --------------------------------------------------------------------------
    # TESTE 4: BALANCO DE POTENCIA E PERDAS TECNICAS
    # --------------------------------------------------------------------------
    LOGGER.info("-" * 80)
    LOGGER.info("TESTE 4: BALANCO DE POTENCIA E EFICIENCIA DA REDE")
    LOGGER.info("-" * 80)

    # Potencia total da subestacao
    tot_power = list(circuit.TotalPower)
    p_injetada_kw = -float(tot_power[0])
    q_injetada_kvar = -float(tot_power[1])

    # Perdas totais do circuito
    losses = list(circuit.Losses)
    p_perdas_kw = float(losses[0]) / 1000.0
    q_perdas_kvar = float(losses[1]) / 1000.0

    pct_perdas = (p_perdas_kw / p_injetada_kw * 100.0) if p_injetada_kw > 0 else 0.0
    p_consumo_liquido_kw = p_injetada_kw - p_perdas_kw

    LOGGER.info(f"Potencia Ativa Injetada na SE STN: {p_injetada_kw:.2f} kW ({p_injetada_kw/1000.0:.2f} MW)")
    LOGGER.info(f"Potencia Reativa Injetada na SE STN: {q_injetada_kvar:.2f} kVAr ({q_injetada_kvar/1000.0:.2f} MVAr)")
    LOGGER.info(f"Potencia Liquida Consumida pelas Cargas: {p_consumo_liquido_kw:.2f} kW ({p_consumo_liquido_kw/1000.0:.2f} MW)")
    LOGGER.info(f"Perdas Tecnicas Ativas: {p_perdas_kw:.2f} kW ({p_perdas_kw/1000.0:.2f} MW)")
    LOGGER.info(f"Perdas Tecnicas Reativas: {q_perdas_kvar:.2f} kVAr ({q_perdas_kvar/1000.0:.2f} MVAr)")
    LOGGER.info(f"Percentual de Perdas Tecnicas: {pct_perdas:.2f}%")

    # Asserts de consistencia fisica
    if p_injetada_kw <= 0:
        LOGGER.error(f"[TESTE 4 FALHOU] Injecao de potencia ativa invalida ({p_injetada_kw:.2f} kW).")
        return 1
    if p_perdas_kw < 0:
        LOGGER.error(f"[TESTE 4 FALHOU] Perdas ativas negativas ({p_perdas_kw:.2f} kW).")
        return 1

    LOGGER.info(f"[TESTE 4 APROVADO] Balanco de potencia consistente e fisicamente realizavel.")

    # --------------------------------------------------------------------------
    # RELATORIO SINTETICO DE SAUDE DA REDE
    # --------------------------------------------------------------------------
    LOGGER.info("=" * 80)
    LOGGER.info("RELATORIO SINTETICO DE SAUDE DA REDE (BASELINE TN08 - OPENDSS):")
    LOGGER.info("=" * 80)
    LOGGER.info(f"  * Status de Convergencia: APROVADO ({iterations} iteracoes)")
    LOGGER.info(f"  * Faixa de Tensao Global: [{v_min:.4f} pu, {v_max:.4f} pu]")
    LOGGER.info(f"  * Violacoes de Tensao ANEEL: {len(violation_under_093)} subtensao | {len(violation_over_105)} sobretensao")
    LOGGER.info(f"  * Ativos em Sobrecarga (>100%): {len(overloaded_lines)} linhas ({len(overloaded_lines)/total_lines*100:.1f}%) | {len(overloaded_trafos)} trafos ({len(overloaded_trafos)/total_trafos*100:.1f}%)")
    LOGGER.info(f"  * Injecao na Subestacao STN: {p_injetada_kw:.2f} kW ({p_injetada_kw/1000.0:.2f} MW)")
    LOGGER.info(f"  * Eficiencia e Perdas: {pct_perdas:.2f}% de perdas tecnicas ({p_perdas_kw:.2f} kW)")
    LOGGER.info(f"  * Tensao no PAC do HRC: {[round(p, 4) for p in hrc_pus]} pu")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Artefato de log gravado em: {LOG_PATH}")
    LOGGER.info(f"Etapa E5 (Validacao Baseline Eletrica) concluida com exito.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

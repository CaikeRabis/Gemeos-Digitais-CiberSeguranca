# Inventário Técnico do Sistema Atual — Zona 1 (Ceilândia/DF)
## Modelos Preditivos na Rede Elétrica do DF (Cibersegurança e Redes Inteligentes)

---

### Metadados do Inventário
* **Projeto:** Modelos Preditivos na Rede Elétrica do DF — Infraestruturas Críticas em Redes Inteligentes
* **Ambiente Analisado:** Zona 1 (Ceilândia / Taguatinga) — Concessionária Neoenergia Brasília
* **Data da Varredura Técnica:** 19 de Outubro de 2026
* **Ambiente de Execução Python:** `Python 3.13.3 (venv)` com `dss-python`, `geopandas`, `pyogrio`, `shapely`, `folium`, `matplotlib`, `pandas`, `numpy`
* **Localização no Repositório:** `consolidacao_resultados_HRC_delegacia_ambiente_1/2_Inventario_Sistema_Atual.md`

---

## 1. Capacidades e Funcionalidades Atuais do Sistema

O ecossistema de software desenvolvido para o projeto consolidou uma esteira analítica e eletrotécnica de ponta a ponta, capaz de processar bases geoespaciais massivas de concessionárias e convertê-las em modelos de simulação cibernética e de potência:

1. **Deduplicação Determinística da BDGD da ANEEL:**
   * Algoritmo de resolução de duplicidades cadastrais em bases brutas da distribuidora (File Geodatabase - GDB com centenas de gigabytes).
   * Identificação e tratamento de baldes de divergência de atributos, preservando unicidade de Unidades Consumidoras sem perda de metadados críticos (`CNAE`, `PAC`, `CTMT`, `CAR_INST`, faturamento histórico).

2. **Extração e Acoplamento Topológico de Redes de Média e Baixa Tensão:**
   * Mineração vetorial via `pyogrio` e `geopandas` dos circuitos alimentadores alvos (`TN08` e `CN07`).
   * Acoplamento topológico entre trechos de condutores primários (`SSDMT`), secundários (`SSDBT`), transformadores de distribuição (`UNTRMT`), parâmetros de condutores (`SEGCON`) e equipamentos de transformação (`EQTRMT`).
   * Rastreamento e injeção do estado operacional de chaves seccionadoras de média tensão (`UNSEMT`), discriminando chaves normalmente fechadas (`P_N_OPE = 'F'`) e chaves de manobra normalmente abertas (`P_N_OPE = 'A'`).

3. **Conversor Automatizado para OpenDSS (.dss):**
   * Sintaxe nativa do OpenDSS (EPRI) gerada via código Python modularizado:
     * `Master_*.dss`: Definição de fontes equivalentes (`Vsource`), bases de tensão, parâmetros de solução Newton-Raphson e direcionamento modular (`Redirect`).
     * `Lines_*.dss`: Modelagem de condutores com matrizes de impedância de sequência positiva e zero ($R_1, X_1, R_0, X_0$) ou códigos de cabo (`LineCode`), distâncias físicas e fases (`Phases=3` ou monofásicas).
     * `Transformers_*.dss`: Transformadores de subestação e distribuição com perdas no ferro (`%noloadloss`), perdas no cobre (`%loadloss`), reatância de dispersão (`XHL`) e conexões Delta/Estrela com neutro aterrado.
     * `Switches_*.dss`: Chaves seccionadoras modeladas como linhas de impedância infinitesimal e alta capacidade de corrente para fechamento da continuidade da malha.
     * `Buscoords_*.dss`: Coordenadas cartesianas/geográficas de cada barra para georreferenciamento de circuitos.

4. **Injeção de Fator de Coincidência ($F_c$) em Cargas de Baixa Tensão:**
   * Superação do artefato matemático de colapso de tensão causado pela soma de potências instaladas brutas.
   * Aplicação da fórmula de demanda de pico realística:
     $$\text{kW}_{\text{pico}} = \max\left(\frac{\text{ENE\_MEDIO}}{730} \times 1.5, \ 0.05\right)$$
     baseada nos 12 meses de consumo faturado (`ENE_01` a `ENE_12`).

5. **Regulação Ativa de Tensão na Subestação:**
   * Ajuste fino de taps dos transformadores de subestação (ex: tap $1.008$ no `T-1_STN`) e regulação da barra de alta tensão ($138\text{ kV}$) em $1.04\text{ pu}$, compensando quedas de tensão no alimentador primário de 13,8 kV.

6. **Auditoria Regulatória de Conformidade PRODIST (ANEEL Módulo 8):**
   * Classificação em tempo de execução das tensões nodais por fase:
     * `[ADEQUADA]` ($0.93 \le V \le 1.05\text{ pu}$)
     * `[PRECÁRIA]` ($0.87 \le V < 0.93\text{ pu}$ ou $1.05 < V \le 1.06\text{ pu}$)
     * `[CRÍTICA]` ($V < 0.87\text{ pu}$ ou $V > 1.06\text{ pu}$)
   * Cálculo de desbalanço percentual entre fases e métricas globais de perdas técnicas ($P_{\text{loss}}, Q_{\text{loss}}$).

7. **Renderização Geoespacial e Resiliência a Bloqueios de Provedor (GIS):**
   * Mapas estáticos vetoriais em alta resolução (300 DPI) com biblioteca `matplotlib` destacando topologia e pontos de acoplamento comum (PACs).
   * Mapas interativos georreferenciados via `folium` (HTML/Leaflet) com popups dinâmicos contendo diagnóstico de tensão.
   * **Solução Definitiva para Bloqueios HTTP 403:** Migração e padronização do basemap para a camada de satélite pública **Esri World Imagery** (`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`), eliminando os bloqueios de User-Agent do OpenStreetMap e de API key do CartoDB.

8. **Rastreamento de Infraestruturas Críticas por CNAE:**
   * Filtro automatizado de estabelecimentos prioritários de Saúde (`CNAE 8610-1/01`) e Segurança Pública (`CNAE 8424-8/00`), comprovando isolamento ou compartilhamento topológico de alimentadores.

---

## 2. Bases de Dados Consolidadas

As bases consolidadas residem no diretório [`data/processed/`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/) e foram geradas a partir da BDGD bruta da Neoenergia Brasília (`data/raw/Neoenergia_Brasilia_5160_2025-12-31_V11_20260821-0031.gdb`):

| Arquivo de Dados | Formato | Tamanho em Disco | Total de Registros | Colunas | Descrição e Finalidade |
| :--- | :---: | :---: | :---: | :---: | :--- |
| [`UCMT_consolidada_20261018_131447.csv`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/UCMT_consolidada_20261018_131447.csv) | CSV (UTF-8) | 2,84 MB (2.980.250 bytes) | **5.609 UCs** | 76 | Universo completo de Unidades Consumidoras de Média Tensão (13,8 kV) do DF deduplicadas. Contém HRC e 15ª DP. |
| [`UCBT_consolidada_20261018_131447.csv`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/UCBT_consolidada_20261018_131447.csv) | CSV (UTF-8 com BOM) | 515,02 MB (540.038.185 bytes) | **1.183.916 UCs** | 76 | Universo integral de Unidades Consumidoras de Baixa Tensão do DF. Contém série histórica `ENE_01` a `ENE_12`. |
| [`seguranca_ceilandia_topologia_20261019_123616.json`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/seguranca_ceilandia_topologia_20261019_123616.json) | JSON | 3,13 KB (3.130 bytes) | 3 Unidades Policiais | — | Mapeamento relacional de Segurança Pública em Ceilândia (15ª DP, 19ª DP, 24ª DP) e comprovação de segregação frente ao HRC. |

---

## 3. Artefatos Geoespaciais (GIS)

Os artefatos espaciais garantem total rastreabilidade cartográfica dos alimentadores de média e baixa tensão sobre a malha urbana de Ceilândia:

### 3.1 Camadas Vetoriais Estruturadas (GeoPackage OGC)
* [`data/processed/opendss/geo_tn08_20261018_134703.gpkg`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/geo_tn08_20261018_134703.gpkg) (630 kB):
  * Camada `linhas_mt_ssdmt`: 348 trechos de média tensão do circuito TN08;
  * Camada `linhas_bt_ssdbt`: 894 trechos de baixa tensão do circuito TN08;
  * Camada `trafos_untrmt`: 61 transformadores de distribuição.
* [`data/processed/opendss/geo_cn07_20261019_124919.gpkg`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/geo_cn07_20261019_124919.gpkg) (827 kB):
  * Camada `linhas_mt_ssdmt`: 431 trechos de média tensão do circuito CN07;
  * Camada `linhas_bt_ssdbt`: 1.240 trechos de baixa tensão do circuito CN07;
  * Camada `trafos_untrmt`: 77 transformadores de distribuição.

### 3.2 Mapas Estáticos de Alta Resolução (Matplotlib — 300 DPI)
* [`data/processed/Mapa_Auditoria_HRC.png`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/Mapa_Auditoria_HRC.png) (427 kB):
  * Traçado ciano/azul da rede TN08;
  * Marcador estrela vermelha no PAC do Hospital Regional de Ceilândia;
  * Box de conformidade PRODIST ($V_A = 1.0053, V_B = 1.0331, V_C = 1.0249\text{ pu}$).
* [`data/processed/Mapa_Auditoria_15DP_CN07.png`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/Mapa_Auditoria_15DP_CN07.png) (572 kB):
  * Traçado laranja elétrico `#ff7f0e` da malha primária do CN07;
  * Marcador de escudo ciano com borda branca no PAC da 15ª DP (`SCN_CN07_9032_CEIRJ002`);
  * Box de conformidade PRODIST com indicação da Fase A precária ($V_A = 0.9248\text{ pu}$).

### 3.3 Mapas Interativos Georreferenciados (Folium HTML)
* [`data/processed/Mapa_Interativo_HRC.html`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/Mapa_Interativo_HRC.html) (269 kB)
* [`data/processed/Mapa_Interativo_15DP_CN07.html`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/Mapa_Interativo_15DP_CN07.html) (355 kB)

> [!IMPORTANT]
> **Histórico de Resolução de Bloqueios de Basemap (HTTP 403):**
> Inicialmente, o renderizador Folium utilizou tiles do *OpenStreetMap* padrão, que bloqueou requisições automatizadas do Python via erro `403 Access Blocked`. Em seguida, tentou-se o *CartoDB Dark Matter*, que passou a exigir credenciais de API no Leaflet.
> A arquitetura foi refatorada para utilizar a camada de satélite **Esri World Imagery**, que é aberta, de altíssima definição, compatível com Leaflet e imune a bloqueios de User-Agent, fornecendo visualização de nível profissional para publicações científicas.

---

## 4. Modelos Elétricos Prontos para Simulação (OpenDSS)

Os circuitos da Zona 1 encontram-se completamente sintetizados e validados em formato nativo OpenDSS na pasta [`data/processed/opendss/`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/):

### 4.1 Circuito TN08 — Atendimento ao Hospital Regional de Ceilândia (HRC)
* [`Master_TN08_20261019_104122.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Master_TN08_20261019_104122.dss) (7.820 bytes) — Arquivo mestre compilável, SE regulada a $1,04\text{ pu}$;
* [`Lines_TN08_20261018_134703.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Lines_TN08_20261018_134703.dss) (163.660 bytes) — 1.242 linhas primárias e secundárias;
* [`Transformers_TN08_20261018_134703.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Transformers_TN08_20261018_134703.dss) (14.686 bytes) — 61 transformadores com parâmetros `EQTRMT`;
* [`Loads_TN08_20261019_104122.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Loads_TN08_20261019_104122.dss) (536.622 bytes) — 39 UCMT e 5.046 UCBT com Fator de Coincidência ($2.446\text{ kW}$ em BT);
* [`Switches_TN08_20261019_093214.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Switches_TN08_20261019_093214.dss) (20.011 bytes) — 112 chaves fechadas e 9 abertas de socorro;
* [`Buscoords_TN08_20261019_093214.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Buscoords_TN08_20261019_093214.dss) (58.312 bytes) — 1.341 nós georreferenciados.

### 4.2 Circuito CN07 — Atendimento à 15ª Delegacia de Polícia Civil (15ª DP)
* [`Master_CN07_20261019_124919.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Master_CN07_20261019_124919.dss) (9.120 bytes) — Arquivo mestre compilável, SE regulada a $1,04\text{ pu}$;
* [`Lines_CN07_20261019_124919.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Lines_CN07_20261019_124919.dss) (226.503 bytes) — 1.671 linhas primárias e secundárias;
* [`Transformers_CN07_20261019_124919.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Transformers_CN07_20261019_124919.dss) (18.823 bytes) — 77 transformadores com parâmetros `EQTRMT`;
* [`Loads_CN07_20261019_124919.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Loads_CN07_20261019_124919.dss) (817.950 bytes) — 46 UCMT (incluindo 15ª DP com 75 kW) e 7.585 UCBT com Fator de Coincidência ($3.123\text{ kW}$ em BT);
* [`Switches_CN07_20261019_124919.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Switches_CN07_20261019_124919.dss) (23.025 bytes) — 126 chaves fechadas e 12 abertas de manobra;
* [`Buscoords_CN07_20261019_124919.dss`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/data/processed/opendss/Buscoords_CN07_20261019_124919.dss) (80.165 bytes) — 1.865 nós georreferenciados.

---

## 5. Catálogo de Scripts (`src/`) e Rastreabilidade de Logs

A tabela a seguir consolida o histórico completo de esteira analítica desenvolvida para a Zona 1:

| Script Python (`src/`) | Linhas de Código | Função Principal no Pipeline | Log de Execução Auditado (`logs/`) |
| :--- | :---: | :--- | :--- |
| [`01_mineracao_topologia.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/01_mineracao_topologia.py) | 120 | Mineração de camadas e circuitos na BDGD bruta | — |
| [`02_filtro_espacial.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/02_filtro_espacial.py) | 215 | Recorte geográfico preliminar em torno de hospitais | — |
| [`03b_inventario_schema_bdgd.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03b_inventario_schema_bdgd.py) | 850 | Dicionário de dados das 28 camadas da BDGD | [`inventario_20261015_165727.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/inventario_20261015_165727.log) |
| [`03c_triagem_ucs_hrc.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03c_triagem_ucs_hrc.py) | 420 | Triagem de UCs no raio de 500m do HRC | [`triagem_ucs_hrc_20261015_172139.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/triagem_ucs_hrc_20261015_172139.log) |
| [`03d_hipoteses_alimentador_hrc.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03d_hipoteses_alimentador_hrc.py) | 680 | Teste de conectividade e seleção do alimentador TN08 | [`hipoteses_alimentador_hrc_20261015_173049.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/hipoteses_alimentador_hrc_20261015_173049.log) |
| [`03e_auditoria_duplicidade_ucs_hrc.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03e_auditoria_duplicidade_ucs_hrc.py) | 590 | Auditoria de UCs duplicadas na camada UCMT | [`auditoria_duplicidade_hrc_20261016_162439.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/auditoria_duplicidade_hrc_20261016_162439.log) |
| [`03f_auditoria_fonte_duplicidade_gdb.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03f_auditoria_fonte_duplicidade_gdb.py) | 410 | Rastreamento de duplicidade de origem no GDB bruto | [`auditoria_fonte_gdb_hrc_20261016_171724.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/auditoria_fonte_gdb_hrc_20261016_171724.log) |
| [`03g2_colunas_divergentes_por_balde.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03g2_colunas_divergentes_por_balde.py) | 260 | Decomposição em baldes de divergência cadastral | [`colunas_dedup_por_balde_20261017_152132.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/colunas_dedup_por_balde_20261017_152132.log) |
| [`03h_amostra_grupos_duplicados.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03h_amostra_grupos_duplicados.py) | 600 | Análise amostral de regras de desempate | [`amostra_grupos_duplicados_20261017_172116.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/amostra_grupos_duplicados_20261017_172116.log) |
| [`03i_medicao_populacao_completa.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/03i_medicao_populacao_completa.py) | 360 | Homologação da regra determinística para 100% da BDGD | [`03i_medicao_populacao_completa_20261018_124845.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/03i_medicao_populacao_completa_20261018_124845.log) |
| [`04_consolidacao_base_uc.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/04_consolidacao_base_uc.py) | 390 | Deduplicação global gerando tabelas consolidadas UCMT e UCBT | [`04_consolidacao_base_uc_20261018_131447.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/04_consolidacao_base_uc_20261018_131447.log) |
| [`05_rastreamento_hrc.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/05_rastreamento_hrc.py) | 280 | Rastreamento do PAC do HRC (`STN_TN08_9026_CEI003`) na UCMT | [`05_rastreamento_hrc_20261018_133430.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/05_rastreamento_hrc_20261018_133430.log) |
| [`06_extracao_circuito_opendss.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/06_extracao_circuito_opendss.py) | 520 | Extração preliminar do TN08 para OpenDSS | [`06_extracao_circuito_opendss_20261018_134703.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/06_extracao_circuito_opendss_20261018_134703.log) |
| [`07_validacao_baseline_eletrica.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/07_validacao_baseline_eletrica.py) | 310 | Smoke Tests de convergência e isolamento do PAC HRC | [`07_validacao_baseline_eletrica_20261019_093232.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/07_validacao_baseline_eletrica_20261019_093232.log) |
| [`08_acoplamento_chaves_unsemt.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/08_acoplamento_chaves_unsemt.py) | 330 | Acoplamento de chaves NF e NA do TN08 | [`08_acoplamento_chaves_unsemt_20261019_093214.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/08_acoplamento_chaves_unsemt_20261019_093214.log) |
| [`09_auditoria_cargas_opendss.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/09_auditoria_cargas_opendss.py) | 270 | Diagnóstico de subtensão por carga bruta em BT (22 MW) | [`09_auditoria_cargas_opendss_20261019_102339.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/09_auditoria_cargas_opendss_20261019_102339.log) |
| [`09_correcao_e_auditoria_visual.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/09_correcao_e_auditoria_visual.py) | 730 | Correção com Fator de Coincidência e Regulação SE STN | [`09_correcao_auditoria_visual_20261019_104122.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/09_correcao_auditoria_visual_20261019_104122.log) |
| [`09_auditoria_visual_hrc.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/09_auditoria_visual_hrc.py) | 433 | Auditoria visual e mapas (PNG e HTML Esri) do HRC | [`09_auditoria_visual_hrc.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/09_auditoria_visual_hrc.log) |
| [`10_rastreamento_seguranca_publica.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/10_rastreamento_seguranca_publica.py) | 380 | Triagem de Segurança Pública e identificação da 15ª DP (CN07) | [`10_rastreamento_seguranca_publica_20261019_123616.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/10_rastreamento_seguranca_publica_20261019_123616.log) |
| [`11_extracao_e_baseline_cn07_dp.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/11_extracao_e_baseline_cn07_dp.py) | 646 | Extração integral e baseline do CN07 com Fator de Coincidência | [`11_extracao_e_baseline_cn07_dp_20261019_124919.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/11_extracao_e_baseline_cn07_dp_20261019_124919.log) |
| [`12_auditoria_visual_dp_cn07.py`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/src/12_auditoria_visual_dp_cn07.py) | 597 | Auditoria PRODIST e geração de mapas (PNG e HTML Esri) da 15ª DP | [`12_auditoria_visual_dp_cn07_20261019_130853.log`](file:///c:/Users/adm/Documents/Modelos%20Preditivos%20na%20Rede%20El%C3%A9trica%20do%20DF/logs/12_auditoria_visual_dp_cn07_20261019_130853.log) |

---

## 6. Próximos Passos Recomendados para a Fase E6

Com a conclusão da modelagem e consolidação das duas infraestruturas críticas da Zona 1 (Saúde no TN08 e Segurança no CN07), o sistema encontra-se formalmente apto para avançar para a **Fase E6: Simulação de Contingências e Injeção de Falhas Ciberfísicas**:

1. **Modelagem das Chaves de Fronteira Normalmentes Abertas (NA):**
   * Avaliação de capacidade de transferência de carga e alívio de tensão entre os alimentadores de Ceilândia (`CN07`, `CN09`, `TN08`, `TN04`).
2. **Injeção de Ataques Ciberfísicos (False Data Injection e Manobras Coordenadas):**
   * Simulação de desarmes maliciosos nas chaves que alimentam o HRC e a 15ª DP;
   * Avaliação do colapso de tensão na Fase A da 15ª DP sob estresse de contingência $N-1$;
3. **Estruturação do Dataset para Graph Neural Networks (GNN):**
   * Conversão dos GeoPackages e arquivos `.dss` em matrizes de adjacência $A$, tensores de nós $X$ (potências, tensões pu, tipo de consumidor) e tensores de arestas $E$ (impedância, capacidade térmica $I_{\max}$) para treinamento de modelos preditivos resilientes.

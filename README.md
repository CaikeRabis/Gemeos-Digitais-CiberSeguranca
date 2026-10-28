# Gêmeos Digitais e Resiliência Ciberfísica na Rede Elétrica do DF

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![OpenDSS](https://img.shields.io/badge/solver-OpenDSS%20Direct%20v0.15-orange.svg)](https://dss-extensions.org/)
[![GIS Platform](https://img.shields.io/badge/GIS-GeoPandas%20%7C%20Shapely%20%7C%20Folium-green.svg)](https://geopandas.org/)
[![Vercel Deployment](https://img.shields.io/badge/deploy-Vercel%20Production-black.svg)](https://fleet-teal-i0ysa80.tmp.now)
[![Regulatório](https://img.shields.io/badge/norma-ANEEL%20PRODIST%20Módulo%208-yellow.svg)](https://www.gov.br/aneel/)

Repositório oficial de pesquisa e desenvolvimento do **Gêmeo Digital Eletromecânico e Topológico da Rede de Distribuição de Energia do Distrito Federal**, com ênfase na auditoria de conformidade regulatória (PRODIST ANEEL) e resiliência ciberfísica das **Infraestruturas Críticas de Saúde (Hospitais) e Segurança Pública (Delegacias de Polícia)**.

---

## 📌 Sumário
1. [Sobre a Pesquisa](#-sobre-a-pesquisa)
2. [Onde Estamos (Estágio Atual)](#-onde-estamos-estágio-atual)
3. [Resultados Consolidados das Zonas 1 e 2](#-resultados-consolidados-das-zonas-1-e-2)
4. [Próximos Passos (Fase E6 — Cibersegurança)](#-próximos-passos-fase-e6--cibersegurança)
5. [Arquitetura do Repositório](#-arquitetura-do-repositório)
6. [Inventário de Scripts](#-inventário-de-scripts)
7. [Como Utilizar o Repositório](#-como-utilizar-o-repositório)
8. [Dashboard Online](#-dashboard-online)

---

## 🔬 Sobre a Pesquisa

As redes de distribuição modernas estão em rápida transição para o paradigma de **Redes Elétricas Inteligentes (Smart Grids)**, caracterizadas por intensa digitalização, sensores IED, medidores inteligentes e telecontrole via protocolos industriais (DNP3, IEC 61850). Essa conectividade amplia a superfície de ataque para ameaças cibernéticas e contingências severas.

O objetivo desta pesquisa é construir um **Gêmeo Digital (Digital Twin)** de alta fidelidade física e topológica para avaliar o impacto de falhas ciberfísicas em serviços essenciais do Distrito Federal, analisando o contraste estrutural entre duas realidades sociotécnicas distintas:

* **Zona 1 (Ceilândia - Periferia Urbana):** Região de alta densidade demográfica, alimentada predominantemente por redes aéreas de média tensão, circuitos radiais extensos e maior vulnerabilidade a afundamentos de tensão.
  * **Saúde:** Hospital Regional de Ceilândia (**HRC**).
  * **Segurança:** 15ª Delegacia de Polícia Civil (**15ª DP**).
* **Zona 2 (Asa Sul / Plano Piloto - Centro Administrativo e Cívico):** Região que abriga os centros de poder e complexos hospitalares estratégicos, atendida por redes subterrâneas primárias e secundárias em anel/galerias técnicas, alimentadas por subestações de subtransmissão a 34.5 kV.
  * **Saúde:** Hospital de Base do Distrito Federal (**HBDF** - Setor Médico Hospitalar Sul).
  * **Segurança:** 1ª Delegacia de Polícia Civil (**1ª DP** / Complexo PCDF no Setor Policial Sul).

### Bases de Dados Oficiais Utilizadas
* **BDGD ANEEL / Neoenergia Distribuição Brasília (Dezembro/2025 - V11 2026):** Dados georreferenciados de condutores (`SSDMT`, `SSDBT`), transformadores (`UNTRMT`), chaves de manobra (`UNSEMT`), subestações (`SUB`) e unidades consumidoras (`UCMT`, `UCBT`).
* **Faturas Físicas de Energia (Ground Truth / LAI):** Microdados reais de medição obtidos via Lei de Acesso à Informação.
* **Procedimentos de Distribuição (PRODIST Módulo 8 da ANEEL):** Faixas regulatórias de tensão em Média Tensão (Adequada: `0,93 a 1,05 pu`; Precária: `0,87 a 0,93 pu` ou `1,05 a 1,06 pu`; Crítica: `< 0,87 pu` ou `> 1,06 pu`).

---

## 🚀 Onde Estamos (Estágio Atual)

O projeto concluiu com total êxito as etapas analíticas, topológicas e eletromecânicas das **Fases E1 a E5**:

1. **Fases E1 a E3 (Consolidação Populacional e Deduplicação):**
   * Processamento em 20 baldes via hash `CRC32(COD_ID)` no GDB nativo.
   * Resolução da divergência de 126.926 UCs repetidas em BT e 666 em MT através da **Regra de Cascata R3** (prioridade para `SIT_ATIV == 'AT'`, desempate por `DAT_CON` máxima).
   * Consolidação das bases oficiais com **1.183.916 UCs em Baixa Tensão** e **5.609 UCs em Média Tensão**.
2. **Fase E4 e E5 — Modelagem Zona 1 (Ceilândia):**
   * Mapeamento completo dos circuitos `TN08` (SE STN) e `CN07` (SE SCN).
   * **Calibração Ground Truth do HRC:** A demanda contratada nominal da BDGD (110.22 kW) foi substituída pelo valor real medido de fatura física oficial de 08/2026 (**460.80 kW**, FP = 0.92, FC = 0.56).
   * Diagnóstico: HRC com tensões plenamente **Adequadas** (1.002 a 1.030 pu); 15ª DP no final do circuito CN07 com tensão **Precária** na Fase A (0.9248 pu).
3. **Fase E5 — Desmistificação do SPOF e Modelagem Zona 2 (Asa Sul):**
   * **Correção Geográfica:** Identificação de um erro cadastral na BDGD que posicionava o HBDF na Hípica (erro de 4,41 km).
   * **Descarte do SPOF:** A varredura espacial por buffer métrico (500 metros em EPSG:31983) comprovou que a UC de 90 kW ligada à SE SHP era um falso positivo. O verdadeiro HBDF está no PAC `S02_0201_PT_TF_913`, suprido pela **Subestação SBG (Brasília Geral / Furnas)** no circuito `02_BGC1`.
   * **Topologia Segregada:** Comprovação de que tanto Ceilândia quanto a Asa Sul possuem infraestruturas de Saúde e Segurança fisicamente segregadas em subestações distintas.
   * Modelagem do circuito `02_BGC1` com **1.700,68 kW (1.70 MW)** agregados no HBDF e tensões 100% **Adequadas** (0.951 a 0.992 pu).
4. **Dashboard Integrado e Deploy:**
   * Mapa orbital unificado com a camada **Esri Satellite** (100% livre de requisições OSM para evitar erros 403).
   * Frontend interativo em tema escuro com cards dinâmicos dos cálculos do OpenDSS e botões para a Fase E6.
   * Publicação online via Vercel Edge Network.

---

## 📊 Resultados Consolidados das Zonas 1 e 2

| Região / Zona | Ativo Crítico | Subestação / Circuito | PAC Auditado | Demanda Modelada | Tensões Nodais (pu) | Diagnóstico PRODIST | Topologia da Zona |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Zona 1 (Ceilândia)** | **HRC** (Hospital) | `STN` / `TN08` | `STN_TN08_9026_CEI003` | **`460.80 kW`** | A: 1.0022<br>B: 1.0302<br>C: 1.0219 | **`[ADEQUADA]`** | **Segregada** (`STN` ≠ `SCN`) |
| **Zona 1 (Ceilândia)** | **15ª DP** (Polícia) | `SCN` / `CN07` | `SCN_CN07_9032_CEIRJ002` | **`75.00 kW`** | A: 0.9248<br>B: 0.9594<br>C: 0.9457 | **`[PRECÁRIA]`** (Fase A) | **Segregada** (`STN` ≠ `SCN`) |
| **Zona 2 (Asa Sul)** | **HBDF** (Hospital) | `SBG` / `02_BGC1` | `S02_0201_PT_TF_913` | **`1.700,68 kW`** | A: 0.9514<br>B: 0.9922<br>C: 0.9857 | **`[ADEQUADA]`** | **Segregada** (`SBG` ≠ `SHP`) |
| **Zona 2 (Asa Sul)** | **1ª DP** (Polícia) | `SHP` / `HP04` | `SHP_HP04_9025_BSB27A` | **`97.50 kW`** | A: 1.0138<br>B: 1.0158<br>C: 1.0157 | **`[ADEQUADA]`** | **Segregada** (`SBG` ≠ `SHP`) |

### Métricas Energéticas Globais
* **Zona 1 (Ceilândia):** Injeção total de **16.60 MW** | Perdas técnicas de **1.288,8 kW (7.76%)**.
* **Zona 2 (Asa Sul):** Injeção total de **33.33 MW** | Perdas técnicas de **1.624,8 kW (4.88%)** (eficiência de 95.12% devido ao cabeamento subterrâneo e subtransmissão em 34.5 kV).

---

## 🔮 Próximos Passos (Fase E6 — Cibersegurança)

Com os modelos elétricos das Zonas 1 e 2 calibrados e validados, a próxima etapa da pesquisa consiste na implementação dos módulos avançados de segurança ciberfísica e restauração:

1. **Ataques de Injeção de Dados Falsos (FDI - False Data Injection):**
   * Modelagem de invasão cibernética em medidores inteligentes de PACs críticos.
   * Criação de vetores de perturbação $\Delta z = H \cdot c$ formulados para contornar o algoritmo de Detecção de Dados Espúrios (BDD) do estimador de estado do centro de operação.
2. **Simulação de Contingências N-1 Físicas e Cibernéticas:**
   * Exploração simulada de vulnerabilidades em protocolos SCADA (DNP3 desprotegido / IEC 61850 GOOSE) para forçar o disparo indevido de disjuntores e chaves seccionadoras (`UNSEMT`).
   * Análise do impacto dinâmico na continuidade de suprimento do HRC e do HBDF.
3. **Mecanismos de Auto-Recuperação e Microrredes Hospitalares (Self-Healing):**
   * Reconfiguração automática da rede com transferência de blocos de carga para alimentadores adjacentes via chaves de manobra normalmente abertas (NA).
   * Ilhamento intencional (*islanding*) dos complexos hospitalares com despacho de geradores de emergência a diesel e geração fotovoltaica distribuída.
4. **Modelos Preditivos com Redes Neurais em Grafos (GNN):**
   * Treinamento de arquiteturas GNN (Graph Convolutional Networks / Graph Attention Networks) sobre a malha de barras e condutores do OpenDSS para predição ultra-rápida de fluxo de potência em tempo real.

---

## 📁 Arquitetura do Repositório

```text
├── .gitignore                                         # Regras estritas (bloqueio de dados > 100MB)
├── MATRIZ_MESTRE.md                                  # Matriz de controle e marcos da pesquisa
├── README.md                                         # Documentação oficial do projeto
├── requirements.txt                                  # Dependências Python reprodutíveis
├── public/                                           # Frontend estático para deploy (Vercel)
│   └── index.html                                    # Dashboard interativo autocontido
├── consolidacao_resultados_HRC_delegacia_ambiente_1/ # Documentação e laudos da Zona 1 (Ceilândia)
│   ├── 1_Comparativo_Tensoes_HRC_15DP.md
│   ├── 2_Inventario_Sistema_Atual.md
│   └── 3_Laudo_Calibracao_Ground_Truth_HRC.md
├── consolidacao_resultados_Zonas_1_e_2/              # Documentação e laudos da Zona 2 (Asa Sul)
│   └── 3_Laudo_Topologia_Segregada_Zona2.md
├── data/
│   ├── raw/                                          # GDB bruto da BDGD (ignorado no git)
│   └── processed/                                    # Artefatos processados, JSONs e OpenDSS
│       ├── Dashboard_Resiliencia_DF_Definitivo.html
│       ├── dashboard_resiliencia_df_definitivo_status.json
│       ├── laudo_baseline_sbg_hbdf.json
│       ├── laudo_calibracao_ground_truth_hrc.json
│       └── opendss/                                  # Modelos DSS nativos (Master, Lines, etc.)
│           ├── Master_TN08_Calibrado.dss
│           ├── Master_CN07_*.dss
│           ├── Master_SBG.dss
│           └── Master_SHP_Calibrado.dss
├── logs/                                             # Logs detalhados de todas as execuções
└── src/                                              # Scripts de automação, GIS e OpenDSS (01 a 22)
```

---

## 🛠 Inventário de Scripts

| Script | Finalidade e Escopo |
| :--- | :--- |
| `src/01_mineracao_topologia.py` | Mineração inicial da topologia da BDGD no GDB. |
| `src/02_filtro_espacial.py` | Filtragem de ativos georreferenciados no DF. |
| `src/03b_inventario_schema_bdgd.py` | Inventário de tabelas e campos do schema da BDGD. |
| `src/03g_colunas_dedup_matriz.py` | Análise de memória e arquitetura em 20 baldes CRC32. |
| `src/03h_amostra_grupos_duplicados.py` | Avaliação das regras candidatas de deduplicação (R1 a R4). |
| `src/03i_medicao_populacao_completa.py` | Medição exata em 100% da população de UCMT e UCBT. |
| `src/04_consolidacao_base_uc.py` | Deduplicação e geração das bases consolidadas de UCs. |
| `src/05_rastreamento_hrc.py` | Rastreamento topológico da cadeia de média tensão do HRC. |
| `src/06_extracao_circuito_opendss.py` | Primeira conversão do alimentador TN08 para OpenDSS. |
| `src/07_validacao_baseline_eletrica.py` | Validação de convergência de fluxo de potência. |
| `src/08_acoplamento_chaves_unsemt.py` | Acoplamento de chaves seccionadoras e integridade de malha. |
| `src/11_extracao_e_baseline_cn07_dp.py` | Extração do circuito CN07 e modelagem da 15ª DP. |
| `src/12_auditoria_visual_dp_cn07.py` | Auditoria visual e mapas temáticos da 15ª DP. |
| `src/13_rastreamento_asa_sul_saude_seguranca.py` | Triagem de ativos hospitalares e policiais na Asa Sul. |
| `src/14_extracao_e_baseline_asa_sul.py` | Extração da malha da SE SHP e simulação preliminar. |
| `src/15_auditoria_visual_asa_sul.py` | Auditoria visual e cartografia da SE SHP. |
| `src/16_calibracao_ground_truth_hrc.py` | Calibração do HRC com Ground Truth de fatura física oficial (LAI). |
| `src/17_correcao_geografica_asa_sul.py` | Correção das coordenadas geográficas nodais do HBDF e da 1ª DP. |
| `src/18_dashboard_integrado_frontend.py` | Criação do primeiro dashboard unificado Z1/Z2. |
| `src/19_rastreamento_espacial_hbdf.py` | Varredura por buffer métrico (500m) e descoberta do verdadeiro PAC do HBDF. |
| `src/20_extracao_e_baseline_sbg_hbdf.py` | Modelagem OpenDSS definitiva da SE SBG (02_BGC1) e baseline do HBDF. |
| `src/21_dashboard_definitivo_frontend.py` | Geração do Dashboard Definitivo unificado com Esri Satellite. |
| `src/22_limpeza_repositorio.py` | Higienização do repositório e remoção de arquivos intermediários. |

---

## 💻 Como Utilizar o Repositório

### 1. Pré-Requisitos
* Python 3.12+ (64 bits)
* Git instalado
* Node.js 20+ (opcional, para deploys via Vercel CLI)

### 2. Clonagem e Configuração do Ambiente Virtual

```powershell
# Clonar o repositório
git clone https://github.com/CaikeRabis/Gemeos-Digitais-CiberSeguranca.git
cd Gemeos-Digitais-CiberSeguranca

# Criar e ativar o ambiente virtual (Windows PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Instalar dependências
pip install -r requirements.txt
```

### 3. Execução das Simulações Elétricas (OpenDSS)

```powershell
# Executar a calibração com Ground Truth do HRC (Zona 1)
python src/16_calibracao_ground_truth_hrc.py

# Executar a modelagem e auditoria do circuito definitivo do HBDF na SE SBG (Zona 2)
python src/20_extracao_e_baseline_sbg_hbdf.py

# Gerar o Dashboard Unificado atualizado com as Zonas 1 e 2
python src/21_dashboard_definitivo_frontend.py
```

### 4. Visualização do Dashboard Local

Após executar o script `21`, abra o arquivo no navegador:
```powershell
Start-Process "data/processed/Dashboard_Resiliencia_DF_Definitivo.html"
```
Ou abra diretamente o arquivo da pasta pública:
```powershell
Start-Process "public/index.html"
```

---

## 🌐 Dashboard Online

O painel unificado está hospedado e acessível publicamente via Vercel Edge CDN:
👉 **[https://fleet-teal-i0ysa80.tmp.now](https://fleet-teal-i0ysa80.tmp.now)**

---

## 📄 Licença e Autoria
Projeto desenvolvido no âmbito da pesquisa em **Modelos Preditivos e Cibersegurança em Sistemas Elétricos de Potência do Distrito Federal**.  
Autor: **CaikeRabis** (`caikerabis@gmail.com`).

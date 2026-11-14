import streamlit as st
import pandas as pd
import re
from pypdf import PdfReader
from io import BytesIO

st.set_page_config(page_title="Conversor de Mapas BNC/BLL", layout="wide")
st.title("Conversor de Mapas: Portais BNC e BLL")

def extrair_marcas_propostas(pdf_file):
    lote_marca_map = {}
    reader = PdfReader(pdf_file)
    lines = []
    for page in reader.pages:
        lines.extend(page.extract_text().split('\n'))

    current_lote = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m_lote = re.match(r'^LOTE\s+(\d+)$', line)
        if m_lote:
            current_lote = int(m_lote.group(1))
            lote_marca_map[current_lote] = {}
        elif line == 'LOTE':
            if i + 1 < len(lines) and re.match(r'^\d+$', lines[i+1].strip()):
                current_lote = int(lines[i+1].strip())
                lote_marca_map[current_lote] = {}
                i += 1
                
        if line.startswith('PARTICIPANTE '):
            parts = line.split()
            if len(parts) >= 2:
                part_num = parts[1]
                brand_str = ""
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if re.match(r'^\d{1,3}(\.\d{3})*,\d+$', next_line) or next_line == '':
                        if next_line != '':
                            break
                    else:
                        brand_str += next_line + " "
                    j += 1
                if current_lote is not None:
                    lote_marca_map[current_lote][part_num] = brand_str.strip()
                i = j - 1
        i += 1
    return lote_marca_map

def extrair_ata_sessao(pdf_file, itens_validos, lote_marca_map):
    reader = PdfReader(pdf_file)
    ata_lines = []
    for page in reader.pages:
        ata_lines.extend(page.extract_text().split('\n'))

    resultados = []
    current_lote = None
    mode = None
    i = 0

    while i < len(ata_lines):
        line = ata_lines[i].strip()
        
        m_lote = re.match(r'^LOTE\s+(\d+)', line)
        if m_lote:
            current_lote = int(m_lote.group(1))
            mode = None
        elif line == 'LOTE':
            if i + 1 < len(ata_lines) and re.match(r'^\d+', ata_lines[i+1].strip()):
                current_lote = int(re.match(r'^\d+', ata_lines[i+1].strip()).group())
                mode = None
                i += 1
                
        if current_lote in itens_validos:
            if line == 'CLASSIFICAÇÃO':
                mode = 'CLASSIFICACAO'
            elif line == 'DESCLASSIFICADOS':
                mode = 'DESCLASSIFICADOS'
            elif line == 'INABILITADOS':
                mode = 'INABILITADOS'
            elif line == 'MOVIMENTOS DO LOTE' or line.startswith('01/10/2026'):
                mode = None
                
            if mode in ['CLASSIFICACAO', 'DESCLASSIFICADOS', 'INABILITADOS']:
                m_cnpj = re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', line)
                if m_cnpj:
                    cnpj = m_cnpj.group()
                    
                    window = [ata_lines[max(0, i-k)].strip() for k in range(5, -1, -1)]
                    idx_cnpj = 5
                    idx_num = idx_cnpj - 1
                    num = None
                    
                    m_num = re.search(r'\b(\d{3})\b', window[idx_num])
                    if m_num:
                        num = m_num.group(1)
                    else:
                        m_num = re.search(r'\b(\d{3})\b', window[idx_num-1])
                        if m_num:
                            num = m_num.group(1)
                            idx_num -= 1
                    
                    rs_parts = []
                    for k in range(idx_num-1, -1, -1):
                        txt = window[k]
                        if mode == 'CLASSIFICACAO' and re.match(r'^\d+$', txt):
                            break
                        if mode != 'CLASSIFICACAO' and (re.match(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', txt) or txt in ['Sim', 'Não']):
                            break
                        rs_parts.insert(0, txt)
                    
                    razao_social = " ".join(rs_parts).strip()
                    
                    # Regex Sanitizer para Razão Social
                    razao_social = re.sub(r'^\d+\s+', '', razao_social)
                    razao_social = re.sub(r'\b(Dif\.|%\s*ME|ME|Sim|Não)\b', '', razao_social, flags=re.IGNORECASE)
                    razao_social = re.sub(r'\(%\)', '', razao_social)
                    razao_social = re.sub(r'\d+,\d+', '', razao_social)
                    razao_social = razao_social.strip()
                        
                    oferta_final = None
                    me_str = None
                    j = i + 1
                    ofertas = []
                    while j < min(i + 8, len(ata_lines)):
                        n_line = ata_lines[j].strip()
                        if n_line in ['Sim', 'Não']:
                            me_str = 'ME/EPP' if n_line == 'Sim' else 'Grande Porte'
                            break
                        if re.match(r'^\d{1,3}(\.\d{3})*,\d+$', n_line):
                            ofertas.append(n_line)
                        j += 1
                    
                    if len(ofertas) >= 2:
                        oferta_final = ofertas[1]
                    elif len(ofertas) == 1:
                        oferta_final = ofertas[0]
                        
                    if oferta_final:
                        oferta_final = float(oferta_final.replace('.', '').replace(',', '.'))
                    else:
                        oferta_final = float('inf')
                    
                    marca = lote_marca_map.get(current_lote, {}).get(num, "")
                    
                    resultados.append({
                        'Lote': current_lote,
                        'Razão Social': razao_social,
                        'CNPJ': cnpj,
                        'Oferta Final': oferta_final,
                        'Porte': me_str,
                        'Marca': marca
                    })
        i += 1
    return resultados

def gerar_mapa_excel(resultados, df_cadastro):
    map_itens = {row['Item']: row for _, row in df_cadastro.dropna(subset=['Item']).iterrows()}
    mapa = []
    
    for lote in sorted(list(set(r['Lote'] for r in resultados))):
        if lote not in map_itens:
            continue
            
        row_item = map_itens[lote]
        qtde = float(row_item['Quantidade'])
        desc = row_item['--------------------------------- D i s c r i m i n a ç ã o ---------------------------------']
        
        mapa.append({
            'MAPA': 22105,
            'Posição': f'Item {lote}',
            'Item': lote,
            'Código': '',
            'Descrição': desc,
            'CNPJ': '',
            'Empresa': '',
            'Porte': '',
            'Marca': '',
            'Modelo': '',
            'Quantidade': qtde,
            'Valor unitário': None,
            'Valor total': None,
            'Mapa': 22105,
            'Desconsiderado': ''
        })
        
        lote_results = [r for r in resultados if r['Lote'] == lote]
        lote_results.sort(key=lambda x: x['Oferta Final'])
        
        for idx, r in enumerate(lote_results):
            vt = r['Oferta Final'] * qtde if r['Oferta Final'] != float('inf') else None
            vu = r['Oferta Final'] if r['Oferta Final'] != float('inf') else None
            
            mapa.append({
                'MAPA': '',
                'Posição': f"{idx + 1}º",
                'Item': '',
                'Código': '',
                'Descrição': '',
                'CNPJ': r['CNPJ'],
                'Empresa': r['Razão Social'],
                'Porte': r['Porte'],
                'Marca': r['Marca'],
                'Modelo': '',
                'Quantidade': '',
                'Valor unitário': vu,
                'Valor total': vt,
                'Mapa': 22105,
                'Desconsiderado': ''
            })

    df_mapa = pd.DataFrame(mapa)
    
    header_row1 = ['MAPA', 22105, '86/2026', 'FUNDO M. DE SAÚDE DE RIO VERDE'] + [''] * 10
    header_row2 = ['Posição', 'Item', 'Código', 'Descrição', 'CNPJ', 'Empresa', 'Porte', 'Marca', 'Modelo', 'Quantidade', 'Valor unitário', 'Valor total', 'Mapa', 'Desconsiderado']

    df_mapa_final = pd.DataFrame(columns=header_row2)
    for idx, row in df_mapa.iterrows():
        df_mapa_final.loc[idx] = [row.get(c, '') for c in header_row2]
        
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame([header_row1]).to_excel(writer, header=False, index=False, startrow=0)
        df_mapa_final.to_excel(writer, header=True, index=False, startrow=1)
        
    return output.getvalue()


# --- INTERFACE DO STREAMLIT ---
st.write("Faça o upload dos arquivos extraídos do portal para gerar a planilha no modelo unificado.")

col1, col2, col3 = st.columns(3)
with col1:
    arq_cadastro = st.file_uploader("1. Planilha de Cadastro (XLSX)", type=["xlsx"])
with col2:
    arq_propostas = st.file_uploader("2. Ata de Propostas (PDF)", type=["pdf"])
with col3:
    arq_ata = st.file_uploader("3. Ata da Sessão (PDF)", type=["pdf"])

if arq_cadastro and arq_propostas and arq_ata:
    if st.button("Processar Arquivos", type="primary"):
        with st.spinner('Lendo documentos e estruturando mapa...'):
            try:
                # 1. Lê cadastro
                df_cad = pd.read_excel(arq_cadastro)
                df_cad['Item'] = pd.to_numeric(df_cad['Item'], errors='coerce')
                itens_cotados = df_cad.dropna(subset=['Item'])['Item'].astype(int).tolist()
                
                # 2. Executa processamento
                dict_marcas = extrair_marcas_propostas(arq_propostas)
                dados_concorrentes = extrair_ata_sessao(arq_ata, itens_cotados, dict_marcas)
                
                # 3. Gera Excel em memória
                excel_data = gerar_mapa_excel(dados_concorrentes, df_cad)
                
                st.success("Conversão concluída com sucesso!")
                
                # 4. Botão de Download
                st.download_button(
                    label="📥 Baixar Planilha Convertida (XLSX)",
                    data=excel_data,
                    file_name="mapa_bll_bnc_convertido.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            except Exception as e:
                st.error(f"Ocorreu um erro durante o processamento: {e}")

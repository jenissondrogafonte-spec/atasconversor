import streamlit as st
import pandas as pd
import re
from io import BytesIO
from pypdf import PdfReader # Substituímos pdfplumber pelo pypdf que é 10x mais leve e não estoura a RAM

st.set_page_config(page_title="Conversor de Mapas BNC/BLL", layout="wide")
st.title("Conversor de Mapas: Portais BNC e BLL")

def extract_text_from_pdf(pdf_file):
    """Extrai texto bruto do PDF usando pypdf para não consumir memória visual"""
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t:
            text += t + "\n"
    return text

def mapear_marcas_propostas(pdf_text):
    """Cria um dicionário (Lote) -> {Num_Participante: Marca} a partir do PDF de Propostas"""
    lote_marca_map = {}
    lines = pdf_text.split('\n')
    current_lote = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m_lote = re.match(r'^LOTE\s+(\d+)$', line)
        if m_lote:
            current_lote = int(m_lote.group(1))
            lote_marca_map[current_lote] = {}
            
        if line.startswith('PARTICIPANTE ') or line.startswith('PARTICIPAΝΤΕ '):
            parts = line.split()
            if len(parts) >= 2:
                part_num = parts[1]
                brand_str = ""
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    # Para se achar outro participante ou fim
                    if next_line.startswith('PARTICIPANTE ') or next_line.startswith('PARTICIPAΝΤΕ '):
                        break
                    
                    if next_line == '':
                        pass
                    else:
                        clean_next_line = next_line
                        # Remove caracteres de tabela do PDF
                        if next_line.startswith('|'):
                            clean_next_line = next_line[1:].strip()
                            
                        # Se achar o preço, ignora e encerra a busca da marca
                        if re.match(r'^\d{1,3}(\.\d{3})*,\d+$', clean_next_line) or re.match(r'^\d{1,3}(\.\d{3})*\.\d+$', clean_next_line):
                            pass 
                        else:
                            brand_str += clean_next_line + " "
                    j += 1
                if current_lote is not None:
                    lote_marca_map[current_lote][part_num] = brand_str.strip()
                i = j - 1
        i += 1
    return lote_marca_map

def mapear_ata_sessao(pdf_text):
    """Cria um dicionário (Lote, CNPJ) -> {'num_participante': X, 'status': Y} a partir da Ata Final"""
    ata_lines = pdf_text.split('\n')
    mapa_sessao = {}
    current_lote = None
    mode = None
    
    i = 0
    while i < len(ata_lines):
        line = ata_lines[i].strip()
        
        # Pega o Lote
        m_lote = re.match(r'^LOTE\s+(\d+)', line)
        if m_lote:
            current_lote = int(m_lote.group(1))
            if current_lote not in mapa_sessao:
                mapa_sessao[current_lote] = {}
            mode = None
        elif line == 'LOTE': # Outro padrão comum do PDF
            if i + 1 < len(ata_lines) and re.match(r'^\d+', ata_lines[i+1].strip()):
                current_lote = int(re.match(r'^\d+', ata_lines[i+1].strip()).group())
                if current_lote not in mapa_sessao:
                    mapa_sessao[current_lote] = {}
                mode = None
                i += 1
                
        # Status
        if line == 'CLASSIFICAÇÃO':
            mode = 'CLASSIFICACAO'
        elif line == 'DESCLASSIFICADOS':
            mode = 'DESCLASSIFICADOS'
        elif line == 'INABILITADOS':
            mode = 'INABILITADOS'
        elif line == 'MOVIMENTOS DO LOTE' or line.startswith('01/10/2026'):
            mode = None
            
        if mode in ['CLASSIFICACAO', 'DESCLASSIFICADOS', 'INABILITADOS']:
            # Procurar CNPJ na linha
            m_cnpj = re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', line)
            if m_cnpj and current_lote is not None:
                cnpj = m_cnpj.group()
                
                # Janela de leitura: 2 linhas anteriores e a atual para achar o num do participante (3 dígitos)
                window = [ata_lines[max(0, i-k)].strip() for k in range(2, -1, -1)]
                num = None
                
                for w_line in window:
                    clean_w = w_line
                    if clean_w.startswith('|'):
                        clean_w = clean_w[1:].strip()
                        
                    m_num = re.search(r'\b(\d{3})\b', clean_w)
                    if m_num and not num:
                        num = m_num.group(1)
                
                if num:
                    mapa_sessao[current_lote][cnpj] = {
                        'num_participante': num,
                        'status': mode
                    }
        i += 1
    return mapa_sessao


# --- INTERFACE DO STREAMLIT ---
st.write("Faça o upload da Tabela Mestra (Excel) e das Atas de Enriquecimento (PDFs).")

col1, col2, col3 = st.columns(3)
with col1:
    arq_resultado = st.file_uploader("1. Excel Mestre (Resultados)", type=["xlsx"])
with col2:
    arq_propostas = st.file_uploader("2. PDF (Propostas do Processo)", type=["pdf"])
with col3:
    arq_ata = st.file_uploader("3. PDF (Ata da Sessão)", type=["pdf"])

if arq_resultado and arq_propostas and arq_ata:
    if st.button("Processar Arquivos (Arquitetura Otimizada)", type="primary"):
        with st.spinner('Realizando cruzamento de dados inteligente. Isso deve levar apenas alguns segundos...'):
            try:
                # 1. Extração de Texto Leve dos PDFs
                texto_propostas = extract_text_from_pdf(arq_propostas)
                texto_ata = extract_text_from_pdf(arq_ata)
                
                # 2. Construção dos Dicionários de Memória
                dict_marcas = mapear_marcas_propostas(texto_propostas)
                dict_sessao = mapear_ata_sessao(texto_ata)
                
                # 3. Leitura do Arquivo Mestre (Excel)
                df_mestre = pd.read_excel(arq_resultado)
                
                # Garante que as colunas alvo existam
                if 'Marca' not in df_mestre.columns:
                    df_mestre['Marca'] = ''
                if 'Desconsiderado' not in df_mestre.columns:
                    df_mestre['Desconsiderado'] = ''
                if 'Posição' not in df_mestre.columns: # Caso a planilha mestre seja bruta
                    df_mestre['Posição'] = ''
                if 'MAPA' not in df_mestre.columns:
                    df_mestre['MAPA'] = ''
                    
                # 4. Merge e Enriquecimento das Linhas
                current_lote = None
                
                for idx, row in df_mestre.iterrows():
                    # Descobre em que lote a linha está ancorada
                    if pd.notna(row.get('Item')) and str(row.get('Item')).strip() != '':
                        try:
                            current_lote = int(float(str(row['Item']).strip()))
                        except:
                            pass
                            
                    cnpj = str(row.get('CNPJ', '')).strip()
                    
                    if current_lote and re.match(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', cnpj):
                        # Temos um lote ativo e um CNPJ válido na linha
                        participante_info = dict_sessao.get(current_lote, {}).get(cnpj)
                        
                        if participante_info:
                            num_part = participante_info['num_participante']
                            status = participante_info['status']
                            
                            # Define o Status (Desconsiderado)
                            if status in ['DESCLASSIFICADOS', 'INABILITADOS']:
                                df_mestre.at[idx, 'Desconsiderado'] = 'SIM'
                            else:
                                df_mestre.at[idx, 'Desconsiderado'] = ''
                                
                            # Define a Marca
                            marca_encontrada = dict_marcas.get(current_lote, {}).get(num_part, '')
                            df_mestre.at[idx, 'Marca'] = marca_encontrada

                # 5. Higienização e Formatação Final
                colunas_desejadas = ['MAPA', 'Posição', 'Item', 'Código', 'Descrição', 'CNPJ', 'Empresa', 'Porte', 'Marca', 'Modelo', 'Quantidade', 'Valor unitário', 'Valor total', 'Mapa', 'Desconsiderado']
                
                # Preenche com colunas vazias se a planilha mestre não tiver alguma do layout
                for col in colunas_desejadas:
                    if col not in df_mestre.columns:
                        df_mestre[col] = ''
                        
                df_final = df_mestre[colunas_desejadas]
                
                # Gera o Excel de saída
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_final.to_excel(writer, index=False)
                    
                excel_data = output.getvalue()
                
                st.success("Cruzamento concluído com sucesso e arquivo final enriquecido!")
                st.download_button(
                    label="📥 Baixar Planilha Pronta",
                    data=excel_data,
                    file_name="mapa_cruzamento_final.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            except Exception as e:
                st.error(f"Erro inesperado: {e}")

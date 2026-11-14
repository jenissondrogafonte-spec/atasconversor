import pandas as pd
import re
from pypdf import PdfReader
import warnings

# Ignorar avisos do openpyxl
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

def extrair_marcas_propostas(pdf_path):
    """Lê o PDF de Propostas e cria um dicionário Lote -> Participante -> Marca"""
    lote_marca_map = {}
    with open(pdf_path, 'rb') as f:
        reader = PdfReader(f)
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
                    # Interrompe a leitura da marca ao encontrar o preço final (ex: 3,23)
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

def extrair_ata_sessao(pdf_path, itens_validos, lote_marca_map):
    """Lê o PDF da Ata Final e extrai os concorrentes e seus valores"""
    with open(pdf_path, 'rb') as f:
        reader = PdfReader(f)
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
                # Gatilho principal: CNPJ
                m_cnpj = re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', line)
                if m_cnpj:
                    cnpj = m_cnpj.group()
                    
                    # Janela de leitura (5 linhas acima)
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
                    
                    # 1ª CORREÇÃO: Limpeza de lixo (Regex Sanitizer)
                    razao_social = re.sub(r'^\d+\s+', '', razao_social)
                    razao_social = re.sub(r'\b(Dif\.|%\s*ME|ME|Sim|Não)\b', '', razao_social, flags=re.IGNORECASE)
                    razao_social = re.sub(r'\(%\)', '', razao_social)
                    razao_social = re.sub(r'\d+,\d+', '', razao_social)
                    razao_social = razao_social.strip()
                        
                    # Busca valores
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
                        oferta_final = float('inf') # Proteção caso não encontre valor
                    
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

def gerar_mapa_excel(resultados, df_cadastro, arquivo_saida):
    """Gera o arquivo Excel final com base nas regras do mapa_22105"""
    map_itens = {row['Item']: row for _, row in df_cadastro.dropna(subset=['Item']).iterrows()}
    mapa = []
    
    for lote in sorted(list(set(r['Lote'] for r in resultados))):
        row_item = map_itens[lote]
        qtde = float(row_item['Quantidade'])
        desc = row_item['--------------------------------- D i s c r i m i n a ç ã o ---------------------------------']
        
        # Linha Pai
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
        
        # Filtra lote e faz o sort pelo preço
        lote_results = [r for r in resultados if r['Lote'] == lote]
        
        # 2ª CORREÇÃO: Ordenação rigorosa pelo valor final, ignorando status da ata
        lote_results.sort(key=lambda x: x['Oferta Final'])
        
        # Linhas Filhas
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

    with pd.ExcelWriter(arquivo_saida) as writer:
        pd.DataFrame([header_row1]).to_excel(writer, header=False, index=False, startrow=0)
        df_mapa_final.to_excel(writer, header=True, index=False, startrow=1)

if __name__ == "__main__":
    # Nomes dos arquivos de entrada
    arq_cadastro = 'cadastro_portal_21758_bnc_bll_lictanet_unificada.xlsx'
    arq_propostas = 'PropostasProcesso_1aa20261019105931620.pdf'
    arq_ata = 'AtaSessaoFinal_1aa20261112131613137.pdf'
    arq_saida = 'mapa_bll_bnc_convertido.xlsx'
    
    # Execução do Workflow
    print("Iniciando extração...")
    df_cad = pd.read_excel(arq_cadastro)
    df_cad['Item'] = pd.to_numeric(df_cad['Item'], errors='coerce')
    itens_cotados = df_cad.dropna(subset=['Item'])['Item'].astype(int).tolist()
    
    dict_marcas = extrair_marcas_propostas(arq_propostas)
    dados_concorrentes = extrair_ata_sessao(arq_ata, itens_cotados, dict_marcas)
    
    gerar_mapa_excel(dados_concorrentes, df_cad, arq_saida)
    print(f"Conversão concluída. Arquivo {arq_saida} gerado com sucesso!")

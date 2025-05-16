import os
import random
import string

def gerar_arquivo_teste(nome_arquivo: str, tamanho_mb: int):
    """Gera um arquivo de teste com o tamanho especificado em MB"""
    tamanho_bytes = tamanho_mb * 1024 * 1024  # Converte MB para bytes
    
    print(f"Gerando arquivo de teste de {tamanho_mb}MB...")
    
    with open(nome_arquivo, 'wb') as f:
        bytes_escritos = 0
        tamanho_bloco = 1024 * 1024  # Escreve 1MB por vez
        
        while bytes_escritos < tamanho_bytes:
            # Gera dados aleatórios
            dados = ''.join(random.choices(string.ascii_letters + string.digits, k=tamanho_bloco)).encode()
            
            # Ajusta o último bloco se necessário
            if bytes_escritos + len(dados) > tamanho_bytes:
                dados = dados[:tamanho_bytes - bytes_escritos]
                
            f.write(dados)
            bytes_escritos += len(dados)
            
            # Mostra progresso
            progresso = (bytes_escritos / tamanho_bytes) * 100
            print(f"\rProgresso: {progresso:.1f}%", end='')
            
    print(f"\nArquivo {nome_arquivo} ({tamanho_mb}MB) gerado com sucesso!")

if __name__ == '__main__':
    # Gera dois arquivos de teste: 1MB e 10MB
    gerar_arquivo_teste('teste_15mb.dat', 15)
    # gerar_arquivo_teste('teste_10mb.dat', 10) 
    # gerar_arquivo_teste('teste_100mb.dat', 100) 
#   gerar_arquivo_teste('teste_1gb.dat', 1024) 
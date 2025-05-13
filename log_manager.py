import os
import json
from datetime import datetime
from typing import Set, Dict, List

class LogManager:
    def __init__(self, nome_arquivo: str):
        self.nome_arquivo = nome_arquivo
        self.tempo_inicio = datetime.now()
        self.tempo_fim = None
        self.total_chunks = 0
        self.chunks_processados: Set[int] = set()
        self.chunks_perdidos: Set[int] = set()
        self.chunks_recuperados: Set[int] = set()
        self.log_dir = "logs"
        
        # Cria diretório de logs se não existir
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
    
    def registrar_total_chunks(self, total: int):
        """Registra o número total de chunks do arquivo"""
        self.total_chunks = total
    
    def registrar_chunk_processado(self, chunk_id: int):
        """Registra um chunk processado com sucesso"""
        self.chunks_processados.add(chunk_id)
    
    def registrar_chunk_perdido(self, chunk_id: int):
        """Registra um chunk perdido"""
        self.chunks_perdidos.add(chunk_id)
    
    def registrar_chunk_recuperado(self, chunk_id: int):
        """Registra um chunk recuperado"""
        self.chunks_recuperados.add(chunk_id)
        
    def finalizar(self):
        """Finaliza o log e gera o relatório"""
        self.tempo_fim = datetime.now()
        self._gerar_relatorio()
    
    def _calcular_estatisticas(self) -> Dict:
        """Calcula as estatísticas da transferência"""
        duracao = (self.tempo_fim - self.tempo_inicio).total_seconds()
        
        return {
            "arquivo": self.nome_arquivo,
            "data_inicio": self.tempo_inicio.isoformat(),
            "data_fim": self.tempo_fim.isoformat(),
            "duracao_segundos": duracao,
            "total_chunks": self.total_chunks,
            "chunks_processados": len(self.chunks_processados),
            "chunks_perdidos": len(self.chunks_perdidos),
            "chunks_recuperados": len(self.chunks_recuperados),
            "chunks_nao_recuperados": len(self.chunks_perdidos - self.chunks_recuperados),
            "porcentagem_sucesso": (len(self.chunks_processados) / self.total_chunks) * 100 if self.total_chunks > 0 else 0,
            "porcentagem_perdidos": (len(self.chunks_perdidos) / self.total_chunks) * 100 if self.total_chunks > 0 else 0,
            "porcentagem_recuperados": (len(self.chunks_recuperados) / len(self.chunks_perdidos)) * 100 if len(self.chunks_perdidos) > 0 else 100,
            "lista_chunks_processados": sorted(list(self.chunks_processados)),
            "lista_chunks_perdidos": sorted(list(self.chunks_perdidos)),
            "lista_chunks_recuperados": sorted(list(self.chunks_recuperados))
        }
    
    def _gerar_relatorio(self):
        """Gera o arquivo de log com as estatísticas"""
        estatisticas = self._calcular_estatisticas()
        
        # Nome do arquivo de log baseado no timestamp
        timestamp = self.tempo_inicio.strftime("%Y%m%d_%H%M%S")
        nome_log = f"{self.log_dir}/log_{os.path.basename(self.nome_arquivo)}_{timestamp}.json"
        
        with open(nome_log, 'w', encoding='utf-8') as f:
            json.dump(estatisticas, f, indent=4)
            
        # Gera também um relatório em texto para fácil leitura
        nome_relatorio = f"{self.log_dir}/relatorio_{os.path.basename(self.nome_arquivo)}_{timestamp}.txt"
        with open(nome_relatorio, 'w', encoding='utf-8') as f:
            f.write(f"Relatório de Transferência - {self.nome_arquivo}\n")
            f.write(f"Data/Hora Início: {estatisticas['data_inicio']}\n")
            f.write(f"Data/Hora Fim: {estatisticas['data_fim']}\n")
            f.write(f"Duração: {estatisticas['duracao_segundos']:.2f} segundos\n\n")
            
            f.write("Estatísticas:\n")
            f.write(f"- Total de Chunks: {estatisticas['total_chunks']}\n")
            f.write(f"- Chunks Processados: {estatisticas['chunks_processados']} ({estatisticas['porcentagem_sucesso']:.1f}%)\n")
            f.write(f"- Chunks Perdidos: {estatisticas['chunks_perdidos']} ({estatisticas['porcentagem_perdidos']:.1f}%)\n")
            f.write(f"- Chunks Recuperados: {estatisticas['chunks_recuperados']} ")
            f.write(f"({estatisticas['porcentagem_recuperados']:.1f}% dos perdidos)\n")
            f.write(f"- Chunks Não Recuperados: {estatisticas['chunks_nao_recuperados']}\n") 
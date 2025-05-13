import socket
import argparse
import os
import struct
import zlib
import time
import select
import logging
from typing import Tuple, Dict

# Configuração de logging com timestamp
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# --- Configurações do protocolo ---
MAGIC_NUMBER = 0x0000       # Número mágico para identificação de pacotes válidos
MAX_PAYLOAD = 1024 * 8      # 8 KB por segmento
HEADER_SIZE = 18            # Header + checksum
TIMEOUT = 0.5               # Timeout para retransmissão (s)
MAX_RETRIES = 5             # Máximo de retransmissões

# Tipos de pacote
TYPE_REQUEST = 0
TYPE_DATA    = 1
TYPE_ACK     = 2
TYPE_ERROR   = 3

# Flags
FLAG_NORMAL = 0
FLAG_LAST   = 1


def compute_checksum(data: bytes) -> bytes:
    """
    Calcula checksum CRC32 em 4 bytes big-endian
    """
    checksum = zlib.crc32(data) & 0xFFFFFFFF
    return struct.pack('!I', checksum)

class UDPServer:
    def __init__(self, port: int, directory: str):
        """
        Inicia socket UDP e prepara estado
        """
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("", port))
        self.directory = directory
        self.clients: Dict[Tuple[str,int], dict] = {}
        logging.info(f"Servidor iniciado em 0.0.0.0:{port}, servindo {directory}")

    def run(self):
        """Loop: receber pacotes e retransmitir"""
        try:
            while True:
                ready,_,_ = select.select([self.socket], [], [], 1.0)
                if ready:
                    data, addr = self.socket.recvfrom(MAX_PAYLOAD + HEADER_SIZE)
                    logging.info(f"Pacote recebido de {addr}, tamanho {len(data)} bytes")
                    self.handle_packet(data, addr)
                self.check_retransmissions()
        except KeyboardInterrupt:
            logging.info("Servidor encerrado pelo usuário")

    def handle_packet(self, data: bytes, addr: Tuple[str,int]):
        if len(data) < HEADER_SIZE:
            logging.warning(f"Pacote muito curto de {addr}")
            return
        header = data[:HEADER_SIZE]
        magic, ptype, seq, size, total, flags, recv_checksum = \
            struct.unpack('!HBIH I B4s'.replace(' ', ''), header)
        if magic != MAGIC_NUMBER:
            logging.warning(f"Magic inválido de {addr}")
            return
        payload = data[HEADER_SIZE:HEADER_SIZE+size]
        calc = compute_checksum(header[:-4] + payload)
        if calc != recv_checksum:
            logging.error(f"CRC inválido de {addr}, seq={seq}")
            return
        # Processa tipos
        if ptype == TYPE_REQUEST:
            text = payload.decode('utf-8')
            if text.startswith("GET /"):
                filename = text[5:]
                logging.info(f"Requisição GET de {addr}: {filename}")
                self.start_transfer(filename, addr)
            elif text.startswith("RESEND "):
                seq_req = int(text.split()[1])
                logging.info(f"Requisição RESEND de {addr}: seq={seq_req}")
                self.resend_segment(addr, seq_req)
        elif ptype == TYPE_ACK:
            logging.info(f"ACK recebido de {addr}, seq={seq}")
            self.handle_ack(addr, seq)

    def start_transfer(self, filename: str, addr: Tuple[str,int]):
        path = os.path.join(self.directory, filename)
        if not os.path.exists(path):
            self.send_error(addr, f"Arquivo {filename} não encontrado")
            return
        filesize = os.path.getsize(path)
        total_segments = (filesize + MAX_PAYLOAD - 1) // MAX_PAYLOAD
        file_obj = open(path, 'rb')
        self.clients[addr] = {
            'file': file_obj,
            'total': total_segments,
            'current': 0,
            'last_send': 0.0,
            'retries': 0,
            'start_time': time.time()
        }
        logging.info(f"Iniciando transferência de {filename}: {filesize} bytes em {total_segments} segmentos para {addr}")
        self.send_next(addr)

    def send_next(self, addr: Tuple[str,int]):
        st = self.clients.get(addr)
        if not st: return
        i, total = st['current'], st['total']
        if i >= total:
            duration = time.time() - st['start_time']
            logging.info(f"Transferência completa para {addr} em {duration:.2f}s")
            return
        file_obj = st['file']
        file_obj.seek(i * MAX_PAYLOAD)
        chunk = file_obj.read(MAX_PAYLOAD)
        flags = FLAG_LAST if i == total-1 else FLAG_NORMAL
        header = struct.pack('!HBIH I B'.replace(' ', ''),
                             MAGIC_NUMBER, TYPE_DATA, i, len(chunk), total, flags)
        checksum = compute_checksum(header + chunk)
        packet = header + checksum + chunk
        self.socket.sendto(packet, addr)
        st['last_send'] = time.time()
        logging.info(f"Enviado segmento {i}/{total-1} para {addr}")

    def handle_ack(self, addr: Tuple[str,int], seq: int):
        st = self.clients.get(addr)
        if not st or seq != st['current']: return
        st['current'] += 1
        st['retries'] = 0
        self.send_next(addr)

    def check_retransmissions(self):
        now = time.time()
        for addr, st in list(self.clients.items()):
            if now - st['last_send'] > TIMEOUT:
                if st['retries'] >= MAX_RETRIES:
                    logging.error(f"Abortando {addr} após {MAX_RETRIES} falhas")
                    st['file'].close()
                    del self.clients[addr]
                else:
                    st['retries'] += 1
                    logging.warning(f"Timeout de ACK para {addr}, retransmitindo seq={st['current']}")
                    self.send_next(addr)

    def resend_segment(self, addr: Tuple[str,int], seq_req: int):
        st = self.clients.get(addr)
        if not st or seq_req < 0 or seq_req >= st['total']: return
        prev = st['current']
        st['current'] = seq_req
        self.send_next(addr)
        st['current'] = prev

    def send_error(self, addr: Tuple[str,int], msg: str):
        payload = msg.encode('utf-8')
        header = struct.pack('!HBIH I B'.replace(' ', ''),
                             MAGIC_NUMBER, TYPE_ERROR, 0, len(payload), 0, 0)
        checksum = compute_checksum(header + payload)
        self.socket.sendto(header + checksum + payload, addr)
        logging.error(f"Erro enviado a {addr}: {msg}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="UDP File Server confiável")
    parser.add_argument('port', type=int, help='Porta UDP (>1024)')
    parser.add_argument('--dir', type=str, default='.', help='Diretório de arquivos (opcional)')
    args = parser.parse_args()
    UDPServer(args.port, args.dir).run()
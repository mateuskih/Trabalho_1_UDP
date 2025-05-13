"""
Exemplo de requisição no cliente no PowerShell ou terminal:

  python cliente_modificado.py GET 0.0.0.0:5000/teste_1mb.dat --loss 5

Onde:
  GET           - verbo de requisição sobre UDP
  0.0.0.0:5000  - IP e porta do servidor
  teste_1mb.dat - nome do arquivo a ser baixado
  --loss 5      - taxa de perda intencional de 5%
"""
import socket
import argparse
import struct
import zlib
import random
import time
import logging
import os
from typing import Dict, Set, Tuple

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

MAGIC_NUMBER = 0x0000
MAX_PAYLOAD   = 1024 * 8
HEADER_SIZE   = 18 # 14 bytes de campos + 4 bytes de checksum

TYPE_REQUEST = 0
TYPE_DATA    = 1
TYPE_ACK     = 2
TYPE_ERROR   = 3


def compute_checksum(data: bytes) -> bytes:
    """Calcula checksum CRC32 em 4 bytes big-endian"""
    checksum = zlib.crc32(data) & 0xFFFFFFFF
    return struct.pack('!I', checksum)

class UDPClient:
    def __init__(self, loss: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2.0)
        self.loss_rate = loss
        self.segments: Dict[int, bytes] = {}
        self.lost: Set[int] = set()
        self.start_time = None

    def parse_target(self, target: str) -> Tuple[str,int,str]:
        """Interpreta string IP:Port/arquivo.ext"""
        ipport, fname = target.split('/', 1)
        ip, port = ipport.split(':')
        return ip, int(port), fname

    def make_request(self, fname: str) -> bytes:
        """Monta pacote REQUEST GET /fname"""
        txt = f"GET /{fname}".encode('utf-8')
        header = struct.pack('!HBIH I B'.replace(' ', ''),
                             MAGIC_NUMBER, TYPE_REQUEST, 0, len(txt), 0, 0)
        return header + compute_checksum(header + txt) + txt

    def make_ack(self, seq: int) -> bytes:
        """Monta pacote ACK para seq informado"""
        header = struct.pack('!HBIH I B'.replace(' ', ''),
                             MAGIC_NUMBER, TYPE_ACK, seq, 0, 0, 0)
        return header + compute_checksum(header)

    def start(self, command: str, target: str):
        """Executa o download: ENVIA REQUEST, recebe e monta arquivo"""
        if command.upper() != 'GET':
            logging.error(f"Comando inválido: {command}. Use GET.")
            return
        ip, port, fname = self.parse_target(target)
        addr = (ip, port)
        logging.info(f"Conectando a {ip}:{port} para baixar '{fname}'")
        # Envia pacote REQUEST
        self.sock.sendto(self.make_request(fname), addr)
        self.start_time = time.time()
        total = None

        while True:
            try:
                packet, _ = self.sock.recvfrom(MAX_PAYLOAD + HEADER_SIZE)
                header = packet[:HEADER_SIZE]
                magic, ptype, seq, size, tot, flags, recv_crc = \
                    struct.unpack('!HBIH I B4s'.replace(' ', ''), header)
                payload = packet[HEADER_SIZE:HEADER_SIZE+size]
                if magic != MAGIC_NUMBER:
                    continue
                # Verifica CRC
                if compute_checksum(header[:-4] + payload) != recv_crc:
                    logging.warning(f"Corrupção no segmento {seq}")
                    self.lost.add(seq)
                    continue
                # Simula perda intencional
                if random.randint(1,100) <= self.loss_rate:
                    logging.warning(f"Descartei intencionalmente segmento {seq}")
                    self.lost.add(seq)
                    continue
                if ptype == TYPE_DATA:
                    if total is None:
                        total = tot
                        logging.info(f"Esperando {total} segmentos...")
                    logging.info(f"Recebido segmento {seq}/{total-1}")
                    # Envia ACK
                    self.sock.sendto(self.make_ack(seq), addr)
                    # Armazena payload
                    self.segments[seq] = payload
                    if len(self.segments) == total - len(self.lost):
                        break
                elif ptype == TYPE_ERROR:
                    logging.error(f"Erro do servidor: {payload.decode()}")
                    return
            except socket.timeout:
                logging.warning("Timeout de recepção")
                break

        # Retransmissões sob demanda
        if self.lost:
            logging.info(f"Pacotes perdidos: {sorted(self.lost)}")
            ans = input("Recuperar perdidos? (s/n): ")
            if ans.lower().startswith('s'):
                for seq in sorted(self.lost):
                    msg = f"RESEND {seq}".encode('utf-8')
                    hdr = struct.pack('!HBIH I B'.replace(' ', ''),
                                      MAGIC_NUMBER, TYPE_REQUEST, 0, len(msg), 0, 0)
                    self.sock.sendto(hdr + compute_checksum(hdr + msg) + msg, addr)
                    # Recebe reenvio
                    data, _ = self.sock.recvfrom(MAX_PAYLOAD + HEADER_SIZE)
                    hdr2 = data[:HEADER_SIZE]
                    _, _, seq2, size2, _, _, _ = \
                        struct.unpack('!HBIH I B4s'.replace(' ', ''), hdr2)
                    payload2 = data[HEADER_SIZE:HEADER_SIZE+size2]
                    self.segments[seq2] = payload2
                    logging.info(f"Recuperado segmento {seq2}")

        # Montagem final
        duration = time.time() - self.start_time
        out = f"recebido_{os.path.basename(fname)}"
        with open(out, 'wb') as f:
            for i in sorted(self.segments):
                f.write(self.segments[i])
        logging.info(f"Arquivo salvo como {out}")
        logging.info(f"Transferência concluída em {duration:.2f}s, {len(self.segments)} segmentos, {len(self.lost)} perdidos")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="UDP File Client confiável")
    parser.add_argument('command', choices=['GET'], help="Comando de requisição (GET)")
    parser.add_argument('target', help="Formato IP:Port/arquivo.ext")
    parser.add_argument('--loss', type=int, default=0, help="Taxa de perda (%)")
    args = parser.parse_args()

    client = UDPClient(args.loss)
    client.start(args.command, args.target)

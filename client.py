"""
Uso:
  python client.py GET 127.0.0.1:5000/teste_1mb.dat --loss 5
"""

import socket
import argparse
import struct
import uuid
import zlib
import random
import time
import logging
import os
from typing import Dict, Set, Tuple

# --- Configuração de logs ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# --- Protocolo ---
MAGIC_NUMBER = 0x0000
MAX_PAYLOAD  = 1500
HEADER_SIZE  = 18
MAX_RETRIES  = 3

TYPE_REQ, TYPE_DATA, TYPE_ACK, TYPE_ERR = 0,1,2,3



def compute_checksum(data: bytes) -> bytes:
    return struct.pack('!I', zlib.crc32(data) & 0xFFFFFFFF)


class UDPClient:
    def __init__(self, loss: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2.0)
        self.loss_rate = loss
        self.segments: Dict[int, bytes] = {}
        self.start_time = None

    def parse_target(self, target: str) -> Tuple[str,int,str]:
        ipport, fname = target.split('/', 1)
        ip, port = ipport.split(':')
        return ip, int(port), fname

    def make_request(self, text: str) -> bytes:
        hdr = struct.pack('!HBIHIB',
                          MAGIC_NUMBER, TYPE_REQ, 0,
                          len(text), 0, 0)
        return hdr + compute_checksum(hdr + text.encode()) + text.encode()

    def make_ack(self, seq: int) -> bytes:
        hdr = struct.pack('!HBIHIB',
                          MAGIC_NUMBER, TYPE_ACK, seq,
                          0, 0, 0)
        return hdr + compute_checksum(hdr)

    def start(self, command: str, target: str):
        if command.upper() != 'GET':
            logging.error("Comando inválido. Use GET.")
            return

        ip, port, fname = self.parse_target(target)
        addr = (ip, port)
        os.makedirs('received', exist_ok=True)
        uid = uuid.uuid4().hex[:8]

        logging.info(f"Conectando a {ip}:{port} para baixar '{fname}'")
        # envia GET
        self.sock.sendto(self.make_request(f"GET /{fname}"), addr)
        self.start_time = time.time()
        total = None

        # 1) recepção inicial
        while True:
            try:
                packet, _ = self.sock.recvfrom(MAX_PAYLOAD + HEADER_SIZE)
            except socket.timeout:
                logging.warning("Timeout de recepção (possível fim de envio)")
                break

            header = packet[:HEADER_SIZE]
            magic, ptype, seq, size, tot, flags, recv_crc = struct.unpack('!HBIHIB4s', header)
            payload = packet[HEADER_SIZE:HEADER_SIZE+size]

            if magic != MAGIC_NUMBER:
                continue

            # integridade
            if compute_checksum(header[:-4] + payload) != recv_crc:
                logging.warning(f"Corrupção no segmento {seq}")
                self.sock.sendto(self.make_ack(seq), addr)
                continue

            # simula perda
            if random.randint(1,100) <= self.loss_rate:
                logging.warning(f"Simulação de perda: descartou segmento {seq}")
                self.sock.sendto(self.make_ack(seq), addr)
                continue

            if ptype == TYPE_DATA:
                if total is None:
                    total = tot
                    logging.info(f"Esperando {total} segmentos...")
                logging.info(f"Recebido segmento {seq}/{total-1}")
                self.sock.sendto(self.make_ack(seq), addr)
                self.segments.setdefault(seq, payload)
                if len(self.segments) == total:
                    logging.info("Todos os segmentos recebidos")
                    break

            elif ptype == TYPE_ERR:
                logging.error(f"Erro do servidor: {payload.decode()}")
                return

        if total is None:
            logging.error("Não recebeu metadados de total de segmentos.")
            return

        # 2) recuperação
        missing = sorted(set(range(total)) - set(self.segments.keys()))
        if missing:
            logging.info(f"Segmentos faltantes: {missing}")
            ans = input("Recuperar perdidos? (s/n): ")
            if ans.lower().startswith('s'):
                for seq in missing:
                    recovered = False
                    for attempt in range(1, MAX_RETRIES+1):
                        # envia RESEND
                        self.sock.sendto(self.make_request(f"RESEND {seq}"), addr)
                        try:
                            data, _ = self.sock.recvfrom(MAX_PAYLOAD + HEADER_SIZE)
                        except socket.timeout:
                            logging.warning(f"Tentativa {attempt}/{MAX_RETRIES} sem resposta para seq {seq}")
                            continue

                        h2 = data[:HEADER_SIZE]
                        magic2, ptype2, seq2, size2, _, _, crc2 = struct.unpack('!HBIHIB4s', h2)
                        p2 = data[HEADER_SIZE:HEADER_SIZE+size2]
                        if magic2 == MAGIC_NUMBER and ptype2 == TYPE_DATA \
                           and seq2 == seq and compute_checksum(h2[:-4]+p2) == crc2:
                            logging.info(f"Recuperado segmento {seq2}")
                            self.sock.sendto(self.make_ack(seq2), addr)
                            self.segments[seq2] = p2
                            recovered = True
                            break
                        else:
                            logging.warning(f"Resposta inesperada ou CRC inválido no reenvio de seq {seq}")
                    if not recovered:
                        logging.error(f"Falha ao recuperar segmento {seq} após {MAX_RETRIES} tentativas")
            else:
                # grava parcial
                out = os.path.join('received', f"{uid}_{fname}")
                with open(out, 'wb') as f:
                    for i in sorted(self.segments):
                        f.write(self.segments[i])
                logging.info(f"Arquivo parcial salvo em {out}")
                return

        # 3) montagem final
        out = os.path.join('received', f"{uid}_{fname}")
        with open(out, 'wb') as f:
            for i in range(total):
                f.write(self.segments[i])
        duration = time.time() - self.start_time
        logging.info(f"Arquivo completo salvo em {out}")
        logging.info(f"Transferência concluída em {duration:.2f}s, {total} segmentos, "
                     f"{len(missing)} recuperados")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="UDP File Client confiável")
    parser.add_argument('command', choices=['GET'], help="Comando de requisição (GET)")
    parser.add_argument('target', help="Formato IP:Port/arquivo.ext")
    parser.add_argument('--loss', type=int, default=0, help="Taxa de perda (%)")
    args = parser.parse_args()

    client = UDPClient(args.loss)
    client.start(args.command, args.target)

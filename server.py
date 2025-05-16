"""
Uso:
  python server.py 5000

"""

import socket, threading, queue, os, struct, zlib, time, logging
from typing import Tuple, Dict

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

MTU, IP_HDR, UDP_HDR = 1500, 20, 8
MAGIC = 0x0000
HDR_FMT = '!HBIHIB4s'  # MAGIC(2) TYPE(1) SEQ(4) SIZE(2) TOTAL(4) FLAGS(1) CRC(4)
HDR_SZ = struct.calcsize(HDR_FMT)
MAX_PAYLOAD = MTU - IP_HDR - UDP_HDR - HDR_SZ

TIMEOUT      = 2.0
MAX_RETRIES  = 3
RECOVER_WIN  = 5.0    # segundos para aceitar RESENDs pós-FLAG_LAST
LATENCY      = 0.05

TYPE_REQ, TYPE_DATA, TYPE_ACK, TYPE_ERR = 0,1,2,3
FLAG_NORMAL, FLAG_LAST = 0,1

def crc32(data: bytes) -> bytes:
    return struct.pack('!I', zlib.crc32(data) & 0xFFFFFFFF)

class ClientHandler(threading.Thread):
    def __init__(self, server, addr, q):
        super().__init__(daemon=True)
        self.srv = server
        self.addr = addr
        self.q = q
        self.state = None
        self.finished_at = None

    def run(self):
        # 1) espera REQUEST
        try:
            pkt = self.q.get(timeout=TIMEOUT)
        except queue.Empty:
            logging.error(f"{self.addr}: sem REQUEST, abortando")
            return self.cleanup()

        h,p = pkt[:HDR_SZ], pkt[HDR_SZ:]
        magic, ptype, _, size, _, _, _ = struct.unpack(HDR_FMT, h)
        if magic!=MAGIC or ptype!=TYPE_REQ:
            logging.error(f"{self.addr}: primeiro pacote inválido")
            return self.cleanup()

        text = p[:size].decode().strip().split()
        if len(text)!=2 or text[0].upper()!='GET':
            logging.error(f"{self.addr}: REQUEST mal formatado: {p[:size]!r}")
            return self.cleanup()

        fname = text[1].lstrip('/')
        path = os.path.join(self.srv.directory, fname)
        if not os.path.exists(path):
            self.srv.send_error(self.addr, f"'{fname}' não encontrado")
            return self.cleanup()

        # 2) inicializa estado
        sz = os.path.getsize(path)
        total = (sz + MAX_PAYLOAD-1)//MAX_PAYLOAD
        f = open(path,'rb')
        self.state = {
            'file': f,
            'total': total,
            'current': 0,
            'retries': 0,
            'last_send': 0.0,
            'last_seq': total-1
        }
        logging.info(f"{self.addr}: enviando '{fname}' ({sz}B em {total} segs)")
        self.send_next()

        # 3) loop: ACKs, RESEND, timeout
        while True:
            # se último ACK recebido, abre janela de RESEND
            if self.finished_at:
                try:
                    pkt = self.q.get(timeout=RECOVER_WIN)
                except queue.Empty:
                    logging.info(f"{self.addr}: tempo de recuperação esgotado")
                    break
            else:
                try:
                    pkt = self.q.get(timeout=TIMEOUT)
                except queue.Empty:
                    if not self.retransmit():
                        logging.error(f"{self.addr}: retries excedidos")
                        break
                    continue

            h = pkt[:HDR_SZ]; b = pkt[HDR_SZ:]
            magic, ptype, seq, size, _, flags, crc_recv = struct.unpack(HDR_FMT, h)
            payload = b[:size]
            if magic!=MAGIC or crc32(h[:-4]+payload)!=crc_recv:
                logging.warning(f"{self.addr}: CRC/magic inválido")
                continue

            if ptype==TYPE_ACK:
                logging.info(f"{self.addr}: ACK seq={seq}")
                # se é o ACK do último segmento, marca finish
                if seq==self.state['last_seq']:
                    self.finished_at = time.time()
                    logging.info(f"{self.addr}: ACK de FLAG_LAST recebido")
                self.handle_ack(seq)

            elif ptype==TYPE_REQ:
                txt = payload.decode().strip().split()
                if txt[0].upper()=='RESEND':
                    seqr = int(txt[1])
                    logging.info(f"{self.addr}: RESEND seq={seqr}")
                    self.resend_segment(seqr)
                else:
                    logging.warning(f"{self.addr}: REQUEST inesperado: {txt!r}")

        self.cleanup()

    def send_next(self):
        st = self.state; i,tot = st['current'], st['total']
        if i>=tot: return
        f=st['file']; f.seek(i*MAX_PAYLOAD)
        chunk=f.read(MAX_PAYLOAD)
        fl = FLAG_LAST if i==tot-1 else FLAG_NORMAL

        h = struct.pack('!HBIHIB', MAGIC, TYPE_DATA, i, len(chunk), tot, fl)
        pkt = h + crc32(h+chunk) + chunk
        self.srv.socket.sendto(pkt, self.addr)
        
        st['last_send']=time.time()
        logging.info(f"{self.addr}: enviado seg {i}/{tot-1}")
        time.sleep(LATENCY)

    def handle_ack(self, seq):
        st=self.state
        if seq==st['current']:
            st['current']+=1; st['retries']=0
            self.send_next()

    def retransmit(self):
        st=self.state
        if time.time()-st['last_send']<TIMEOUT: return True
        if st['retries']>=MAX_RETRIES: return False
        st['retries']+=1
        logging.warning(f"{self.addr}: timeout seg {st['current']}, retry")
        self.send_next()
        return True

    def resend_segment(self, n):
        st=self.state
        if 0<=n<st['total']:
            prev=st['current']; st['current']=n
            self.send_next(); st['current']=prev

    def cleanup(self):
        if self.state:
            self.state['file'].close()
        self.srv.remove_client(self.addr)
        logging.info(f"{self.addr}: handler finalizado")


class UDPServer:
    def __init__(self, port:int):
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.socket.bind(('',port))
        self.directory='files'
        os.makedirs(self.directory,exist_ok=True)
        self.queues:Dict[Tuple[str,int],queue.Queue]={}
        logging.info(f"Servidor iniciado UDP 0.0.0.0:{port}, servindo 'files/'")

    def run(self):
        while True:
            try:
                data,addr=self.socket.recvfrom(HDR_SZ+MAX_PAYLOAD)
            except ConnectionResetError:
                continue
            if addr not in self.queues:
                q=queue.Queue()
                self.queues[addr]=q
                ClientHandler(self,addr,q).start()
            self.queues[addr].put(data)

    def remove_client(self,addr):
        self.queues.pop(addr,None)

    def send_error(self,addr,msg):
        p=msg.encode()
        h=struct.pack('!HBIHIB',MAGIC,TYPE_ERR,0,len(p),0,0)
        pkt=h+crc32(h+p)+p
        self.socket.sendto(pkt,addr)
        logging.error(f"{addr}: erro '{msg}' enviado")


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('port',type=int)
    args=p.parse_args()
    UDPServer(args.port).run()

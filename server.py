import socket
import argparse
import os
import struct
import zlib
import time
import select
from typing import Tuple, Optional, Dict

# Constants for the protocol
MAGIC_NUMBER = 0x0000 
MAX_PAYLOAD = 1024
HEADER_SIZE = 18
TIMEOUT = 0.5  # seconds
MAX_RETRIES = 5

# Packet types
TYPE_REQUEST = 0
TYPE_DATA = 1
TYPE_ACK = 2
TYPE_ERROR = 3

# Flags
FLAG_LAST = 1
FLAG_NORMAL = 0

class UDPServer:
    def __init__(self, port: int, directory: str):
        self.port = port
        self.directory = directory
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('', port))
        self.clients: Dict[Tuple[str, int], dict] = {}
        print(f"Server started on port {port}, serving files from {directory}")
        
    def run(self):
        """Main server loop to handle client requests"""
        while True:
            try:
                # Wait for data from any client
                ready = select.select([self.socket], [], [], 1.0)
                if ready[0]:
                    data, client_address = self.socket.recvfrom(2048)
                    self.handle_packet(data, client_address)
                
                # Check for clients that need retransmission
                self.check_retransmissions()
                    
            except KeyboardInterrupt:
                print("Server shutting down...")
                break
            except Exception as e:
                print(f"Error: {e}")

    def handle_packet(self, data: bytes, client_address: Tuple[str, int]):
        """Process received packet based on its type"""
        try:
            # Parse the header
            if len(data) < HEADER_SIZE:
                print(f"Received malformed packet from {client_address}")
                return
                
            magic, packet_type, seq_num, payload_size, total_segments, flags, received_checksum = struct.unpack(
                '!HIBHIB4s', data[:HEADER_SIZE]
            )
            
            # Verify magic number
            if magic != MAGIC_NUMBER:
                print(f"Invalid magic number from {client_address}")
                return
                
            # Extract the payload
            payload = data[HEADER_SIZE:HEADER_SIZE + payload_size]
            
            # Verify checksum (excluding the checksum field itself)
            checksum_data = data[:HEADER_SIZE-4] + data[HEADER_SIZE:]
            calculated_checksum = zlib.crc32(checksum_data) & 0xFFFFFFFF
            received_checksum = int.from_bytes(received_checksum, byteorder='big')
            
            if calculated_checksum != received_checksum:
                print(f"Checksum mismatch from {client_address}: expected {calculated_checksum}, got {received_checksum}")
                return
                
            # Handle by packet type
            if packet_type == TYPE_REQUEST:
                self.handle_request(payload.decode('utf-8'), client_address)
            elif packet_type == TYPE_ACK:
                self.handle_ack(seq_num, client_address)
            else:
                print(f"Unexpected packet type {packet_type} from {client_address}")
                
        except Exception as e:
            print(f"Error handling packet: {e}")

    def handle_request(self, request: str, client_address: Tuple[str, int]):
        """Process a file request from client"""
        if not request.startswith("GET /"):
            self.send_error(client_address, "Invalid request format")
            return
            
        # Extract filename from request
        filename = request[5:].strip()
        file_path = os.path.join(self.directory, filename)
        
        print(f"Client {client_address} requested file: {filename}")
        
        # Check if file exists
        if not os.path.exists(file_path):
            self.send_error(client_address, f"File {filename} not found")
            return
            
        # Prepare for file transfer
        try:
            file_size = os.path.getsize(file_path)
            total_segments = (file_size + MAX_PAYLOAD - 1) // MAX_PAYLOAD
            
            # Create client state
            self.clients[client_address] = {
                'file': open(file_path, 'rb'),
                'filename': filename,
                'file_size': file_size,
                'total_segments': total_segments,
                'current_segment': 0,
                'last_send_time': 0,
                'retries': 0
            }
            
            print(f"Starting transfer of {filename} ({file_size} bytes, {total_segments} segments)")
            # Send first segment
            self.send_next_segment(client_address)
            
        except Exception as e:
            self.send_error(client_address, f"Error preparing file: {e}")
    
    def send_next_segment(self, client_address: Tuple[str, int]) -> bool:
        """Send the next file segment to the client"""
        client = self.clients.get(client_address)
        if not client:
            return False
            
        file = client['file']
        current_segment = client['current_segment']
        total_segments = client['total_segments']
        
        if current_segment >= total_segments:
            # Transfer complete
            file.close()
            del self.clients[client_address]
            print(f"File transfer to {client_address} completed!")
            return False
            
        # Read payload from file
        file.seek(current_segment * MAX_PAYLOAD)
        payload = file.read(MAX_PAYLOAD)
        
        # Determine if this is the last segment
        is_last = (current_segment == total_segments - 1)
        flags = FLAG_LAST if is_last else FLAG_NORMAL
        
        # Send the data packet
        self.send_data_packet(client_address, current_segment, payload, total_segments, flags)
        
        # Update client state
        client['last_send_time'] = time.time()
        return True
        
    def send_data_packet(self, client_address: Tuple[str, int], seq_num: int, payload: bytes, 
                         total_segments: int, flags: int):
        """Create and send a DATA packet"""
        # Prepare header without checksum
        header_without_checksum = struct.pack(
            '!HIBHIB', 
            MAGIC_NUMBER, 
            TYPE_DATA, 
            seq_num, 
            len(payload), 
            total_segments,
            flags
        )
        
        # Calculate checksum over header (without checksum field) + payload
        checksum = zlib.crc32(header_without_checksum + payload) & 0xFFFFFFFF
        
        # Complete header with checksum
        header = header_without_checksum + struct.pack('!I', checksum)
        
        # Send the packet
        self.socket.sendto(header + payload, client_address)
        
        print(f"Sent segment {seq_num}/{total_segments-1} to {client_address} ({len(payload)} bytes)")
    
    def handle_ack(self, seq_num: int, client_address: Tuple[str, int]):
        """Process ACK from client"""
        client = self.clients.get(client_address)
        if not client:
            print(f"Received ACK from unknown client {client_address}")
            return
            
        if seq_num == client['current_segment']:
            print(f"Received ACK for segment {seq_num} from {client_address}")
            
            # Move to next segment
            client['current_segment'] += 1
            client['retries'] = 0
            
            # Send next segment
            self.send_next_segment(client_address)
        else:
            print(f"Received out-of-order ACK from {client_address}: got {seq_num}, expected {client['current_segment']}")
    
    def check_retransmissions(self):
        """Check for packets that need retransmission due to timeout"""
        current_time = time.time()
        
        for client_address, client in list(self.clients.items()):
            if current_time - client['last_send_time'] > TIMEOUT:
                # Timeout occurred
                if client['retries'] >= MAX_RETRIES:
                    print(f"Max retries reached for {client_address}, aborting transfer")
                    client['file'].close()
                    del self.clients[client_address]
                else:
                    print(f"Timeout for segment {client['current_segment']}, retransmitting")
                    client['retries'] += 1
                    client['last_send_time'] = current_time
                    
                    # Resend the current segment
                    file = client['file']
                    current_segment = client['current_segment']
                    total_segments = client['total_segments']
                    
                    # Read payload from file again
                    file.seek(current_segment * MAX_PAYLOAD)
                    payload = file.read(MAX_PAYLOAD)
                    
                    # Determine if this is the last segment
                    is_last = (current_segment == total_segments - 1)
                    flags = FLAG_LAST if is_last else FLAG_NORMAL
                    
                    # Resend the packet
                    self.send_data_packet(client_address, current_segment, payload, total_segments, flags)
    
    def send_error(self, client_address: Tuple[str, int], message: str):
        """Send an error message to the client"""
        print(f"Sending error to {client_address}: {message}")
        
        payload = message.encode('utf-8')
        
        # Prepare header without checksum
        header_without_checksum = struct.pack(
            '!HIBHIB', 
            MAGIC_NUMBER, 
            TYPE_ERROR, 
            0,  # seq_num not relevant for error 
            len(payload), 
            0,  # total_segments not relevant for error
            0   # flags not relevant for error
        )
        
        # Calculate checksum
        checksum = zlib.crc32(header_without_checksum + payload) & 0xFFFFFFFF
        
        # Complete header with checksum
        header = header_without_checksum + struct.pack('!I', checksum)
        
        # Send the packet
        self.socket.sendto(header + payload, client_address)

def main():
    parser = argparse.ArgumentParser(description="UDP File Transfer Server")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    parser.add_argument("--directory", type=str, default="./files", help="Directory containing files to serve")
    
    args = parser.parse_args()
    
    # Create directory if it doesn't exist
    if not os.path.exists(args.directory):
        os.makedirs(args.directory)
    
    server = UDPServer(args.port, args.directory)
    server.run()

if __name__ == "__main__":
    main()
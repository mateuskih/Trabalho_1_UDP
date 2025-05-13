import socket
import argparse
import struct
import zlib
import time
import random
import os
from typing import Dict, List, Optional

# Constants for the protocol (matching server implementation)
MAGIC_NUMBER = 0x0000
MAX_PAYLOAD = 1024
HEADER_SIZE = 18
TIMEOUT = 2.0  # seconds

# Packet types
TYPE_REQUEST = 0
TYPE_DATA = 1
TYPE_ACK = 2
TYPE_ERROR = 3

# Flags
FLAG_LAST = 1
FLAG_NORMAL = 0

class UDPClient:
    def __init__(self, server_address: str, server_port: int, loss_rate: int = 0):
        self.server_address = (server_address, server_port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(TIMEOUT)
        self.loss_rate = loss_rate
        print(f"Client initialized, connecting to {server_address}:{server_port}")
        if loss_rate > 0:
            print(f"Simulating {loss_rate}% packet loss")
    
    def request_file(self, filename: str, save_path: str = None) -> bool:
        """Request a file from the server and save it locally"""
        if save_path is None:
            save_path = os.path.basename(filename)
            
        print(f"Requesting file: {filename}")
        
        # Create and send request packet
        request = f"GET /{filename}".encode('utf-8')
        
        # Prepare header without checksum
        header_without_checksum = struct.pack(
            '!HIBHIB', 
            MAGIC_NUMBER, 
            TYPE_REQUEST, 
            0,  # seq_num not relevant for request 
            len(request), 
            0,  # total_segments not known yet
            0   # flags not relevant for request
        )
        
        # Calculate checksum
        checksum = zlib.crc32(header_without_checksum + request) & 0xFFFFFFFF
        
        # Complete header with checksum
        header = header_without_checksum + struct.pack('!I', checksum)
        
        # Send the request
        self.socket.sendto(header + request, self.server_address)
        
        # Prepare for receiving the file
        segments: Dict[int, bytes] = {}
        total_segments = None
        highest_seq_received = -1
        start_time = time.time()
        
        # Open the destination file
        with open(save_path, 'wb') as output_file:
            while True:
                try:
                    # Check if we're done
                    if total_segments is not None and len(segments) == total_segments:
                        break
                        
                    # Receive a packet
                    data, server = self.socket.recvfrom(MAX_PAYLOAD + HEADER_SIZE)
                    
                    # Simulate packet loss
                    if self.loss_rate > 0 and random.randint(1, 100) <= self.loss_rate:
                        print("Simulating packet loss...")
                        continue
                    
                    # Process the packet
                    if not self.process_packet(data, segments):
                        return False
                        
                    # Get total_segments from the first data packet
                    if total_segments is None and segments:
                        # Get any segment and extract total_segments
                        _, _, _, _, total_segments_val, _, _ = self.parse_header(list(segments.values())[0])
                        total_segments = total_segments_val
                        print(f"File consists of {total_segments} segments")
                    
                    # Write segments to file in order
                    next_seq = highest_seq_received + 1
                    while next_seq in segments:
                        segment_data = segments[next_seq]
                        _, _, _, _, _, flags, _ = self.parse_header(segment_data)
                        payload = segment_data[HEADER_SIZE:]
                        
                        output_file.write(payload)
                        del segments[next_seq]
                        highest_seq_received = next_seq
                        next_seq += 1
                        
                        if flags & FLAG_LAST:
                            print("Received final segment")
                    
                except socket.timeout:
                    print("Timeout occurred, transfer may be complete or interrupted")
                    if total_segments is not None and highest_seq_received == total_segments - 1:
                        print("All segments received")
                        break
                    else:
                        print("Transfer interrupted, not all segments received")
                        return False
        
        transfer_time = time.time() - start_time
        transfer_size = os.path.getsize(save_path)
        print(f"File transfer complete: {transfer_size} bytes in {transfer_time:.2f} seconds")
        print(f"Average speed: {transfer_size / transfer_time / 1024:.2f} KB/s")
        return True
    
    def process_packet(self, data: bytes, segments: Dict[int, bytes]) -> bool:
        """Process received packet and return True if processing should continue"""
        if len(data) < HEADER_SIZE:
            print("Received malformed packet (too short)")
            return True
            
        # Parse the header
        magic, packet_type, seq_num, payload_size, total_segments, flags, received_checksum = self.parse_header(data)
        
        # Verify magic number
        if magic != MAGIC_NUMBER:
            print(f"Invalid magic number: {magic}")
            return True
        
        # Extract the payload
        payload = data[HEADER_SIZE:HEADER_SIZE + payload_size]
        
        # Verify checksum (excluding the checksum field itself)
        checksum_data = data[:HEADER_SIZE-4] + data[HEADER_SIZE:]
        calculated_checksum = zlib.crc32(checksum_data) & 0xFFFFFFFF
        received_checksum_int = int.from_bytes(received_checksum, byteorder='big')
        
        if calculated_checksum != received_checksum_int:
            print(f"Checksum mismatch for segment {seq_num}: expected {calculated_checksum}, got {received_checksum_int}")
            return True
        
        # Handle by packet type
        if packet_type == TYPE_DATA:
            print(f"Received DATA segment {seq_num}/{total_segments-1} ({len(payload)} bytes)")
            
            # Store the segment (whole packet including header)
            segments[seq_num] = data
            
            # Send ACK
            self.send_ack(seq_num)
            
            return True
            
        elif packet_type == TYPE_ERROR:
            error_msg = payload.decode('utf-8')
            print(f"Received ERROR: {error_msg}")
            return False
            
        else:
            print(f"Unexpected packet type: {packet_type}")
            return True
    
    def parse_header(self, data: bytes):
        """Parse the packet header"""
        return struct.unpack('!HIBHIB4s', data[:HEADER_SIZE])
    
    def send_ack(self, seq_num: int):
        """Send ACK packet to the server"""
        # Prepare header without checksum
        header_without_checksum = struct.pack(
            '!HIBHIB', 
            MAGIC_NUMBER, 
            TYPE_ACK, 
            seq_num, 
            0,  # payload_size is 0 for ACK 
            0,  # total_segments not relevant for ACK
            0   # flags not relevant for ACK
        )
        
        # Calculate checksum (no payload for ACK)
        checksum = zlib.crc32(header_without_checksum) & 0xFFFFFFFF
        
        # Complete header with checksum
        header = header_without_checksum + struct.pack('!I', checksum)
        
        # Send the ACK
        self.socket.sendto(header, self.server_address)
        print(f"Sent ACK for segment {seq_num}")

def main():
    parser = argparse.ArgumentParser(description="UDP File Transfer Client")
    parser.add_argument("--server", type=str, required=True, help="Server IP address")
    parser.add_argument("--port", type=int, default=5000, help="Server port")
    parser.add_argument("--file", type=str, required=True, help="File to request")
    parser.add_argument("--output", type=str, help="Output file path")
    parser.add_argument("--loss", type=int, default=0, help="Simulate packet loss percentage (0-99)")
    
    args = parser.parse_args()
    
    # Validate packet loss rate
    if args.loss < 0 or args.loss > 99:
        print("Error: Loss percentage must be between 0 and 99")
        return
    
    client = UDPClient(args.server, args.port, args.loss)
    client.request_file(args.file, args.output)

if __name__ == "__main__":
    main()
#include "tcp_handler.h"

#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <stdexcept>
#include <cstring>


static void send_all(int fd, const uint8_t* buf, size_t len) {
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = ::send(fd, buf + sent, len - sent, MSG_NOSIGNAL);
        if (n <= 0) throw std::runtime_error("TCP send failed");
        sent += n;
    }
}

static void recv_all(int fd, uint8_t* buf, size_t len) {
    size_t got = 0;
    while (got < len) {
        ssize_t n = ::recv(fd, buf + got, len - got, 0);
        if (n <= 0) throw std::runtime_error("TCP recv failed / connection closed");
        got += n;
    }
}


void tcp_server_run(uint16_t port) {
    int srv = ::socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) throw std::runtime_error("socket()");

    int opt = 1;
    ::setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port        = htons(port);

    if (::bind(srv, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
        throw std::runtime_error("bind()");
    if (::listen(srv, 5) < 0)
        throw std::runtime_error("listen()");

    std::cout << "[TCP Server] Listening on port " << port << " ...\n";

    
    while (true) {
        sockaddr_in cli_addr{};
        socklen_t   cli_len = sizeof(cli_addr);
        int conn = ::accept(srv, reinterpret_cast<sockaddr*>(&cli_addr), &cli_len);
        if (conn < 0) { perror("accept"); continue; }

        char cli_ip[INET_ADDRSTRLEN];
        ::inet_ntop(AF_INET, &cli_addr.sin_addr, cli_ip, sizeof(cli_ip));
        std::cout << "[TCP Server] Client connected: " << cli_ip << "\n";

        try {
            
            SessionHeader hdr{};
            recv_all(conn, reinterpret_cast<uint8_t*>(&hdr), sizeof(hdr));

            Protocol     proto      = static_cast<Protocol>(hdr.protocol);
            TransferMode mode       = static_cast<TransferMode>(hdr.mode);
            size_t       block_size = ntohl(hdr.block_size);
            uint64_t     total_exp  = be64toh(hdr.total_bytes);

            std::cout << "[TCP Server] Session: proto=" << protocol_name(proto)
                      << " mode=" << mode_name(mode)
                      << " block=" << block_size
                      << " total=" << total_exp << " bytes\n";

                      
            std::vector<uint8_t> reassembled;
            reassembled.reserve(total_exp);

            std::vector<uint8_t> blk(block_size);
            uint64_t messages_recv = 0;
            uint64_t bytes_recv    = 0;

            while (bytes_recv < total_exp) {
                size_t to_read = std::min(block_size, (size_t)(total_exp - bytes_recv));
                recv_all(conn, blk.data(), to_read);
                reassembled.insert(reassembled.end(), blk.begin(), blk.begin() + to_read);
                bytes_recv    += to_read;
                messages_recv += 1;

                if (mode == TransferMode::STOP_AND_WAIT) {
                    uint8_t ack = 0xAC;
                    send_all(conn, &ack, 1);
                }
            }

            
            std::string hash = sha256_hex_incremental(reassembled);
            print_server_stats(proto, messages_recv, bytes_recv, hash);

        } catch (std::exception& e) {
            std::cerr << "[TCP Server] Error: " << e.what() << "\n";
        }

        ::close(conn);
    }
    ::close(srv);
}


void tcp_client_run(const std::string& host,
                    uint16_t           port,
                    size_t             block_size,
                    size_t             total_bytes,
                    TransferMode       mode)
{
    
    std::vector<uint8_t> payload = make_payload(total_bytes);
    std::string hash_sent = sha256_hex_incremental(payload);

    
    int sock = ::socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) throw std::runtime_error("socket()");

    sockaddr_in srv_addr{};
    srv_addr.sin_family = AF_INET;
    srv_addr.sin_port   = htons(port);
    if (::inet_pton(AF_INET, host.c_str(), &srv_addr.sin_addr) <= 0)
        throw std::runtime_error("inet_pton()");

    if (::connect(sock, reinterpret_cast<sockaddr*>(&srv_addr), sizeof(srv_addr)) < 0)
        throw std::runtime_error("connect()");

        
    int nodelay = 1;
    ::setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &nodelay, sizeof(nodelay));

    
    SessionHeader hdr{};
    hdr.protocol   = static_cast<uint8_t>(Protocol::TCP);
    hdr.mode       = static_cast<uint8_t>(mode);
    hdr.block_size = htonl(static_cast<uint32_t>(block_size));
    hdr.total_bytes = htobe64(static_cast<uint64_t>(total_bytes));
    send_all(sock, reinterpret_cast<uint8_t*>(&hdr), sizeof(hdr));

    
    uint64_t messages_sent = 0;
    uint64_t bytes_sent    = 0;
    size_t   offset        = 0;

    auto t_start = Clock::now();

    while (offset < total_bytes) {
        size_t chunk = std::min(block_size, total_bytes - offset);
        send_all(sock, payload.data() + offset, chunk);
        offset        += chunk;
        bytes_sent    += chunk;
        messages_sent += 1;

        if (mode == TransferMode::STOP_AND_WAIT) {
            uint8_t ack = 0;
            recv_all(sock, &ack, 1);
            if (ack != 0xAC)
                throw std::runtime_error("Bad ACK from server");
        }
    }

    auto t_end = Clock::now();
    double seconds = elapsed_seconds(t_start, t_end);

    ::close(sock);

    print_client_stats(Protocol::TCP, mode, block_size, total_bytes,
                       messages_sent, bytes_sent, seconds, hash_sent);
}

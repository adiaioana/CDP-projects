#include "udp_handler.h"

#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <stdexcept>
#include <cstring>
#include <map>


static constexpr uint8_t FLAG_DATA    = 0x00;
static constexpr uint8_t FLAG_SESS    = 0x01;
static constexpr uint8_t FLAG_FIN     = 0x02;
static constexpr uint8_t FLAG_ACK     = 0xAC;

static constexpr int ACK_TIMEOUT_MS   = 500;  
static constexpr int MAX_RETRANSMIT   = 10;

#pragma pack(push, 1)
struct UDPHeader {
    uint32_t seq_no;
    uint8_t  flags;
};
#pragma pack(pop)

static constexpr size_t UDP_HDR_SIZE = sizeof(UDPHeader);



static void set_recv_timeout(int sock, int ms) {
    struct timeval tv;
    tv.tv_sec  = ms / 1000;
    tv.tv_usec = (ms % 1000) * 1000;
    ::setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
}

static void clear_recv_timeout(int sock) {
    struct timeval tv{};
    ::setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
}


static size_t build_packet(std::vector<uint8_t>& out_buf,
                            uint32_t seq_no, uint8_t flags,
                            const uint8_t* payload, size_t pay_len)
{
    size_t total = UDP_HDR_SIZE + pay_len;
    out_buf.resize(total);
    UDPHeader hdr{ htonl(seq_no), flags };
    memcpy(out_buf.data(), &hdr, UDP_HDR_SIZE);
    if (pay_len) memcpy(out_buf.data() + UDP_HDR_SIZE, payload, pay_len);
    return total;
}

void udp_server_run(uint16_t port) {
    int sock = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) throw std::runtime_error("socket()");

    
    int rcvbuf = 16 * 1024 * 1024;
    ::setsockopt(sock, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf));

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port        = htons(port);
    if (::bind(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0)
        throw std::runtime_error("bind()");

    std::cout << "[UDP Server] Listening on port " << port << " ...\n";

    std::vector<uint8_t> recv_buf(65535 + UDP_HDR_SIZE + sizeof(SessionHeader) + 16);

    while (true) {
        
        sockaddr_in cli_addr{};
        socklen_t   cli_len = sizeof(cli_addr);

        SessionHeader sess{};
        bool got_session = false;

        while (!got_session) {
            ssize_t n = ::recvfrom(sock, recv_buf.data(), recv_buf.size(), 0,
                                   reinterpret_cast<sockaddr*>(&cli_addr), &cli_len);
            if (n < (ssize_t)UDP_HDR_SIZE) continue;
            UDPHeader hdr;
            memcpy(&hdr, recv_buf.data(), UDP_HDR_SIZE);
            if (hdr.flags != FLAG_SESS) continue;
            memcpy(&sess, recv_buf.data() + UDP_HDR_SIZE, sizeof(sess));
            got_session = true;
        }

        Protocol     proto      = static_cast<Protocol>(sess.protocol);
        TransferMode mode       = static_cast<TransferMode>(sess.mode);
        uint32_t     block_size = ntohl(sess.block_size);
        uint64_t     total_exp  = be64toh(sess.total_bytes);

        char cli_ip[INET_ADDRSTRLEN];
        ::inet_ntop(AF_INET, &cli_addr.sin_addr, cli_ip, sizeof(cli_ip));
        std::cout << "[UDP Server] Session from " << cli_ip
                  << " proto=" << protocol_name(proto)
                  << " mode=" << mode_name(mode)
                  << " block=" << block_size
                  << " total=" << total_exp << "\n";

                  
        {
            std::vector<uint8_t> ack_pkt;
            build_packet(ack_pkt, 0, FLAG_ACK, nullptr, 0);
            ::sendto(sock, ack_pkt.data(), ack_pkt.size(), 0,
                     reinterpret_cast<sockaddr*>(&cli_addr), cli_len);
        }

        
        std::map<uint32_t, std::vector<uint8_t>> recv_map;
        uint64_t bytes_recv    = 0;
        uint64_t messages_recv = 0;
        uint32_t expected_seq  = 1;
        bool     finished      = false;

        
        set_recv_timeout(sock, 2000);

        while (!finished) {
            ssize_t n = ::recvfrom(sock, recv_buf.data(), recv_buf.size(), 0,
                                   reinterpret_cast<sockaddr*>(&cli_addr), &cli_len);
            if (n < (ssize_t)UDP_HDR_SIZE) continue;

            UDPHeader hdr;
            memcpy(&hdr, recv_buf.data(), UDP_HDR_SIZE);
            uint32_t seq  = ntohl(hdr.seq_no);
            uint8_t  flag = hdr.flags;

            if (flag == FLAG_FIN) {
                
                std::vector<uint8_t> fin_ack;
                build_packet(fin_ack, seq, FLAG_ACK, nullptr, 0);
                for (int i = 0; i < 3; ++i)
                    ::sendto(sock, fin_ack.data(), fin_ack.size(), 0,
                             reinterpret_cast<sockaddr*>(&cli_addr), cli_len);
                finished = true;
                break;
            }

            if (flag != FLAG_DATA) continue;

            size_t pay_len = n - UDP_HDR_SIZE;

            if (recv_map.find(seq) == recv_map.end()) {
                
                recv_map[seq] = std::vector<uint8_t>(recv_buf.begin() + UDP_HDR_SIZE,
                                                     recv_buf.begin() + UDP_HDR_SIZE + pay_len);
                bytes_recv    += pay_len;
                messages_recv += 1;
            }
            

            if (mode == TransferMode::STOP_AND_WAIT) {
                std::vector<uint8_t> ack_pkt;
                build_packet(ack_pkt, seq, FLAG_ACK, nullptr, 0);
                ::sendto(sock, ack_pkt.data(), ack_pkt.size(), 0,
                         reinterpret_cast<sockaddr*>(&cli_addr), cli_len);
            }
        }

        clear_recv_timeout(sock);

        
        std::vector<uint8_t> reassembled;
        reassembled.reserve(total_exp);
        for (auto& [seq, data] : recv_map)
            reassembled.insert(reassembled.end(), data.begin(), data.end());

        std::string hash = sha256_hex_incremental(reassembled);
        print_server_stats(proto, messages_recv, bytes_recv, hash);
    }

    ::close(sock);
}


void udp_client_run(const std::string& host,
                    uint16_t           port,
                    size_t             block_size,
                    size_t             total_bytes,
                    TransferMode       mode)
{
    if (block_size > MAX_UDP_PAYLOAD)
        throw std::runtime_error("block_size exceeds max UDP payload");

        
    std::vector<uint8_t> payload = make_payload(total_bytes);
    std::string hash_sent = sha256_hex_incremental(payload);

    
    int sock = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) throw std::runtime_error("socket()");

    int sndbuf = 16 * 1024 * 1024;
    ::setsockopt(sock, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof(sndbuf));

    sockaddr_in srv_addr{};
    srv_addr.sin_family = AF_INET;
    srv_addr.sin_port   = htons(port);
    if (::inet_pton(AF_INET, host.c_str(), &srv_addr.sin_addr) <= 0)
        throw std::runtime_error("inet_pton()");

        
    ::connect(sock, reinterpret_cast<sockaddr*>(&srv_addr), sizeof(srv_addr));

    
    {
        SessionHeader sess{};
        sess.protocol   = static_cast<uint8_t>(Protocol::UDP);
        sess.mode       = static_cast<uint8_t>(mode);
        sess.block_size = htonl(static_cast<uint32_t>(block_size));
        sess.total_bytes = htobe64(total_bytes);

        std::vector<uint8_t> pkt;
        build_packet(pkt, 0, FLAG_SESS,
                     reinterpret_cast<uint8_t*>(&sess), sizeof(sess));

        set_recv_timeout(sock, ACK_TIMEOUT_MS);
        bool acked = false;
        for (int attempt = 0; attempt < MAX_RETRANSMIT && !acked; ++attempt) {
            ::send(sock, pkt.data(), pkt.size(), 0);
            uint8_t buf[64];
            ssize_t n = ::recv(sock, buf, sizeof(buf), 0);
            if (n >= (ssize_t)UDP_HDR_SIZE) {
                UDPHeader hdr;
                memcpy(&hdr, buf, UDP_HDR_SIZE);
                if (hdr.flags == FLAG_ACK) acked = true;
            }
        }
        if (!acked) throw std::runtime_error("Server did not ACK session header");
        clear_recv_timeout(sock);
    }

    
    uint64_t messages_sent = 0;
    uint64_t bytes_sent    = 0;
    uint32_t seq_no        = 1;
    size_t   offset        = 0;

    std::vector<uint8_t> pkt;

    auto t_start = Clock::now();

    while (offset < total_bytes) {
        size_t chunk = std::min(block_size, total_bytes - offset);
        build_packet(pkt, seq_no, FLAG_DATA, payload.data() + offset, chunk);

        if (mode == TransferMode::STOP_AND_WAIT) {
            set_recv_timeout(sock, ACK_TIMEOUT_MS);
            bool acked = false;
            for (int attempt = 0; attempt < MAX_RETRANSMIT && !acked; ++attempt) {
                ::send(sock, pkt.data(), pkt.size(), 0);
                uint8_t ack_buf[64];
                ssize_t n = ::recv(sock, ack_buf, sizeof(ack_buf), 0);
                if (n >= (ssize_t)UDP_HDR_SIZE) {
                    UDPHeader ahdr;
                    memcpy(&ahdr, ack_buf, UDP_HDR_SIZE);
                    if (ahdr.flags == FLAG_ACK && ntohl(ahdr.seq_no) == seq_no)
                        acked = true;
                }
            }
            if (!acked) {
                std::cerr << "[UDP Client] Warning: no ACK for seq=" << seq_no
                          << " after " << MAX_RETRANSMIT << " attempts\n";
            }
            clear_recv_timeout(sock);
        } else {
            
            ::send(sock, pkt.data(), pkt.size(), 0);
        }

        offset        += chunk;
        bytes_sent    += chunk;
        messages_sent += 1;
        seq_no        += 1;
    }

    
    {
        std::vector<uint8_t> fin_pkt;
        build_packet(fin_pkt, seq_no, FLAG_FIN, nullptr, 0);
        set_recv_timeout(sock, ACK_TIMEOUT_MS);
        for (int attempt = 0; attempt < MAX_RETRANSMIT; ++attempt) {
            ::send(sock, fin_pkt.data(), fin_pkt.size(), 0);
            uint8_t ack_buf[64];
            ssize_t n = ::recv(sock, ack_buf, sizeof(ack_buf), 0);
            if (n >= (ssize_t)UDP_HDR_SIZE) {
                UDPHeader ahdr;
                memcpy(&ahdr, ack_buf, UDP_HDR_SIZE);
                if (ahdr.flags == FLAG_ACK) break;
            }
        }
        clear_recv_timeout(sock);
    }

    auto t_end = Clock::now();
    double seconds = elapsed_seconds(t_start, t_end);

    ::close(sock);

    print_client_stats(Protocol::UDP, mode, block_size, total_bytes,
                       messages_sent, bytes_sent, seconds, hash_sent);
}

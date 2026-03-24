#pragma once

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <chrono>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <openssl/sha.h>

// ──────────────────────────────────────────────
//  Constants
// ──────────────────────────────────────────────
static constexpr uint16_t DEFAULT_PORT        = 9000;
static constexpr size_t   MAX_UDP_PAYLOAD     = 65535;
static constexpr size_t   QUIC_STREAM_BUFFER  = 65536;

// Transfer mode
enum class TransferMode : uint8_t {
    STREAMING    = 0,
    STOP_AND_WAIT = 1
};

// Protocol selector
enum class Protocol : uint8_t {
    TCP  = 0,
    UDP  = 1,
    QUIC = 2
};

inline std::string protocol_name(Protocol p) {
    switch (p) {
        case Protocol::TCP:  return "TCP";
        case Protocol::UDP:  return "UDP";
        case Protocol::QUIC: return "QUIC";
    }
    return "UNKNOWN";
}

inline std::string mode_name(TransferMode m) {
    return m == TransferMode::STREAMING ? "STREAMING" : "STOP_AND_WAIT";
}

// ──────────────────────────────────────────────
//  Control header sent by client before data
//  (used by all protocols)
// ──────────────────────────────────────────────
#pragma pack(push, 1)
struct SessionHeader {
    uint8_t  protocol;      // Protocol enum
    uint8_t  mode;          // TransferMode enum
    uint32_t block_size;    // bytes per message
    uint64_t total_bytes;   // total payload bytes to transfer
};
#pragma pack(pop)

// ──────────────────────────────────────────────
//  SHA-256 helpers
// ──────────────────────────────────────────────
inline std::string sha256_hex(const uint8_t* data, size_t len) {
    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256(data, len, hash);
    std::ostringstream oss;
    for (int i = 0; i < SHA256_DIGEST_LENGTH; ++i)
        oss << std::hex << std::setw(2) << std::setfill('0') << (int)hash[i];
    return oss.str();
}

// Incremental SHA-256 over a large buffer split into chunks
inline std::string sha256_hex_incremental(const std::vector<uint8_t>& buf) {
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    SHA256_Update(&ctx, buf.data(), buf.size());
    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256_Final(hash, &ctx);
    std::ostringstream oss;
    for (int i = 0; i < SHA256_DIGEST_LENGTH; ++i)
        oss << std::hex << std::setw(2) << std::setfill('0') << (int)hash[i];
    return oss.str();
}

// ──────────────────────────────────────────────
//  Timing helpers
// ──────────────────────────────────────────────
using Clock     = std::chrono::steady_clock;
using TimePoint = std::chrono::time_point<Clock>;

inline double elapsed_seconds(TimePoint start, TimePoint end) {
    return std::chrono::duration<double>(end - start).count();
}

// ──────────────────────────────────────────────
//  Generate deterministic payload buffer
// ──────────────────────────────────────────────
inline std::vector<uint8_t> make_payload(size_t total_bytes) {
    std::vector<uint8_t> buf(total_bytes);
    for (size_t i = 0; i < total_bytes; ++i)
        buf[i] = static_cast<uint8_t>(i & 0xFF);
    return buf;
}

// ──────────────────────────────────────────────
//  Print helpers
// ──────────────────────────────────────────────
inline void print_client_stats(Protocol proto, TransferMode mode,
                                size_t block_size, size_t total_bytes,
                                uint64_t messages_sent, uint64_t bytes_sent,
                                double seconds, const std::string& hash)
{
    double mb = bytes_sent / (1024.0 * 1024.0);
    double throughput = mb / seconds;
    std::cout << "\n========== CLIENT STATS ==========\n"
              << "Protocol       : " << protocol_name(proto) << "\n"
              << "Mode           : " << mode_name(mode) << "\n"
              << "Block size     : " << block_size << " bytes\n"
              << "Total planned  : " << total_bytes / (1024*1024) << " MB\n"
              << "Messages sent  : " << messages_sent << "\n"
              << "Bytes sent     : " << bytes_sent << "\n"
              << "Time           : " << std::fixed << std::setprecision(3) << seconds << " s\n"
              << "Throughput     : " << std::fixed << std::setprecision(2) << throughput << " MB/s\n"
              << "SHA-256 (sent) : " << hash << "\n"
              << "==================================\n";
}

inline void print_server_stats(Protocol proto, uint64_t messages_recv,
                                uint64_t bytes_recv, const std::string& hash)
{
    std::cout << "\n========== SERVER STATS ==========\n"
              << "Protocol        : " << protocol_name(proto) << "\n"
              << "Messages recv   : " << messages_recv << "\n"
              << "Bytes recv      : " << bytes_recv << "\n"
              << "SHA-256 (recv)  : " << hash << "\n"
              << "==================================\n";
}


#include "common.h"
#include "tcp_handler.h"
#include "udp_handler.h"
#include "quic_handler.h"

#include <cstdlib>
#include <cstring>
#include <cctype>
#include <algorithm>

static void usage(const char* prog) {
    std::cerr <<
        "Usage: " << prog << "\n"
        "  --protocol   tcp|udp|quic\n"
        "  --host       HOST\n"
        "  --block-size BYTES  (1-65535)\n"
        "  --total-bytes BYTES|100m|500m|1g|2g\n"
        "  --mode       streaming|stop-and-wait\n"
        " [--port       PORT]  (default 9000)\n";
    std::exit(1);
}

static size_t parse_size(const std::string& s) {
    std::string lower = s;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    if (lower == "100m")  return 100ULL * 1024 * 1024;
    if (lower == "500m")  return 500ULL * 1024 * 1024;
    if (lower == "1g")    return 1ULL   * 1024 * 1024 * 1024;
    if (lower == "2g")    return 2ULL   * 1024 * 1024 * 1024;
    return static_cast<size_t>(std::stoull(s));
}

int main(int argc, char* argv[]) {
    std::string  proto_str;
    std::string  host;
    size_t       block_size  = 0;
    size_t       total_bytes = 0;
    std::string  mode_str;
    uint16_t     port        = DEFAULT_PORT;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--protocol")   && i+1<argc) proto_str   = argv[++i];
        else if (!strcmp(argv[i], "--host")  && i+1<argc) host        = argv[++i];
        else if (!strcmp(argv[i], "--block-size") && i+1<argc) block_size  = std::stoull(argv[++i]);
        else if (!strcmp(argv[i], "--total-bytes") && i+1<argc) total_bytes = parse_size(argv[++i]);
        else if (!strcmp(argv[i], "--mode")  && i+1<argc) mode_str    = argv[++i];
        else if (!strcmp(argv[i], "--port")  && i+1<argc) port        = static_cast<uint16_t>(std::atoi(argv[++i]));
        else usage(argv[0]);
    }

    if (proto_str.empty() || host.empty() || block_size == 0 ||
        total_bytes == 0  || mode_str.empty()) usage(argv[0]);

    TransferMode mode;
    if (mode_str == "streaming")       mode = TransferMode::STREAMING;
    else if (mode_str == "stop-and-wait") mode = TransferMode::STOP_AND_WAIT;
    else { std::cerr << "Unknown mode: " << mode_str << "\n"; usage(argv[0]); }

    if (block_size > MAX_UDP_PAYLOAD) {
        std::cerr << "block-size must be <= " << MAX_UDP_PAYLOAD << "\n";
        return 1;
    }

    try {
        if (proto_str == "tcp")
            tcp_client_run(host, port, block_size, total_bytes, mode);
        else if (proto_str == "udp")
            udp_client_run(host, port, block_size, total_bytes, mode);
        else if (proto_str == "quic")
            quic_client_run(host, port, block_size, total_bytes, mode);
        else {
            std::cerr << "Unknown protocol: " << proto_str << "\n";
            usage(argv[0]);
        }
    } catch (std::exception& e) {
        std::cerr << "[Client] Fatal: " << e.what() << "\n";
        return 1;
    }
    return 0;
}

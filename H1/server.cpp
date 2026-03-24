

#include "common.h"
#include "tcp_handler.h"
#include "udp_handler.h"
#include "quic_handler.h"

#include <cstdlib>
#include <cstring>

static void usage(const char* prog) {
    std::cerr << "Usage: " << prog
              << " --protocol tcp|udp|quic [--port PORT]\n";
    std::exit(1);
}

int main(int argc, char* argv[]) {
    std::string proto_str;
    uint16_t    port = DEFAULT_PORT;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--protocol") && i + 1 < argc)
            proto_str = argv[++i];
        else if (!strcmp(argv[i], "--port") && i + 1 < argc)
            port = static_cast<uint16_t>(std::atoi(argv[++i]));
        else
            usage(argv[0]);
    }

    if (proto_str.empty()) usage(argv[0]);

    try {
        if (proto_str == "tcp")
            tcp_server_run(port);
        else if (proto_str == "udp")
            udp_server_run(port);
        else if (proto_str == "quic")
            quic_server_run(port);
        else {
            std::cerr << "Unknown protocol: " << proto_str << "\n";
            usage(argv[0]);
        }
    } catch (std::exception& e) {
        std::cerr << "[Server] Fatal: " << e.what() << "\n";
        return 1;
    }
    return 0;
}

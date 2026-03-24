#pragma once
#include "common.h"


void udp_server_run(uint16_t port);


void udp_client_run(const std::string& host,
                    uint16_t           port,
                    size_t             block_size,
                    size_t             total_bytes,
                    TransferMode       mode);

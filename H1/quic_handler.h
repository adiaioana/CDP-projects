#pragma once
#include "common.h"


void quic_server_run(uint16_t port);


void quic_client_run(const std::string& host,
                     uint16_t           port,
                     size_t             block_size,
                     size_t             total_bytes,
                     TransferMode       mode);

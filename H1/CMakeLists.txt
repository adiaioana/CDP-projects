cmake_minimum_required(VERSION 3.16)
project(pcd_hw1 CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)


add_compile_options(-O2 -Wall -Wextra -pthread)


find_package(OpenSSL REQUIRED)


find_package(PkgConfig QUIET)
if(PkgConfig_FOUND)
    pkg_check_modules(MSQUIC QUIET msquic)
endif()

if(NOT MSQUIC_FOUND)

    set(MSQUIC_INCLUDE_DIRS "/usr/include")
    set(MSQUIC_LIBRARIES    "msquic")
endif()


set(COMMON_SOURCES
    tcp_handler.cpp
    udp_handler.cpp
    quic_handler.cpp
)

add_executable(server
    server.cpp
    ${COMMON_SOURCES}
)
target_include_directories(server PRIVATE ${MSQUIC_INCLUDE_DIRS} ${OPENSSL_INCLUDE_DIR})
target_link_libraries(server PRIVATE
    ${MSQUIC_LIBRARIES}
    OpenSSL::SSL
    OpenSSL::Crypto
    pthread
)


add_executable(client
    client.cpp
    ${COMMON_SOURCES}
)
target_include_directories(client PRIVATE ${MSQUIC_INCLUDE_DIRS} ${OPENSSL_INCLUDE_DIR})
target_link_libraries(client PRIVATE
    ${MSQUIC_LIBRARIES}
    OpenSSL::SSL
    OpenSSL::Crypto
    pthread
)


add_custom_command(
    OUTPUT  ${CMAKE_BINARY_DIR}/server.crt ${CMAKE_BINARY_DIR}/server.key
    COMMAND openssl req -x509 -newkey rsa:2048
                -keyout ${CMAKE_BINARY_DIR}/server.key
                -out    ${CMAKE_BINARY_DIR}/server.crt
                -days 3650 -nodes
                -subj "/CN=localhost"
    COMMENT "Generating self-signed TLS certificate for QUIC"
)
add_custom_target(gen_cert ALL
    DEPENDS ${CMAKE_BINARY_DIR}/server.crt ${CMAKE_BINARY_DIR}/server.key
)
add_dependencies(server gen_cert)

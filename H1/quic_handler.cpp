

#include "quic_handler.h"
#include <msquic.h>

#include <condition_variable>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <thread>

static const QUIC_API_TABLE* MsQuic = nullptr;

static const QUIC_BUFFER Alpn = {
    sizeof("pcd1") - 1,
    reinterpret_cast<uint8_t*>(const_cast<char*>("pcd1"))
};


static constexpr uint8_t QFLAG_DATA = 0x00;
static constexpr uint8_t QFLAG_SESS = 0x01;
static constexpr uint8_t QFLAG_FIN  = 0x02;

#pragma pack(push,1)
struct QUICFrameHeader { uint32_t seq_no; uint8_t flags; };
#pragma pack(pop)
static constexpr size_t QHDR = sizeof(QUICFrameHeader);

struct ServerSession {
    std::vector<uint8_t>    raw;
    std::mutex              mtx;
    std::condition_variable cv;
    bool                    done = false;
};


struct ClientSession {
    std::mutex              mtx;
    std::condition_variable cv;
    bool connected  = false;
    bool done_flag  = false;
};


static QUIC_STATUS QUIC_API
ServerStreamCB(HQUIC Stream, void* Ctx, QUIC_STREAM_EVENT* Ev)
{
    auto* s = static_cast<ServerSession*>(Ctx);
    switch (Ev->Type) {
    case QUIC_STREAM_EVENT_RECEIVE: {
        std::lock_guard<std::mutex> lk(s->mtx);
        for (uint32_t i = 0; i < Ev->RECEIVE.BufferCount; ++i)
            s->raw.insert(s->raw.end(),
                          Ev->RECEIVE.Buffers[i].Buffer,
                          Ev->RECEIVE.Buffers[i].Buffer + Ev->RECEIVE.Buffers[i].Length);
        MsQuic->StreamReceiveComplete(Stream, Ev->RECEIVE.TotalBufferLength);
        break;
    }
    case QUIC_STREAM_EVENT_SEND_COMPLETE: {
        auto* qb = static_cast<QUIC_BUFFER*>(Ev->SEND_COMPLETE.ClientContext);
        delete[] qb->Buffer; delete qb;
        break;
    }
    case QUIC_STREAM_EVENT_PEER_SEND_SHUTDOWN:
    case QUIC_STREAM_EVENT_SHUTDOWN_COMPLETE:
        { std::lock_guard<std::mutex> lk(s->mtx); s->done = true; }
        s->cv.notify_all();
        MsQuic->StreamClose(Stream);
        break;
    default: break;
    }
    return QUIC_STATUS_SUCCESS;
}


static QUIC_STATUS QUIC_API
ServerConnCB(HQUIC Conn, void* /*Ctx*/, QUIC_CONNECTION_EVENT* Ev)
{
    switch (Ev->Type) {
    case QUIC_CONNECTION_EVENT_CONNECTED:
        MsQuic->ConnectionSendResumptionTicket(Conn,
            QUIC_SEND_RESUMPTION_FLAG_NONE, 0, nullptr);
        break;
    case QUIC_CONNECTION_EVENT_PEER_STREAM_STARTED: {
        auto* sess = new ServerSession();
        MsQuic->SetCallbackHandler(Ev->PEER_STREAM_STARTED.Stream,
            reinterpret_cast<void*>(ServerStreamCB), sess);

        std::thread([sess, Conn]() {
            { std::unique_lock<std::mutex> lk(sess->mtx);
              sess->cv.wait(lk, [sess]{ return sess->done; }); }

              
            const uint8_t* p    = sess->raw.data();
            size_t         left = sess->raw.size();
            SessionHeader  sh{};
            bool got_sh = false;
            uint64_t msgs = 0, bytes = 0;
            Protocol     proto = Protocol::QUIC;
            TransferMode tmode = TransferMode::STREAMING;
            std::vector<uint8_t> data;

            while (left >= QHDR) {
                QUICFrameHeader fh;
                memcpy(&fh, p, QHDR); p += QHDR; left -= QHDR;
                uint8_t flag = fh.flags;
                if (flag == QFLAG_SESS) {
                    if (left < sizeof(sh)) break;
                    memcpy(&sh, p, sizeof(sh)); p += sizeof(sh); left -= sizeof(sh);
                    proto = static_cast<Protocol>(sh.protocol);
                    tmode = static_cast<TransferMode>(sh.mode);
                    got_sh = true;
                } else if (flag == QFLAG_DATA) {
                    size_t chunk = got_sh
                        ? std::min((size_t)ntohl(sh.block_size), left)
                        : std::min((size_t)1, left);
                    data.insert(data.end(), p, p + chunk);
                    p += chunk; left -= chunk;
                    bytes += chunk; msgs++;
                } else { break; }
            }
            print_server_stats(proto, msgs, bytes, sha256_hex_incremental(data));
            delete sess;
            MsQuic->ConnectionClose(Conn);
        }).detach();
        break;
    }
    default: break;
    }
    return QUIC_STATUS_SUCCESS;
}


static QUIC_STATUS QUIC_API
ListenerCB(HQUIC /*L*/, void* Ctx, QUIC_LISTENER_EVENT* Ev)
{
    if (Ev->Type == QUIC_LISTENER_EVENT_NEW_CONNECTION) {
        MsQuic->SetCallbackHandler(Ev->NEW_CONNECTION.Connection,
            reinterpret_cast<void*>(ServerConnCB), nullptr);
        MsQuic->ConnectionSetConfiguration(Ev->NEW_CONNECTION.Connection,
            static_cast<HQUIC>(Ctx));
    }
    return QUIC_STATUS_SUCCESS;
}


void quic_server_run(uint16_t port)
{
    if (QUIC_FAILED(MsQuicOpen2(&MsQuic)))
        throw std::runtime_error("MsQuicOpen2 failed");

    HQUIC reg = nullptr;
    QUIC_REGISTRATION_CONFIG rc{ "pcd1_srv", QUIC_EXECUTION_PROFILE_LOW_LATENCY };
    if (QUIC_FAILED(MsQuic->RegistrationOpen(&rc, &reg)))
        throw std::runtime_error("RegistrationOpen");

    HQUIC cfg = nullptr;
    {
        QUIC_SETTINGS s{};
        s.IdleTimeoutMs = 30000; s.IsSet.IdleTimeoutMs = TRUE;
        s.ServerResumptionLevel = QUIC_SERVER_RESUME_AND_ZERORTT;
        s.IsSet.ServerResumptionLevel = TRUE;
        s.PeerUnidiStreamCount = 1; s.IsSet.PeerUnidiStreamCount = TRUE;
        if (QUIC_FAILED(MsQuic->ConfigurationOpen(reg, &Alpn, 1, &s, sizeof(s), nullptr, &cfg)))
            throw std::runtime_error("ConfigurationOpen");

        QUIC_CERTIFICATE_FILE cf{ "server.key", "server.crt" };
        QUIC_CREDENTIAL_CONFIG cc{};
        cc.Type = QUIC_CREDENTIAL_TYPE_CERTIFICATE_FILE;
        cc.CertificateFile = &cf;
        if (QUIC_FAILED(MsQuic->ConfigurationLoadCredential(cfg, &cc)))
            throw std::runtime_error("ConfigurationLoadCredential");
    }

    HQUIC listener = nullptr;
    if (QUIC_FAILED(MsQuic->ListenerOpen(reg, ListenerCB, cfg, &listener)))
        throw std::runtime_error("ListenerOpen");

    QUIC_ADDR addr{};
    QuicAddrSetFamily(&addr, QUIC_ADDRESS_FAMILY_INET);
    QuicAddrSetPort(&addr, port);
    if (QUIC_FAILED(MsQuic->ListenerStart(listener, &Alpn, 1, &addr)))
        throw std::runtime_error("ListenerStart");

    std::cout << "[QUIC Server] Listening on UDP port " << port << " ...\n";
    while (true) std::this_thread::sleep_for(std::chrono::seconds(60));

    MsQuic->ListenerClose(listener);
    MsQuic->ConfigurationClose(cfg);
    MsQuic->RegistrationClose(reg);
    MsQuicClose(MsQuic);
}

static QUIC_STATUS QUIC_API
ClientStreamCB(HQUIC /*S*/, void* /*Ctx*/, QUIC_STREAM_EVENT* Ev)
{
    if (Ev->Type == QUIC_STREAM_EVENT_SEND_COMPLETE) {
        auto* qb = static_cast<QUIC_BUFFER*>(Ev->SEND_COMPLETE.ClientContext);
        delete[] qb->Buffer; delete qb;
    }
    return QUIC_STATUS_SUCCESS;
}


static QUIC_STATUS QUIC_API
ClientConnCB(HQUIC /*C*/, void* Ctx, QUIC_CONNECTION_EVENT* Ev)
{
    auto* cs = static_cast<ClientSession*>(Ctx);
    if (Ev->Type == QUIC_CONNECTION_EVENT_CONNECTED) {
        std::lock_guard<std::mutex> lk(cs->mtx);
        cs->connected = true; cs->cv.notify_all();
    } else if (Ev->Type == QUIC_CONNECTION_EVENT_SHUTDOWN_COMPLETE) {
        std::lock_guard<std::mutex> lk(cs->mtx);
        cs->done_flag = true; cs->cv.notify_all();
    }
    return QUIC_STATUS_SUCCESS;
}


void quic_client_run(const std::string& host, uint16_t port,
                     size_t block_size, size_t total_bytes,
                     TransferMode mode)
{
    auto payload   = make_payload(total_bytes);
    auto hash_sent = sha256_hex_incremental(payload);

    if (QUIC_FAILED(MsQuicOpen2(&MsQuic)))
        throw std::runtime_error("MsQuicOpen2 failed");

    HQUIC reg = nullptr;
    QUIC_REGISTRATION_CONFIG rc{ "pcd1_cli", QUIC_EXECUTION_PROFILE_LOW_LATENCY };
    if (QUIC_FAILED(MsQuic->RegistrationOpen(&rc, &reg)))
        throw std::runtime_error("RegistrationOpen");

    HQUIC cfg = nullptr;
    {
        QUIC_SETTINGS s{};
        s.IdleTimeoutMs = 30000; s.IsSet.IdleTimeoutMs = TRUE;
        if (QUIC_FAILED(MsQuic->ConfigurationOpen(reg, &Alpn, 1, &s, sizeof(s), nullptr, &cfg)))
            throw std::runtime_error("ConfigurationOpen");
        QUIC_CREDENTIAL_CONFIG cc{};
        cc.Type  = QUIC_CREDENTIAL_TYPE_NONE;
        cc.Flags = QUIC_CREDENTIAL_FLAG_CLIENT |
                   QUIC_CREDENTIAL_FLAG_NO_CERTIFICATE_VALIDATION;
        if (QUIC_FAILED(MsQuic->ConfigurationLoadCredential(cfg, &cc)))
            throw std::runtime_error("ConfigurationLoadCredential");
    }

    ClientSession cs;
    HQUIC conn = nullptr;
    if (QUIC_FAILED(MsQuic->ConnectionOpen(reg, ClientConnCB, &cs, &conn)))
        throw std::runtime_error("ConnectionOpen");
    if (QUIC_FAILED(MsQuic->ConnectionStart(conn, cfg,
            QUIC_ADDRESS_FAMILY_INET, host.c_str(), port)))
        throw std::runtime_error("ConnectionStart");

    { std::unique_lock<std::mutex> lk(cs.mtx);
      cs.cv.wait_for(lk, std::chrono::seconds(10), [&]{ return cs.connected; });
      if (!cs.connected) throw std::runtime_error("QUIC handshake timeout"); }

    HQUIC stream = nullptr;
    if (QUIC_FAILED(MsQuic->StreamOpen(conn,
            QUIC_STREAM_OPEN_FLAG_UNIDIRECTIONAL, ClientStreamCB, nullptr, &stream)))
        throw std::runtime_error("StreamOpen");
    if (QUIC_FAILED(MsQuic->StreamStart(stream, QUIC_STREAM_START_FLAG_NONE)))
        throw std::runtime_error("StreamStart");

        
    auto send_frame = [&](uint32_t seq, uint8_t flag,
                           const uint8_t* data, size_t len,
                           QUIC_SEND_FLAGS sf = QUIC_SEND_FLAG_NONE) {
        size_t total = QHDR + len;
        auto* buf = new uint8_t[total];
        QUICFrameHeader fh{ htonl(seq), flag };
        memcpy(buf, &fh, QHDR);
        if (len) memcpy(buf + QHDR, data, len);
        auto* qb = new QUIC_BUFFER{ static_cast<uint32_t>(total), buf };
        if (QUIC_FAILED(MsQuic->StreamSend(stream, qb, 1, sf, qb)))
            { delete[] buf; delete qb; throw std::runtime_error("StreamSend"); }
    };

    
    {
        SessionHeader sh{};
        sh.protocol    = static_cast<uint8_t>(Protocol::QUIC);
        sh.mode        = static_cast<uint8_t>(mode);
        sh.block_size  = htonl(static_cast<uint32_t>(block_size));
        sh.total_bytes = htobe64(total_bytes);
        send_frame(0, QFLAG_SESS, reinterpret_cast<uint8_t*>(&sh), sizeof(sh));
    }

    uint64_t msgs = 0, sent = 0;
    uint32_t seq  = 1;
    size_t   off  = 0;

    auto t0 = Clock::now();

    while (off < total_bytes) {
        size_t chunk = std::min(block_size, total_bytes - off);
        send_frame(seq, QFLAG_DATA, payload.data() + off, chunk);
        off += chunk; sent += chunk; msgs++; seq++;
        if (mode == TransferMode::STOP_AND_WAIT)
            std::this_thread::sleep_for(std::chrono::microseconds(200));
    }

    send_frame(seq, QFLAG_FIN, nullptr, 0, QUIC_SEND_FLAG_FIN);
    std::this_thread::sleep_for(std::chrono::milliseconds(300));

    auto t1 = Clock::now();
    double seconds = elapsed_seconds(t0, t1);

    MsQuic->StreamShutdown(stream, QUIC_STREAM_SHUTDOWN_FLAG_GRACEFUL, 0);
    MsQuic->ConnectionShutdown(conn, QUIC_CONNECTION_SHUTDOWN_FLAG_NONE, 0);
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    MsQuic->StreamClose(stream);
    MsQuic->ConnectionClose(conn);
    MsQuic->ConfigurationClose(cfg);
    MsQuic->RegistrationClose(reg);
    MsQuicClose(MsQuic);

    print_client_stats(Protocol::QUIC, mode, block_size, total_bytes,
                       msgs, sent, seconds, hash_sent);
}

# Build Auxiliary Image
FROM ubuntu:22.04 AS builder
ARG TON_RELEASE=v2025.03

RUN apt-get update && \
    apt-get install -y wget git openssl curl unzip build-essential git cmake ninja-build \
        zlib1g-dev libsecp256k1-dev libmicrohttpd-dev libsodium-dev ccache libjemalloc-dev \
        liblz4-dev autoconf libssl-dev lsb-release software-properties-common gnupg libtool && \
    wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && \
    ./llvm.sh 16 all && \
    rm ./llvm.sh && \
    apt-get clean
   
RUN git clone https://github.com/ton-blockchain/ton.git --branch ${TON_RELEASE} --recurse-submodules /ton && \
    cd /ton && \
    mkdir build && \
    cd build && \
    cmake -GNinja -DCMAKE_BUILD_TYPE=Release .. && \
    ninja storage-daemon storage-daemon-cli rldp-http-proxy
#    cp assembly/native/build-ubuntu-shared.sh . && \
#    chmod +x build-ubuntu-shared.sh && \
#    ./build-ubuntu-shared.sh  

# Ton-Storage
FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y wget openssl curl unzip libatomic1 libjemalloc2 libsodium23 && \
    apt-get clean && \
    mkdir -p /opt/ton-storage && \
    cd /opt/ton-storage && \
    wget https://ton-blockchain.github.io/global.config.json && \
    wget https://ton-blockchain.github.io/testnet-global.config.json

COPY --from=builder /ton/build/storage/storage-daemon/storage-daemon-cli /opt/ton-storage
COPY --from=builder /ton/build/storage/storage-daemon/storage-daemon /opt/ton-storage
COPY --from=builder /ton/build/rldp-http-proxy/rldp-http-proxy /opt/ton-storage

WORKDIR /opt/ton-storage

VOLUME storage-db

EXPOSE 3333/udp 5555

CMD [ "./storage-daemon",  "-v3", "-C", "global.config.json", "-I", "127.0.0.1:3333", "-p", "5555", "-D", "/storage-db" ]
   
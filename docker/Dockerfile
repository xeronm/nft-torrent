FROM ubuntu:22.04

ARG USER_ID=9001 \
    GROUP_ID=9001 \
    NFTORRENT_VERSION \
    PIP_INDEX_URL

RUN groupadd -r nftorrent --gid=${GROUP_ID} && \
    useradd -r -g nftorrent --uid=${USER_ID} --home-dir=/opt/nftorrent --shell=/bin/bash nftorrent && \
    apt-get update && \
    apt-get install -y wget curl unzip python3 python3-pip && \
    apt-get clean && \
    python3 -m pip install pip -U --no-cache-dir

WORKDIR /opt/nftorrent

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN --mount=from=dist,target=/mnt/dist \
    python3 -m pip install ton_nft_torrent==${NFTORRENT_VERSION} gunicorn --no-cache-dir \
        --find-links /mnt/dist && \
    python3 -m pip install pytonlib==0.0.65 --no-cache-dir

ENV LOGURU_LEVEL=INFO \
    TON_STORAGE_NUM_WORKERS=0 \
    TON_API_TONLIB_LITESERVER_CONFIG=https://ton.org/global-config.json \
    TON_API_TONLIB_KEYSTORE=/storage-db/.ton_keystore/

USER nftorrent

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

CMD [ "gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "1", "--bind", "0.0.0.0:8002", "--access-logfile", "-", "NFTorrent.main:app" ]


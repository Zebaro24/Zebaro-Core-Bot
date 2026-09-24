FROM python:3.13-slim AS build

WORKDIR /app

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock* /app/

RUN poetry config virtualenvs.create false && \
    poetry install --without dev --no-interaction --no-ansi --no-root

COPY . /app

# What the bot builds the Windows VPN installer from (src/services/vpn/installer.py):
# WireGuard's MSIs and the 7-Zip SFX installer module, pinned by SHA256. WG_VERSION must
# match WG_VERSION in installer.py — tests/test_vpn_installer_version.py checks it.
FROM debian:trixie-slim AS vpn-installer

ARG WG_VERSION=1.1.1
ARG LZMA_SDK=lzma2301

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl 7zip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/vpn-installer

RUN for arch in amd64 arm64 x86; do \
        curl -fsSLO "https://download.wireguard.com/windows-client/wireguard-${arch}-${WG_VERSION}.msi"; \
    done \
    && curl -fsSLO "https://www.7-zip.org/a/${LZMA_SDK}.7z" \
    && printf '%s\n' \
        "7bfed60ad61b785c914b38b61555a975488e1d3ec472dbfb2fcdf498fca75242  wireguard-amd64-${WG_VERSION}.msi" \
        "8336335c738d4aff040fa9d11b752da65a80b6f41d3262d6ba5e82f97ebd1bd4  wireguard-arm64-${WG_VERSION}.msi" \
        "e3ec714fbfce3ba3a416671252e16cd71517a837a7ebd18b8c24b29a441e8724  wireguard-x86-${WG_VERSION}.msi" \
        "317dd834d6bbfd95433488b832e823cd3d4d420101436422c03af88507dd1370  ${LZMA_SDK}.7z" \
        | sha256sum -c - \
    && 7z e -y "${LZMA_SDK}.7z" bin/7zSD.sfx >/dev/null \
    && rm "${LZMA_SDK}.7z"

FROM python:3.13-slim

# 7z packs the per-person installer at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends 7zip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /app /app
COPY --from=vpn-installer /opt/vpn-installer /opt/vpn-installer

EXPOSE 8000
CMD ["python", "-m", "src.main"]

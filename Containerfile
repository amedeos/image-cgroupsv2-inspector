# image-cgroupsv2-inspector
# UBI 9 with Python 3.12; entrypoint is the main script.
FROM registry.access.redhat.com/ubi9/python-312

USER root
# Patch base-image packages (security), then install system dependencies:
# podman (image pull/inspect), acl (extended ACLs for rootfs), golang
# (deterministic Go binary scanning via `go version`). Skip docs/man pages and
# clear the dnf cache in the same layer to keep the image small.
# NOTE: weak deps are intentionally kept — rootless podman relies on helpers
# (crun, netavark, aardvark-dns, fuse-overlayfs, slirp4netns/pasta) that ship
# as weak deps on UBI 9; dropping them would break in-container `podman pull`.
RUN dnf -y update --setopt=tsflags=nodocs && \
    dnf -y install --setopt=tsflags=nodocs podman acl golang && \
    dnf clean all && \
    rm -rf /var/cache/dnf /var/cache/yum

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application (script + src/)
COPY image-cgroupsv2-inspector .
COPY src/ src/

RUN chmod +x /app/image-cgroupsv2-inspector

ENTRYPOINT ["/app/image-cgroupsv2-inspector"]

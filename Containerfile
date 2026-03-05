# image-cgroupsv2-inspector
# UBI 9 with Python 3.12; entrypoint is the main script.
FROM registry.access.redhat.com/ubi9/python-312

USER root
# Install system dependencies: podman (image pull/inspect), acl (extended ACLs for rootfs)
RUN dnf install -y podman acl && dnf clean all

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application (script + src/)
COPY image-cgroupsv2-inspector .
COPY src/ src/

RUN chmod +x /app/image-cgroupsv2-inspector

ENTRYPOINT ["/app/image-cgroupsv2-inspector"]

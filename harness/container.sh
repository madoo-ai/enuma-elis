#!/usr/bin/env bash
# Runs inside the manus-dei/base image as the `ubuntu` user.
set -euo pipefail

sudo -n apt-get update -qq
sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends bubblewrap >/dev/null

# Build the runtime tree the adapter expects. For the harness a symlink to the
# distro Python is enough; the production volume is a relocatable build.
sudo -n mkdir -p /opt/manus/python/current/bin /opt/manus/python/current/lib
sudo -n ln -sf /usr/bin/python3 /opt/manus/python/current/bin/python3
sudo -n rm -rf /opt/manus/python/current/lib/agent
sudo -n cp -r /opt/enuma/agent /opt/manus/python/current/lib/agent
sudo -n cp /opt/enuma/runtime/sitecustomize.py /opt/manus/python/current/lib/sitecustomize.py
sudo -n chmod -R a+rX /opt/manus/python

sudo -n mkdir -p /home/ubuntu/workspace
sudo -n chown -R ubuntu:ubuntu /home/ubuntu/workspace

exec sudo -n -u ubuntu -H /usr/bin/python3 /opt/enuma/harness/host.py

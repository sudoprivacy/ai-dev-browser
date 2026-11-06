#!/usr/bin/env bash
set -euo pipefail

# These native browser jobs run on Ubuntu's amd64 GitHub-hosted image.
source /etc/os-release
if [[ "$ID" != ubuntu || "$(dpkg --print-architecture)" != amd64 ]]; then
  echo 'The browser CI dependency installer requires Ubuntu amd64.' >&2
  exit 1
fi

# Keep signed Ubuntu packages on HTTPS, independently of the runner mirror list.
sources=$(mktemp --suffix=.sources)
trap 'rm -f -- "$sources"' EXIT
cat > "$sources" <<EOF
Types: deb
URIs: https://archive.ubuntu.com/ubuntu/
Suites: $VERSION_CODENAME $VERSION_CODENAME-updates $VERSION_CODENAME-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: https://security.ubuntu.com/ubuntu/
Suites: $VERSION_CODENAME-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
options=(
  -o "Dir::Etc::sourcelist=$sources"
  -o 'Dir::Etc::sourceparts=-'
  -o Acquire::Retries=3
  -o Acquire::http::Timeout=20
  -o Acquire::https::Timeout=20
)
sudo apt-get "${options[@]}" update
sudo env DEBIAN_FRONTEND=noninteractive apt-get "${options[@]}" install -y --no-install-recommends "$@"

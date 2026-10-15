#!/bin/sh
# Run as the deployment user. No host-level package/configuration changes.
set -eu
WEIMING_HOME="$HOME/services/weiming"
WEIMING_ROOT="$WEIMING_HOME/project"
WEIMING_IMAGE=$(docker image inspect weiming-sandbox:20261011 --format '{{.Id}}')
case "$WEIMING_IMAGE" in sha256:*) ;; *) exit 1 ;; esac
umask 077
cat > "$WEIMING_HOME/runtime.env" <<EOF
WEIMING_SANDBOX_IMAGE=$WEIMING_IMAGE
WEIMING_CHROME_PATH=$WEIMING_HOME/bin/chrome/opt/google/chrome/chrome
WEIMING_RUNTIME_LOCATION=server
WEIMING_CHAT_TIMEOUT_SECONDS=1800
WEIMING_ANALYSIS_TIMEOUT_SECONDS=2400
WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS=1800
LD_LIBRARY_PATH=$WEIMING_HOME/bin/chrome-libs/usr/lib/x86_64-linux-gnu
EOF
python3 "$WEIMING_ROOT/deploy/server/patch-upstream.py"
mkdir -p "$HOME/.config/systemd/user"
cp "$WEIMING_ROOT/deploy/server/weiming-api.service" "$HOME/.config/systemd/user/"
cp "$WEIMING_ROOT/deploy/server/weiming-ollama.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
echo 'Server units prepared; API is not started by this script.'

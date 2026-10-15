#!/bin/sh
# Rebuild the pinned OpenAPI CLI with this server's user-space toolchain.
set -eu
WEIMING_HOME="$HOME/services/weiming"
WEIMING_RUNTIME="$WEIMING_HOME/project/.runtime/platform-mcp"
export CARGO_HOME="$WEIMING_RUNTIME/rust/cargo"
export RUSTUP_HOME="$WEIMING_RUNTIME/rust/toolchains"
export CC="$WEIMING_HOME/bin/cc-user"
export AR="$WEIMING_HOME/bin/build-sysroot/usr/bin/x86_64-linux-gnu-ar"
export LD_LIBRARY_PATH="$WEIMING_HOME/bin/build-sysroot/usr/lib/x86_64-linux-gnu"
export CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER="$CC"
export CARGO_BUILD_JOBS=4
"$CARGO_HOME/bin/cargo" build --release --locked --manifest-path "$WEIMING_RUNTIME/sources/douyin-openapi/Cargo.toml"
mkdir -p "$WEIMING_RUNTIME/bin"
cp "$WEIMING_RUNTIME/sources/douyin-openapi/target/release/douyin" "$WEIMING_RUNTIME/bin/douyin"
"$WEIMING_RUNTIME/bin/douyin" --version

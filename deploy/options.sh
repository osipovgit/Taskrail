#!/usr/bin/env bash
# Sourced by install.sh; preserve service enablement on unattended updates.
fresh=no
autostart=keep
autostart_explicit=no
agent_mode=keep
boot=no
wait_seconds=0
initial_settings=
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fresh) fresh=yes ;;
        --autostart=yes|--autostart=no|--autostart=keep)
            autostart=${1#*=}
            autostart_explicit=yes ;;
        --agents=keep|--agents=bundled)
            agent_mode=${1#*=} ;;
        --boot=yes|--boot=no)
            boot=${1#*=} ;;
        --wait=*)
            wait_seconds=${1#*=}
            [[ "$wait_seconds" =~ ^[0-9]+$ ]] || { echo 'Invalid --wait seconds' >&2; exit 2; } ;;
        --help)
            echo 'Usage: bash deploy/install.sh [settings.json] [--fresh] [--autostart=yes|no|keep] [--agents=keep|bundled] [--boot=yes|no] [--wait=SECONDS]'
            exit 0 ;;
        --*) echo "Unknown option: $1" >&2; exit 2 ;;
        *)
            [[ -z "$initial_settings" ]] || { echo 'Only one settings file is accepted' >&2; exit 2; }
            initial_settings=$1 ;;
    esac
    shift
done
if [[ "$autostart_explicit" == no && "$boot" == no && -t 0 ]]; then
    read -r -p 'Start Countersign automatically at login? [y/n/Enter=keep current setting] ' answer
    case "$answer" in
        y|Y|yes) autostart=yes ;;
        n|N|no) autostart=no ;;
        '') ;;
        *) echo 'Expected y, n or Enter' >&2; exit 2 ;;
    esac
fi
if [[ "$boot" == yes && "$autostart" == no ]]; then
    echo '--boot=yes requires autostart; use --autostart=yes' >&2
    exit 2
fi
if [[ "$boot" == yes ]]; then
    autostart=yes
fi

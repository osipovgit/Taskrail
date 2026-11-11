#!/usr/bin/env bash
# Sourced by install.sh; preserve service enablement on unattended updates.
reset_mode=
apply_settings=no
opencode_path=
autostart=keep
autostart_explicit=no
agent_mode=keep
boot=no
wait_seconds=0
initial_settings=
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fresh | --force-update)
            if [[ -n "$reset_mode" && "$reset_mode" != "${1#--}" ]]; then
                echo 'Choose either --fresh or --force-update' >&2
                exit 2
            fi
            reset_mode=${1#--}
            ;;
        --apply-settings) apply_settings=yes ;;
        --opencode=?*) opencode_path=${1#*=} ;;
        --autostart=yes | --autostart=no | --autostart=keep)
            autostart=${1#*=}
            autostart_explicit=yes
            ;;
        --agents=keep | --agents=bundled)
            agent_mode=${1#*=}
            ;;
        --boot=yes | --boot=no)
            boot=${1#*=}
            ;;
        --wait=*)
            wait_seconds=${1#*=}
            [[ "$wait_seconds" =~ ^[0-9]+$ ]] || {
                echo 'Invalid --wait seconds' >&2
                exit 2
            }
            ;;
        --help)
            echo 'Usage: bash deploy/install.sh [settings.json] [--apply-settings] [--opencode=PATH] [--force-update|--fresh] [--autostart=yes|no|keep] [--agents=keep|bundled] [--boot=yes|no] [--wait=SECONDS]'
            echo '  --force-update  Reinstall the user service from the supplied settings or release defaults. Erase installed configuration and run history.'
            echo '  --fresh         Wait for active work, reinstall the user service and reset any installed SSH executor.'
            exit 0
            ;;
        --*)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
        *)
            [[ -z "$initial_settings" ]] || {
                echo 'Only one settings file is accepted' >&2
                exit 2
            }
            initial_settings=$1
            ;;
    esac
    shift
done
if [[ "$apply_settings" == yes && -z "$initial_settings" ]]; then
    echo '--apply-settings requires a settings file' >&2
    exit 2
fi
if [[ "$autostart_explicit" == no && "$boot" == no && -t 0 ]]; then
    read -r -p 'Start Taskrail automatically at login? [y/n/Enter=keep current setting] ' answer
    case "$answer" in
        y | Y | yes) autostart=yes ;;
        n | N | no) autostart=no ;;
        '') ;;
        *)
            echo 'Expected y, n or Enter' >&2
            exit 2
            ;;
    esac
fi
if [[ "$boot" == yes && "$autostart" == no ]]; then
    echo '--boot=yes requires autostart; use --autostart=yes' >&2
    exit 2
fi
if [[ "$boot" == yes ]]; then
    autostart=yes
fi

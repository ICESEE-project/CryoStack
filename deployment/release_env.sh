# shellcheck shell=bash
# =============================================================================
# CryoStack connector release -- identity helpers (sourced, not executed).
#
# The canonical artifact store belongs to the *release owner*. That owner is
# never root, even when a single step runs under sudo -- so the store path must
# be resolved from the owner's home, not from the privileged process's $HOME
# (which sudo sets to /root).
#
#   cryostack_release_owner  -> the unprivileged release owner's username
#   cryostack_release_home   -> that owner's home directory
# =============================================================================

cryostack_release_owner() {
    if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
        printf '%s\n' "${SUDO_USER}"
    else
        id -un
    fi
}

cryostack_release_home() {
    _cro_owner="$(cryostack_release_owner)"
    # Not under sudo and the owner is the caller: honour a custom $HOME.
    if [ -z "${SUDO_USER:-}" ] && [ "${_cro_owner}" = "$(id -un)" ]; then
        printf '%s\n' "${HOME}"
        return 0
    fi
    # Under sudo (or resolving another user): read the real home from passwd,
    # never the sudo-provided /root.
    _cro_home="$(getent passwd "${_cro_owner}" 2>/dev/null | cut -d: -f6)"
    if [ -n "${_cro_home}" ]; then
        printf '%s\n' "${_cro_home}"
    else
        printf '%s\n' "${HOME}"
    fi
}

from __future__ import annotations

import os
import ipywidgets as W
from icesee_jupyter_book.core.ssh_key_manager import (
    make_ssh_key_info,
    ensure_cluster_ssh_key,
    read_public_key,
    ssh_agent_running,
    add_key_to_agent,
    ensure_ssh_config_entry,
    test_ssh_login,
    cluster_setup_summary,
)

def build_ssh_key_manager(cluster_name_widget, host_widget, user_widget):
    output = W.Output(layout=W.Layout(
        border="1px solid rgba(0,0,0,.10)",
        padding="10px",
        height="220px",
        overflow="auto",
        width="100%",
    ))

    alias_in = W.Text(value="", placeholder="optional alias, e.g. ub-ccr", layout=W.Layout(width="320px"))
    gen_btn = W.Button(description="Generate SSH Key", icon="key", button_style="info")
    show_btn = W.Button(description="Show Public Key", icon="file-text")
    agent_btn = W.Button(description="Add Key to Agent", icon="plus")
    config_btn = W.Button(description="Write SSH Config", icon="edit")
    test_btn = W.Button(description="Test SSH", icon="terminal", button_style="success")
    refresh_btn = W.Button(description="Refresh", icon="refresh")

    def current_info():
        cluster_id = cluster_name_widget.value.strip() or host_widget.value.strip() or "cluster"
        alias = alias_in.value.strip() or None
        return make_ssh_key_info(
            cluster_id=cluster_id,
            host=host_widget.value.strip(),
            user=user_widget.value.strip(),
            alias=alias,
        )

    def print_summary():
        output.clear_output()
        info = current_info()
        summary = cluster_setup_summary(
            cluster_id=info.cluster_id,
            host=info.host,
            user=info.user,
            alias=info.alias,
        )
        with output:
            print("[ssh] Cluster :", summary["cluster_id"])
            print("[ssh] Alias   :", summary["alias"])
            print("[ssh] Host    :", summary["host"])
            print("[ssh] User    :", summary["user"])
            print("[ssh] Private :", summary["private_key"])
            print("[ssh] Public  :", summary["public_key"])
            print("[ssh] Agent running     :", summary["agent_running"])
            print("[ssh] Any key in agent  :", summary["agent_has_any_keys"])
            print("[ssh] Cluster key loaded:", summary["cluster_key_loaded"])
            print("[ssh] Private key exists:", summary["private_key_exists"])
            print("[ssh] Public key exists :", summary["public_key_exists"])

    def on_generate(_=None):
        info = current_info()
        output.clear_output()
        with output:
            try:
                priv, pub, created = ensure_cluster_ssh_key(
                    cluster_id=info.cluster_id,
                    comment=f"{info.user}@{info.host}",
                    passphrase="",
                )
                if created:
                    print("[ssh] Generated new key pair:")
                else:
                    print("[ssh] Key pair already exists:")
                print("  private:", priv)
                print("  public :", pub)
                print()
                print("[ssh] Next step:")
                print("Upload the public key to your cluster's SSH key portal if required.")
            except Exception as e:
                print("[ssh][ERROR]", type(e).__name__, e)

    def on_show(_=None):
        info = current_info()
        output.clear_output()
        with output:
            try:
                txt = read_public_key(info.public_key)
                print("[ssh] Public key:")
                print(txt)
                print()
                print("[ssh] Copy this into your cluster SSH key portal if needed.")
            except Exception as e:
                print("[ssh][ERROR]", type(e).__name__, e)

    def on_agent(_=None):
        info = current_info()
        output.clear_output()
        with output:
            try:
                if not ssh_agent_running():
                    print("[ssh] ssh-agent is not running in this environment.")
                    print("Start it in your terminal, then retry:")
                    print('eval "$(ssh-agent -s)"')
                    return

                r = add_key_to_agent(info.private_key)
                if r.returncode == 0:
                    print("[ssh] Key added to agent.")
                else:
                    print("[ssh][ERROR] Failed to add key to agent.")
                    if (r.stderr or "").strip():
                        print(r.stderr.strip())
            except Exception as e:
                print("[ssh][ERROR]", type(e).__name__, e)

    def on_config(_=None):
        info = current_info()
        output.clear_output()
        with output:
            try:
                path, created = ensure_ssh_config_entry(
                    alias=info.alias,
                    host=info.host,
                    user=info.user,
                    private_key=info.private_key,
                )
                print("[ssh] SSH config:", path)
                print("[ssh] Entry created." if created else "[ssh] Entry already exists.")
            except Exception as e:
                print("[ssh][ERROR]", type(e).__name__, e)

    def on_test(_=None):
        info = current_info()
        output.clear_output()
        with output:
            try:
                r = test_ssh_login(alias=info.alias, host=info.host, user=info.user, timeout=600)
                print("[ssh] returncode:", r.returncode)
                if (r.stdout or "").strip():
                    print("--- stdout ---")
                    print(r.stdout.strip())
                if (r.stderr or "").strip():
                    print("--- stderr ---")
                    print(r.stderr.strip())
            except Exception as e:
                print("[ssh][ERROR]", type(e).__name__, e)

    gen_btn.on_click(on_generate)
    show_btn.on_click(on_show)
    agent_btn.on_click(on_agent)
    config_btn.on_click(on_config)
    test_btn.on_click(on_test)
    refresh_btn.on_click(lambda _: print_summary())

    controls = W.VBox([
        W.HBox([W.HTML("<div class='icesee-lbl'>Alias:</div>"), alias_in], layout=W.Layout(gap="10px")),
        W.HBox([gen_btn, show_btn, agent_btn, config_btn, refresh_btn], layout=W.Layout(gap="10px", flex_wrap="wrap")),
        output,
    ], layout=W.Layout(gap="10px"))

    print_summary()
    return controls
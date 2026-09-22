# Testing

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-docs-page">
  <section class="cryostack-docs-hero">
    <div class="cryostack-section-label">CryoStack Developer Guide</div>
    <h1>Testing</h1>
    <p>
      The Python suite, Node tests, the documentation build, and which
      tests to add for each type of change.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="developer_guide.html">
        &larr; Developer Guide
      </a>
    </div>
  </section>
</div>
:::

---

| Suite | Command |
|---|---|
| Python | `python -m pytest cryostack_src icesee_jupyter_book icesee_hpc_connector deployment` |
| Node (connector setup page) | `node --test deployment/tests/*.test.mjs` |
| Documentation | `jupyter-book build icesee_jupyter_book` |

**Source-guard tests.** Several tests assert on source text to prevent
regressions a unit test would miss — for example that neither gateway
reintroduces a personal default, that both still call the remote-access Run
gate, and that the shared responsive classes stay in the shared stylesheet.
When you rename or move code, update the corresponding guard.

**Gateway build tests.** The gateways are built end-to-end in tests with an
injected synthetic identity, so a broken widget tree fails fast without a
browser.

**What to run for each kind of change:**

| Change | Also run |
|---|---|
| An application gateway | that gateway's own test module, plus [Shared UI](dev_frontend.md)'s guard tests |
| A Remote/Cloud execution path | `cryostack_src/cloud/tests/`, `cryostack_src/models/tests/` |
| Connector/Relay | `icesee_hpc_connector/tests/`, the Node connector-page tests |
| A model adapter | that model's `cryostack_src/models/<model>/tests/`, plus `cryostack_src/workspace/tests/test_run_results.py` for result-package parity |
| Results/visualization | `cryostack_src/visualization/`'s tests, `cryostack_src/workspace/tests/test_run_results.py` |
| Cloud infrastructure (CloudFormation, IAM) | `cryostack_src/cloud/tests/test_cloud_connect_cloudformation.py`, `cryostack_src/cloud/tests/test_aws_secrets_manager.py` |
| Auto-config · Beta | the test list in [Extending CryoStack](dev_extending.md) |
| Documentation | `jupyter-book build icesee_jupyter_book` (inspect the rendered navigation, not just source) |

Always finish with the full Python suite before proposing a change; state
plainly what passed and what was skipped.

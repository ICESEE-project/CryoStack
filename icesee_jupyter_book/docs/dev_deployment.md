# Deployment & Maintenance

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
    <h1>Deployment &amp; Maintenance</h1>
    <p>
      Contribution workflow, documentation builds, and where the actual
      supported deployment/release procedures live.
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

## Contribution workflow

1. Branch from `main`. Keep a change focused — one concern per commit, a
   couple of small related commits at most.
2. Match the surrounding code: naming, comment density, and idiom.
3. Run the full Python suite, the Node tests when connector-page code
   changed, and the book build when documentation changed. State plainly
   what passed and what was skipped.
4. Never introduce a personal default, a credential, or a secret — the
   source-guard tests reject the obvious cases, but the responsibility is
   yours.
5. Open a pull request against `main` describing what changed and how it was
   verified.

## Documentation build

Build the book with `jupyter-book build icesee_jupyter_book` and inspect the
rendered `_build/html/` output, not just the source files — navigation
nesting, internal links/anchors, and styling only show up in the built
sidebar. The application sub-books (e.g. Frozen Legacies) build separately;
see `bin/build_application_docs.sh`.

## Connector, CloudFormation, and other operational procedures

Publishing a built Connector artifact, updating the CloudFormation templates
this repository ships (`deployment/cloudformation/`), and other production
deployment/rollback procedures (nginx, service administration, the canonical
release store) are **maintainer operations**, documented in the separate
Maintainer Guide at `/docs/maintainer/` — restricted at the authentication
boundary to accounts holding a `developer`, `maintainer`, `admin`, or `owner`
role (a project owner grants roles from the CryoStack Control Center). This
public Developer Guide documents what a contributor needs to build and test
changes; it intentionally does not restate that guide's operational
procedures. See [Connector & Relay](dev_connector.md)
for the specific boundary between the automated local build and the manual
publish step.

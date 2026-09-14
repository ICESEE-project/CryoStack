# CryoStack cross-account access role

`cryostack-execution-role.json` is the CloudFormation template the
**Connect AWS Account** flow opens in a user's AWS console (Quick Create).
It creates one IAM role, `CryoStackExecutionRole`, assumable only by the
CryoStack principal and only with the user's unique `ExternalId`.

## Regenerate

The template is generated from code — never hand-edit this file:

```bash
python -c "from cryostack_src.cloud.connect.cloudformation import render_template; \
  open('deployment/cloudformation/cryostack-execution-role.json','w').write(render_template()+'\n')"
```

`cryostack_src/cloud/tests/test_cloud_connect_cloudformation.py` guards that
the checked-in file matches `render_template()`.

## Deploy

1. Upload `cryostack-execution-role.json` to a public HTTPS URL
   (e.g. an S3 bucket with a static object).
2. Set on the CryoStack web deployment:
   - `CRYOSTACK_CF_TEMPLATE_URL` — that public URL
   - `CRYOSTACK_AWS_PRINCIPAL_ARN` — the CryoStack IAM role/user users' roles trust

Both are read by `cryostack_src/cloud/connect/onboarding.py`. Onboarding fails
with a clear message when either is unset.

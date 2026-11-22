# Releasing AutoSchema

The candidate is **0.4.0a1**, an alpha prerelease. The distribution is named
`autoschema`; Python imports remain `import autoschema`.

## One-time account setup

The intended repository is `https://github.com/adhni/autoschema`.
Create it as an empty public repository (no generated README or license), then
push the existing local history. The GitHub connector can edit repositories but
cannot create them. Verify the local GitHub CLI is signed in as `adhni` before pushing:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh api user --jq .login  # must print adhni
git push -u origin main
```

Configure a pending Trusted Publisher in **both** registries:

- [TestPyPI publisher setup](https://test.pypi.org/manage/account/publishing/)
- [PyPI publisher setup](https://pypi.org/manage/account/publishing/)

Use these exact fields:

| Field | Value |
| --- | --- |
| PyPI project name | `autoschema` |
| GitHub owner | `adhni` |
| Repository | `autoschema` |
| Workflow filename | `publish.yml` |
| Environment on TestPyPI | `testpypi` |
| Environment on PyPI | `pypi` |

Create matching GitHub repository environments named `testpypi` and `pypi`.
The workflow uses short-lived OIDC credentials; no API tokens belong in the
repository. See [PyPI's Trusted Publishing instructions](https://docs.pypi.org/trusted-publishers/using-a-publisher/).
The name returned HTTP 404 on both registries during preparation on 2026-11-22;
this does not reserve it or guarantee that registration will be accepted.

## Check and publish

1. Confirm the **Package checks** workflow passes on the candidate commit.
2. Run **Publish package** manually from `main`, choosing `testpypi`.
3. Confirm the TestPyPI upload succeeded, then run the same workflow from the
   **same commit**, choosing `pypi`. This run checks CI, installs the exact
   candidate version from TestPyPI, and exercises its preview API before upload.
4. After successful publication, tag that commit `v0.4.0a1` and create a GitHub
   prerelease. Update README publication status only after checking PyPI.

Do not alter code between the two registry runs. If code changes or a version
has already been uploaded, increment the version in `src/autoschema/_version.py`
and update the changelog; registry versions cannot be overwritten.

Users can explicitly install the alpha after publication:

```sh
python -m pip install 'autoschema==0.4.0a1'
```

For local distribution before publication:

```sh
python -m build
python -m twine check dist/autoschema-0.4.0a1*
python scripts/check_distribution.py dist/autoschema-0.4.0a1-py3-none-any.whl
```

Only upload artifacts for the intended version. Old files may still be present
in a developer's `dist/` folder; the publishing workflow builds in a fresh runner.

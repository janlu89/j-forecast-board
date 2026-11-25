# Continuous integration

`ci.yml` is the GitHub Actions workflow of this project: tests on Ubuntu and Windows with Python
3.12 and 3.14, the real setup scripts with the doctor on both systems, a dependency audit and a
secret scan.

It lives here until it is enabled: GitHub accepts files under `.github/workflows/` only from a
token with the `workflow` permission. To enable it:

```
gh auth refresh -h github.com -s workflow
git mv docs/ci/ci.yml .github/workflows/ci.yml
git commit -m "ci: enable the workflow" && git push
```

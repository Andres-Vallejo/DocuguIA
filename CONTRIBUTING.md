# Contributing

Use Python 3.12+ and work from a clone of the repository:

```sh
python -m venv .venv
# Activate .venv for your operating system.
python -m pip install -e ".[dev]"
python -m pytest -q
python -m evaluation.run
```

Changes to extraction, retrieval, permissions, citations or API contracts should include a regression case with invented documents. Tests must run without a Gemini key or network calls. Do not add work documents, personal information, API keys, local databases or screenshots of private content.

Describe the user-visible change, its limits, and the checks you ran. Keep retrieval evaluations separate from model answer evaluations: a quoted substring does not establish that a claim is correct. New formats must preserve locations and show clear extraction limits.

For a reproducible bug report, include the file format, steps, expected behavior and a minimal synthetic sample. Do not paste credentials into an issue.

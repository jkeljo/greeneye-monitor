==========================
Setting up dev environment
==========================

This repo uses Poetry to manage its dependencies, and pre-commit for pre-commit hooks.

1. `pip install poetry pre-commit` to add it to your Python installation if you don't have it already
2. `pre-commit install` to install the pre-commit hooks
3. `poetry install` to set up a venv with all needed dependencies
4. `poetry run pytest` (for example) to run tests
5. `poetry shell` to get a shell inside the poetry-created venv

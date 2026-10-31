set -e
apt-get update -qq && apt-get install -y -qq git
git config --global user.email t@t && git config --global user.name t
pip install -q -r /repo/requirements.txt
pip install -q pytest pytest-asyncio typer tomlkit
cd /repo && PYTHONPATH=/repo python -m pytest tests/test_security tests/tools_runtime tests/core/utils -q --no-header 2>&1 | tail -6
echo LINUX_SEC_DONE

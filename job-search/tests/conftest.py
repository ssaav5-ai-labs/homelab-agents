import os

os.environ.setdefault("JOBS_MCP_TOKEN", "test-token")
os.environ.setdefault("LAB_GATEWAY_URL", "http://localhost:4000")
os.environ.setdefault("JOBS_GATEWAY_KEY", "sk-test")
os.environ.setdefault("VAULT_READ_ROOT", "/tmp/vault-read")
os.environ.setdefault("VAULT_WORK_ROOT", "/tmp/vault-work")
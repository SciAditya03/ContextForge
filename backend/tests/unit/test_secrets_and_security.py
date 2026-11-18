from pathlib import Path

from app.services.security.secrets import find_secrets, redact_text

AWS = "AKIA" + "IOSFODNN7EXAMPLE"  # split so repository secret scanners don't flag the test itself
OPENAI = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwx1234"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def test_detects_provider_formats_and_assignments():
    text = f'aws = "{AWS}"\nkey = "{OPENAI}"\ntoken = "{GH}"\nJWT_SECRET = "Zx81kQp0vLmN3rT9"\n'
    kinds = {h.kind for h in find_secrets("cfg.py", text)}
    assert {"AWS access key id", "OpenAI API key", "GitHub token", "Hardcoded secret assignment"} <= kinds


def test_placeholders_and_templates_ignored():
    text = 'password = "changeme"\nAPI_KEY = "${API_KEY}"\nsecret = "your-secret-here"\npassword = "password"\n'
    assert find_secrets("settings.py", text) == []
    assert find_secrets(".env.example", 'JWT_SECRET="Zx81kQp0vLmN3rT9"', is_template=True) == []


def test_redaction_never_leaks_values():
    pem = "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEow\n-----END RSA " + "PRIVATE KEY-----"  # split: not a real key
    text = f'API_KEY = "Zx81kQp0vLmN3rT9aa"\nurl = "postgres://admin:S3cr3tP4ss@db/x"\nk = "{OPENAI}"\n{pem}\n'
    out, n = redact_text(text)
    for secret in ("Zx81kQp0vLmN3rT9aa", "S3cr3tP4ss", OPENAI, "MIIEow"):
        assert secret not in out
    assert n >= 4 and "[REDACTED_SECRET]" in out and "[REDACTED_PRIVATE_KEY]" in out
    hit = find_secrets("x.py", 'API_KEY = "Zx81kQp0vLmN3rT9aa"')[0]
    assert "Zx81kQp0vLmN3rT9aa" not in hit.redacted


def test_security_scanner_rules(tmp_path: Path):
    from app.schemas.facts import FileCategory, FileRecord
    from app.services.security.scanner import ScanContext, scan_security

    (tmp_path / "app.py").write_text(
        'import subprocess, os\n'
        'subprocess.run(cmd, shell=True)\n'
        'cur.execute(f"SELECT * FROM t WHERE id = {uid}")\n'
        'requests.get(url, verify=False)\n'
        'app.run(debug=True)\n'
        'data = pickle.loads(blob)\n'
    )
    (tmp_path / ".env").write_text("DB_PASSWORD=hunter2hunter2\n")
    files = [FileRecord(path="app.py", size=10, language="Python", category=FileCategory.SOURCE),
             FileRecord(path=".env", size=10, language="Env", category=FileCategory.ENV_FILE)]
    findings, secrets = scan_security(ScanContext(root=tmp_path, files=files, modules=[], routes=[], dependencies=[], env_vars=[], technologies=[]))
    cats = {f.category for f in findings}
    assert {"command-injection", "sql-injection", "insecure-transport", "configuration", "unsafe-deserialization", "secret-management"} <= cats
    assert all("hunter2" not in (f.evidence + f.explanation) for f in findings)

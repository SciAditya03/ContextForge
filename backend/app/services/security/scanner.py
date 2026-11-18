"""Layer 7: repository-level security and reliability analysis (static, no execution)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.facts import (
    Dependency,
    EnvVar,
    FileCategory,
    FileRecord,
    Finding,
    ModuleInfo,
    Route,
    SecretHit,
    Technology,
)
from app.services.security.secrets import find_secrets


@dataclass
class ScanContext:
    root: Path
    files: list[FileRecord]
    modules: list[ModuleInfo]
    routes: list[Route]
    dependencies: list[Dependency]
    env_vars: list[EnvVar]
    technologies: list[Technology]
    texts: dict[str, str] = field(default_factory=dict)

    def text(self, path: str) -> str:
        if path not in self.texts:
            try:
                self.texts[path] = (self.root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self.texts[path] = ""
        return self.texts[path]


def _python_string_spans(text: str) -> dict[int, list[tuple[int, int]]]:
    """Column spans (per 1-based line) covered by string literals, so regex rules ignore text inside strings."""
    import io
    import tokenize

    spans: dict[int, list[tuple[int, int]]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type not in (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", -1)):  # f-string bodies are FSTRING_MIDDLE on 3.12+
                continue
            (sl, sc), (el, ec) = tok.start, tok.end
            for ln in range(sl, el + 1):
                spans.setdefault(ln, []).append((sc if ln == sl else 0, ec if ln == el else 10**6))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}
    return spans


def _fid(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode(), usedforsecurity=False).hexdigest()[:10]


@dataclass
class LineRule:
    title: str
    severity: str
    category: str
    group: str
    languages: set[str]
    pattern: re.Pattern[str]
    explanation: str
    impact: str
    suggestion: str
    confidence: float
    status: str = "suspicious"
    exclude: re.Pattern[str] | None = None


PY = {"Python"}
JS = {"JavaScript", "TypeScript"}
ANY = PY | JS | {"Go", "Java", "Kotlin", "PHP", "Ruby", "C#", "Rust"}

LINE_RULES: list[LineRule] = [
    LineRule("SQL built with string formatting", "high", "sql-injection", "security", PY,
             re.compile(r"\.(execute|executemany|raw|text)\(\s*(f[\"']|[\"'][^\"']*[\"']\s*(%|\+|\.format\())", re.I),
             "A SQL statement passed to an execute/raw call is built with f-strings, % formatting, concatenation or .format().",
             "If any interpolated value is user-controlled this is a SQL injection vector.",
             "Use parameterised queries (placeholders + params tuple) or the ORM query builder.", 0.75),
    LineRule("SQL built with template literal / concatenation", "high", "sql-injection", "security", JS,
             re.compile(r"\.(query|execute|raw|\$queryRawUnsafe|\$executeRawUnsafe)\(\s*(`[^`]*\$\{|[\"'][^\"']*[\"']\s*\+)"),
             "A SQL string passed to a query call interpolates values with ${...} or string concatenation.",
             "User-controlled values inside the SQL text allow SQL injection.",
             "Use placeholders ($1, ?) with a values array, or a tagged-template-safe API such as Prisma $queryRaw``.", 0.75),
    LineRule("Shell command execution with shell=True", "high", "command-injection", "security", PY,
             re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"),
             "subprocess is invoked through the shell.", "Interpolated arguments can inject shell commands.",
             "Pass an argument list and shell=False; validate inputs with an allow-list.", 0.7),
    LineRule("os.system / os.popen call", "medium", "command-injection", "security", PY, re.compile(r"\bos\.(system|popen)\("),
             "A command is executed through the system shell.", "Command injection if any part of the command is user-influenced.",
             "Use subprocess.run([...]) with an argument list.", 0.6),
    LineRule("child_process exec with dynamic command", "high", "command-injection", "security", JS,
             re.compile(r"\b(exec|execSync)\(\s*(`[^`]*\$\{|[\"'][^\"']*[\"']\s*\+|\w+\s*\+)"),
             "child_process.exec is called with an interpolated command string.", "Shell metacharacters in inputs lead to command injection.",
             "Use execFile/spawn with an argument array and validate inputs.", 0.7),
    LineRule("Use of eval / exec", "high", "code-injection", "security", PY | JS,
             re.compile(r"(?<![\w.])(eval|exec)\(\s*(?![\"'`]\s*\))"),
             "Dynamic code evaluation is used.", "Evaluating attacker-influenced strings allows arbitrary code execution.",
             "Remove eval/exec; parse data with a safe parser (json, ast.literal_eval).", 0.55,
             exclude=re.compile(r"(\.exec\(|regex|RegExp|re\.\w+\(|cursor\.|\.execute|subprocess|db\.|session\.|\bexecSync|child_process|asyncio)")),
    LineRule("Unsafe deserialisation (pickle/marshal)", "high", "unsafe-deserialization", "security", PY,
             re.compile(r"\b(pickle|cPickle|marshal|dill)\.loads?\("),
             "pickle/marshal deserialises arbitrary objects.", "Loading untrusted data executes attacker-controlled code.",
             "Use JSON or a schema-validated format for untrusted input.", 0.6),
    LineRule("yaml.load without SafeLoader", "medium", "unsafe-deserialization", "security", PY,
             re.compile(r"\byaml\.load\((?![^)]*(SafeLoader|safe_load|CSafeLoader))"),
             "yaml.load is used without an explicit safe loader.", "Older PyYAML versions construct arbitrary Python objects.",
             "Use yaml.safe_load().", 0.7),
    LineRule("TLS certificate verification disabled", "high", "insecure-transport", "security", PY | JS,
             re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0"),
             "HTTPS certificate verification is disabled.", "Traffic can be intercepted by a man-in-the-middle.",
             "Enable verification; configure a custom CA bundle if needed.", 0.85, status="confirmed"),
    LineRule("JWT verification disabled", "critical", "authentication", "security", PY | JS,
             re.compile(r"verify_signature[\"']?\s*:\s*False|options\s*=\s*\{[^}]*\"verify_signature\"\s*:\s*False|algorithms\s*=\s*\[\s*[\"']none[\"']|jwt\.decode\([^)]*verify\s*=\s*False|ignoreExpiration\s*:\s*true"),
             "JWT tokens are decoded without signature/expiry verification or with the 'none' algorithm.",
             "Attackers can forge tokens and impersonate any user.", "Always verify signature, expiry and pin the expected algorithm.", 0.85, status="confirmed"),
    LineRule("jwt.decode without verification (jsonwebtoken)", "high", "authentication", "security", JS,
             re.compile(r"\bjwt\.decode\("), "jsonwebtoken's jwt.decode() does not verify signatures.",
             "If used for authorisation decisions, tokens can be forged.", "Use jwt.verify() with a secret/public key and algorithms option.", 0.5),
    LineRule("Weak hash used (MD5/SHA1)", "medium", "cryptography", "security", PY | JS,
             re.compile(r"hashlib\.(md5|sha1)\(|createHash\(\s*['\"](md5|sha1)['\"]"),
             "MD5/SHA1 are used.", "If used for passwords or integrity against attackers, these hashes are broken.",
             "Use bcrypt/argon2 for passwords and SHA-256+ (or HMAC) for integrity.", 0.45,
             exclude=re.compile(r"usedforsecurity\s*=\s*False")),
    LineRule("Debug mode enabled", "medium", "configuration", "security", PY | JS,
             re.compile(r"\.run\([^)]*debug\s*=\s*True|^\s*DEBUG\s*=\s*True\b|app\.debug\s*=\s*True"),
             "The application enables debug mode in code.", "Debug mode can expose stack traces, consoles and secrets in production.",
             "Drive debug mode from an environment variable that defaults to off.", 0.6),
    LineRule("Permissive CORS (wildcard origin)", "medium", "cors", "security", PY | JS,
             re.compile(r"allow_origins\s*=\s*\[\s*[\"']\*[\"']|origin\s*:\s*[\"']\*[\"']|Access-Control-Allow-Origin[\"']?\s*,\s*[\"']\*|CORS\(\s*app\s*\)|cors\(\s*\)"),
             "CORS allows any origin.", "Any website can call the API from a browser; combined with credentials this leaks user data.",
             "Restrict allowed origins to known frontends; never combine '*' with credentials.", 0.65,
             exclude=re.compile(r"re\.compile\(|LineRule\(|RegExp\(")),
    LineRule("Sensitive value written to logs", "medium", "sensitive-logging", "security", PY | JS,
             re.compile(r"(print|console\.(log|info|debug|warn|error)|log(ger)?\.(info|debug|warning|error|warn))\([^)]*\b(password|passwd|secret|token|api_?key|authorization|credit_?card)\b", re.I),
             "A log/print statement references a sensitive variable.", "Secrets or credentials may end up in log files or monitoring systems.",
             "Remove the value from logs or mask it.", 0.5),
    LineRule("Unsafe archive extraction", "medium", "unsafe-file-operation", "security", PY,
             re.compile(r"\.extractall\("), "Archive contents are extracted without visible path validation.",
             "Path traversal (zip-slip) can overwrite arbitrary files.", "Validate each member path before extraction (or use filter='data' on tarfile).", 0.5),
    LineRule("File path built from request data", "high", "path-traversal", "security", PY | JS,
             re.compile(r"(open|send_file|send_from_directory|sendFile|readFile|readFileSync|createReadStream|FileResponse)\([^)]*\b(req|request)\.(params|query|body|args|form|GET|POST|files)"),
             "A filesystem path is derived directly from request input.", "Attackers can read or write files outside the intended directory.",
             "Normalise and validate paths against an allow-listed base directory.", 0.65),
    LineRule("innerHTML / dangerouslySetInnerHTML", "medium", "xss", "security", JS,
             re.compile(r"dangerouslySetInnerHTML|\.innerHTML\s*="), "HTML is injected into the DOM directly.",
             "Unsanitised user content leads to cross-site scripting.", "Sanitise with DOMPurify or render text content.", 0.5),
    LineRule("HTTP request without timeout", "low", "missing-timeout", "reliability", PY,
             re.compile(r"\brequests\.(get|post|put|delete|patch|request)\((?![^)]*timeout)"),
             "requests call without a timeout.", "A slow upstream can hang the worker indefinitely.", "Pass timeout=(connect, read).", 0.6),
    LineRule("Blocking call inside async code", "medium", "blocking-io", "reliability", PY,
             re.compile(r"^\s+(time\.sleep\(|requests\.(get|post|put|delete|patch)\()"),
             "A blocking call appears in an indented block (verify whether it is inside an async def).",
             "Blocking the event loop stalls every concurrent request.", "Use asyncio.sleep / httpx.AsyncClient or run in a thread executor.", 0.3,
             status="manual_verification"),
    LineRule("Bare except / swallowed exception", "low", "error-handling", "reliability", PY,
             re.compile(r"^\s*except\s*:\s*$|^\s*except\s+(Exception|BaseException)(\s+as\s+\w+)?\s*:\s*(pass)?\s*$"),
             "Broad exception handler.", "Masks real failures and makes debugging difficult.", "Catch specific exceptions and log or re-raise.", 0.5),
    LineRule("Empty catch block", "low", "error-handling", "reliability", JS,
             re.compile(r"catch\s*(\(\s*\w*\s*\))?\s*\{\s*\}"), "An exception is caught and silently ignored.",
             "Failures disappear without trace.", "Log the error or handle it explicitly.", 0.6),
    LineRule("Unbounded DELETE/UPDATE", "high", "database", "reliability", ANY,
             re.compile(r"[\"'`]\s*(DELETE\s+FROM\s+\w+|UPDATE\s+\w+\s+SET\s+[^\"'`]*?)\s*[\"'`;]", re.I),
             "A DELETE/UPDATE statement without a WHERE clause appears in code.", "Executing it affects every row in the table.",
             "Confirm intent; add WHERE conditions or guard with explicit confirmation.", 0.5, exclude=re.compile(r"WHERE", re.I)),
    LineRule("Mass deletion without filter", "medium", "database", "reliability", JS | PY,
             re.compile(r"\.(deleteMany|delete_many)\(\s*(\{\s*\})?\s*\)"), "A deleteMany/delete_many is called with an empty filter.",
             "Deletes every document/row of the collection.", "Pass an explicit filter.", 0.6),
]

# small offline advisory table — only well-known, widely published advisories
ADVISORIES: list[tuple[str, str, str, str, str]] = [
    # ecosystem, package, fixed_version, id, summary
    ("npm", "lodash", "4.17.21", "CVE-2021-23337", "Command injection via template()"),
    ("npm", "minimist", "1.2.6", "CVE-2021-44906", "Prototype pollution"),
    ("npm", "jsonwebtoken", "9.0.0", "CVE-2022-23529", "Multiple verification bypass issues fixed in 9.0.0"),
    ("npm", "axios", "0.21.1", "CVE-2020-28168", "SSRF via redirect handling"),
    ("npm", "express", "4.19.2", "CVE-2024-29041", "Open redirect in res.location/redirect"),
    ("pypi", "pyyaml", "5.4", "CVE-2020-14343", "Arbitrary code execution in full_load/FullLoader"),
    ("pypi", "requests", "2.31.0", "CVE-2023-32681", "Proxy-Authorization header leak on redirects"),
    ("pypi", "flask", "2.2.5", "CVE-2023-30861", "Session cookie may be cached by proxies"),
    ("pypi", "jinja2", "3.1.3", "CVE-2024-22195", "XSS via xmlattr filter"),
]


def _vtuple(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v)
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def _min_version(spec: str | None) -> tuple[str | None, bool]:
    """Return (lowest version allowed by spec, exact_pin)."""
    if not spec:
        return None, False
    s = spec.strip()
    m = re.match(r"^(==|=)?\s*v?(\d+(?:\.\d+){0,3})$", s)
    if m:
        return m.group(2), True
    m = re.search(r"(?:\^|~|>=|~=|>)\s*v?(\d+(?:\.\d+){0,3})", s)
    if m:
        return m.group(1), False
    return None, False


def scan_security(ctx: ScanContext) -> tuple[list[Finding], list[SecretHit]]:
    findings: list[Finding] = []
    secrets: list[SecretHit] = []
    text_files = [f for f in ctx.files if f.status == "included" and not f.is_binary and f.size < 2_000_000]

    for f in text_files:
        is_template = f.category == FileCategory.ENV_TEMPLATE
        text = ctx.text(f.path)
        hits = find_secrets(f.path, text, is_template=is_template)
        if hits:
            f.has_secrets = True
            secrets.extend(hits)
            for h in hits:
                weak_url_cred = h.kind == "Credentials in connection URL" and h.weak
                sev = "low" if weak_url_cred else ("critical" if h.kind not in {"Hardcoded secret assignment", "JSON Web Token", "Credentials in connection URL"} else "high")
                in_test = f.category == FileCategory.TEST
                findings.append(Finding(
                    id=_fid("secret", h.file, h.line, h.kind), title=f"Possible hardcoded secret: {h.kind}", severity="medium" if in_test else sev,
                    category="hardcoded-secret", file=h.file, line_start=h.line, line_end=h.line,
                    explanation=(f"A value matching the '{h.kind}' pattern is present in the repository. Value: {h.redacted}"
                                 + (" The password looks like a development default." if weak_url_cred else "")),
                    evidence=f"{h.file}:{h.line} (value redacted)", impact="Anyone with repository access can use this credential.",
                    suggestion="Rotate the credential, remove it from history, and load it from the environment or a secret manager.",
                    confidence=0.8 if sev == "critical" else 0.55, status="confirmed" if sev == "critical" and not in_test else "suspicious", group="security",
                ))
        if f.category == FileCategory.ENV_FILE and text.strip():
            real = _env_real_secret_keys(text)
            assignments = len([ln for ln in text.splitlines() if "=" in ln and not ln.lstrip().startswith("#")])
            findings.append(Finding(
                id=_fid("envfile", f.path), title="Environment file committed to repository", severity="high" if real else "low", category="secret-management",
                file=f.path, line_start=1,
                explanation=(f"`{f.path}` is a real environment file (not a template) included in the archive. "
                             + (f"Sensitive-looking keys with non-placeholder values: {', '.join(real[:8])}." if real else
                                "All sensitive-looking values appear to be placeholders or empty (e.g. 'changethis').")),
                evidence=f"{f.path} contains {assignments} assignments (values not reproduced)",
                impact="Environment files usually contain credentials and environment-specific configuration.",
                suggestion="Add it to .gitignore, commit a .env.example with placeholders instead, and rotate any real values.",
                confidence=0.8 if real else 0.5, status="confirmed" if real else "suspicious", group="security",
            ))

        if f.language not in ANY:
            continue
        lines = text.splitlines()
        string_spans = _python_string_spans(text) if f.language == "Python" else {}
        for rule in LINE_RULES:
            if f.language not in rule.languages:
                continue
            count = 0
            for i, line in enumerate(lines, 1):
                if len(line) > 2000:
                    continue
                hit = rule.pattern.search(line)
                if not hit:
                    continue
                if string_spans and any(a <= hit.start() < b for a, b in string_spans.get(i, ())):
                    continue  # the match is inside a string literal / docstring, not code
                if rule.exclude and rule.exclude.search(line):
                    continue
                stripped = line.strip()
                if stripped.startswith(("#", "//", "*")):
                    continue
                count += 1
                if count > 5:
                    break
                sev = rule.severity
                status = rule.status
                explanation = rule.explanation
                if f.category == FileCategory.MIGRATION and rule.category in ("database",):
                    sev, status = "info", "suspicious"
                    explanation += " It is inside a migration, where table-wide statements are usually intentional."
                if f.generated:
                    sev = "info"
                    explanation += " (generated code)"
                if f.category == FileCategory.TEST:
                    sev = "info" if sev in {"low", "medium"} else "low"
                    status = "suspicious"
                findings.append(Finding(
                    id=_fid(rule.title, f.path, i), title=rule.title, severity=sev, category=rule.category, file=f.path,
                    line_start=i, line_end=i, explanation=explanation, evidence=_evidence_line(stripped),
                    impact=rule.impact, suggestion=rule.suggestion, confidence=rule.confidence if f.category != FileCategory.TEST else rule.confidence * 0.5,
                    status=status, group=rule.group,
                ))

    findings.extend(_cors_credentials(ctx))
    findings.extend(_authorization_gaps(ctx))
    findings.extend(_input_validation(ctx))
    findings.extend(_dependency_advisories(ctx))
    return findings, secrets


_SENSITIVE_KEY = re.compile(r"(SECRET|PASSWORD|PASSWD|TOKEN|API_?KEY|PRIVATE|CREDENTIAL|AUTH)", re.I)


def _env_real_secret_keys(text: str) -> list[str]:
    from app.services.security.secrets import _is_placeholder

    keys = []
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m or not _SENSITIVE_KEY.search(m.group(1)):
            continue
        val = m.group(2).strip().strip("'\"")
        if val and not _is_placeholder(val) and not re.search(r"(?i)change|example|placeholder|dummy|your|xxx|todo|secret$|password$", val):
            keys.append(m.group(1))
    return keys


def _evidence_line(line: str) -> str:
    from app.services.security.secrets import redact_text

    red, _ = redact_text(line[:240])
    return red


def _python_cors_wildcard_with_credentials(text: str) -> int | None:
    """AST check: CORSMiddleware(...) / add_middleware(CORSMiddleware, ...) with allow_origins=['*'] and allow_credentials=True."""
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kws = {k.arg: k.value for k in node.keywords if k.arg}
        origins, creds = kws.get("allow_origins"), kws.get("allow_credentials")
        wildcard = isinstance(origins, ast.List | ast.Tuple) and any(isinstance(e, ast.Constant) and e.value == "*" for e in origins.elts)
        if wildcard and isinstance(creds, ast.Constant) and creds.value is True:
            return node.lineno
    return None


def _cors_credentials(ctx: ScanContext) -> list[Finding]:
    out = []
    for m in ctx.modules:
        if m.language != "Python":
            continue
        text = ctx.text(m.path)
        line = _python_cors_wildcard_with_credentials(text) if "allow_credentials" in text else None
        if line is not None:
            out.append(Finding(id=_fid("corscred", m.path), title="CORS wildcard origin combined with credentials", severity="high", category="cors",
                               file=m.path, line_start=line, explanation="CORSMiddleware is configured with allow_origins=['*'] and allow_credentials=True.",
                               evidence="allow_origins=['*'] + allow_credentials=True", impact="Browsers reject this combination or (with reflective setups) any site can make credentialed requests.",
                               suggestion="List explicit trusted origins.", confidence=0.85, status="confirmed", group="security"))
    return out


def _authorization_gaps(ctx: ScanContext) -> list[Finding]:
    out: list[Finding] = []
    http = [r for r in ctx.routes if r.kind == "http"]
    with_auth = [r for r in http if r.auth]
    if not http:
        return out
    has_auth_system = bool(with_auth) or any(t.category == "auth" for t in ctx.technologies)
    if not has_auth_system:
        mutating = [r for r in http if r.method in {"POST", "PUT", "PATCH", "DELETE"}]
        if mutating:
            r0 = mutating[0]
            out.append(Finding(id=_fid("noauth"), title="No authentication mechanism detected for mutating endpoints", severity="medium",
                               category="authorization", file=r0.file, line_start=r0.line,
                               explanation=f"{len(mutating)} state-changing endpoints were found and no authentication dependency, middleware or library was detected.",
                               evidence=", ".join(f"{r.method} {r.path}" for r in mutating[:8]), impact="If the service is exposed, anyone can modify data.",
                               suggestion="Confirm whether authentication happens at a gateway; otherwise add auth middleware/dependencies.",
                               confidence=0.4, status="manual_verification", group="security"))
        return out
    for r in http:
        if r.method in {"POST", "PUT", "PATCH", "DELETE"} and not r.auth and not re.search(r"(login|register|signup|sign-up|token|auth|webhook|health|callback|password|reset|verify)", r.path, re.I):
            text = ctx.text(r.file)
            # middleware applied at router/file level counts as protection
            if re.search(r"(router|app)\.use\(\s*(require)?\w*[aA]uth|dependencies\s*=\s*\[\s*Depends\(\s*\w*(auth|user)", text):
                continue
            out.append(Finding(id=_fid("authgap", r.file, r.line, r.method, r.path), title=f"Mutating endpoint without detected auth: {r.method} {r.path}",
                               severity="medium", category="authorization", file=r.file, line_start=r.line,
                               explanation="Other endpoints in this project declare authentication, but this state-changing endpoint has no detected auth dependency/middleware.",
                               evidence=f"handler {r.handler or '?'} ({r.framework})", impact="Possible missing authorization check allowing unauthenticated modification.",
                               suggestion="Verify whether protection is applied globally; otherwise add the project's auth dependency.", confidence=0.45,
                               status="manual_verification", group="security"))
    return out[:40]


def _input_validation(ctx: ScanContext) -> list[Finding]:
    out: list[Finding] = []
    has_validator = any(t.category == "validation" for t in ctx.technologies)
    for r in ctx.routes:
        if r.framework != "Express" or r.method not in {"POST", "PUT", "PATCH"}:
            continue
        text = ctx.text(r.file)
        if "req.body" in text and not has_validator and not re.search(r"(validate|schema|zod|joi|yup|express-validator|celebrate)", text, re.I):
            out.append(Finding(id=_fid("val", r.file, r.line), title=f"Request body used without visible validation: {r.method} {r.path}", severity="low",
                               category="input-validation", file=r.file, line_start=r.line,
                               explanation="The handler file reads req.body and no validation library or schema check was detected.",
                               evidence="req.body usage; no validation library in dependencies", impact="Malformed or malicious payloads reach business logic and the database.",
                               suggestion="Validate payloads with zod/joi/express-validator before use.", confidence=0.4, status="suspicious", group="security"))
    for m in ctx.modules:
        if m.language != "Python" or has_validator:
            continue
        text = ctx.text(m.path)
        if "request.get_json" in text or ("request.json" in text and "flask" in text.lower()):
            out.append(Finding(id=_fid("valpy", m.path), title="Flask request JSON used without schema validation", severity="low", category="input-validation",
                               file=m.path, line_start=1, explanation="request.json/get_json is used and no validation library was detected.",
                               evidence="request.json usage", impact="Unvalidated input reaches business logic.", suggestion="Validate with pydantic/marshmallow.",
                               confidence=0.35, status="suspicious", group="security"))
    return out[:30]


def _dependency_advisories(ctx: ScanContext) -> list[Finding]:
    out: list[Finding] = []
    for d in ctx.dependencies:
        for eco, pkg, fixed, adv, summary in ADVISORIES:
            if d.ecosystem != eco or d.name.lower() != pkg:
                continue
            mv, exact = _min_version(d.version)
            if mv is None or _vtuple(mv) >= _vtuple(fixed):
                continue
            out.append(Finding(
                id=_fid("adv", d.manifest, d.name), title=f"{d.name} {d.version} may be affected by {adv}", severity="high" if exact else "medium",
                category="vulnerable-dependency", file=d.manifest, line_start=d.line,
                explanation=f"{adv}: {summary}. Fixed in {fixed}. Declared constraint: `{d.version}`.",
                evidence=f"{d.manifest}: {d.name} {d.version}",
                impact="Known vulnerability in a direct dependency.",
                suggestion=f"Upgrade {d.name} to >= {fixed} and check the lockfile resolution.",
                confidence=0.85 if exact else 0.45, status="confirmed" if exact else "manual_verification", group="security",
            ))
    return out

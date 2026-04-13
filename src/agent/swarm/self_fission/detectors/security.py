"""SecurityDetector — 安全漏洞检测

检测代码中潜在的安全漏洞，如 eval/exec、SQL 注入、硬编码密钥等。
触发标签: #Security
"""
from __future__ import annotations

from .base import CodeContext, FeatureDetector, SemanticFeature

# 危险函数/模式
DANGEROUS_PATTERNS: set[str] = {
    'eval(', 'exec(', 'compile(', 'os.system(', 'subprocess.call(',
    'subprocess.Popen(', 'os.popen(',
}

# 安全相关关键词
SECURITY_KEYWORDS: set[str] = {
    'auth', 'authenticate', 'authorize', 'permission', 'role', 'token',
    'password', 'secret', 'api_key', 'apikey', 'access_key',
    'sql', 'query', 'cursor', 'execute', 'insert', 'update', 'delete',
    'sanitize', 'escape', 'validate', 'whitelist', 'blacklist',
    'cors', 'csrf', 'xss', 'injection', 'vulnerability',
}

# 硬编码密钥模式
HARDCODED_SECRET_PATTERNS = [
    r'(?:api_key|secret_key|password|token)\s*=\s*["\'][^"\']+["\']',
    r'(?:API_KEY|SECRET|PASSWORD|TOKEN)\s*=\s*["\'][^"\']+["\']',
]


class SecurityDetector(FeatureDetector):
    """安全漏洞检测器

    检测代码中潜在的安全问题。
    """

    @property
    def tag(self) -> str:
        return "#Security"

    def detect(self, context: CodeContext) -> SemanticFeature | None:
        """检测安全相关特征

        评分规则:
        - 使用危险函数 (eval/exec): +0.5 per pattern
        - 安全关键词: +0.08 per keyword (max 0.4)
        - 硬编码密钥模式: +0.4 per match
        """
        score = 0.0
        evidence: list[str] = []
        severity = "low"

        source_lines = context.source_code.split('\n')
        source_lower = context.source_code.lower()

        # 检查危险函数
        dangerous_found = []
        for pattern in DANGEROUS_PATTERNS:
            if pattern in context.source_code:
                score += 0.5
                dangerous_found.append(pattern)
                for i, line in enumerate(source_lines, 1):
                    if pattern in line:
                        evidence.append(f"DANGER line {i}: {line.strip()[:80]}")
                        break

        if dangerous_found:
            severity = "critical"

        # 检查安全关键词
        security_keywords_found = set()
        for keyword in SECURITY_KEYWORDS:
            if keyword.lower() in source_lower:
                score += 0.08
                security_keywords_found.add(keyword)

        keyword_score = min(0.4, len(security_keywords_found) * 0.08)
        score = min(score, 0.5) + keyword_score  # 危险函数最多 0.5 + 关键词最多 0.4

        # 检查硬编码密钥
        import re
        hardcoded_found = []
        for pattern in HARDCODED_SECRET_PATTERNS:
            matches = re.findall(pattern, context.source_code, re.IGNORECASE)
            if matches:
                hardcoded_found.extend(matches)
                score += 0.4
                for match in matches[:3]:
                    evidence.append(f"HARDCODED: {match[:60]}")

        if hardcoded_found and severity != "critical":
            severity = "high"

        confidence = min(1.0, score)

        if confidence >= 0.4:  # 较低阈值，因为安全检测很重要
            return SemanticFeature(
                tag=self.tag,
                confidence=confidence,
                evidence=evidence[:10],
                severity=severity,
            )

        return None

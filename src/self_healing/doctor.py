"""
Project Doctor - Autonomous project health diagnostics and repair.

Inspired by Project B's doctor pattern to ensure environment and configuration stability.
"""

import logging
import os
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class DiagnosticResult:
    """Represents the result of a single diagnostic check."""
    id: str
    name: str
    status: str  # "PASS", "FAIL", "WARN"
    message: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    details: dict[str, Any] = field(default_factory=dict)
    can_fix: bool = False
    fix_action: Callable[[], bool] | None = None

class ProjectDoctor:
    """
    Diagnoses and repairs common project environment and configuration issues.
    Implements Project B's autonomous diagnostic pattern.
    """

    def __init__(self, project_root: Path | None = None, detection_threshold: float = 0.2):
        self.project_root = project_root or Path.cwd()
        self.detection_threshold = detection_threshold  # WARN if > 20% error rate
        self.results: list[DiagnosticResult] = []
        self._failed_checks = 0

    def run_all(self) -> list[DiagnosticResult]:
        """Run all registered diagnostic checks."""
        self.results = []
        self._failed_checks = 0
        logger.info("🔍 Starting Project Doctor diagnostics...")

        # 1. Environment Checks
        self._check_python_version()
        self._check_platform()
        self._check_disk_space()
        self._check_memory()

        # 2. Configuration Checks
        self._check_dot_env()
        self._check_config_json()
        self._check_budget_guard()

        # 3. Dependency Checks
        self._check_key_dependencies()
        self._check_installed_binaries()
        self._check_integration_hooks()

        # 4. Project Health
        self._check_task_load()
        self._check_freshness_state()
        self._check_orchestrator_health()
        self._check_status_summary()

        logger.info("✅ Project Doctor diagnostics completed.")
        return self.results

    def diagnose_and_repair(self) -> dict[str, list[DiagnosticResult]]:
        """
        Diagnostic-first approach with auto-repair capabilities.
        Returns repair actions grouped by symptom.
        """
        self.run_all()

        # Group results by status
        fails = [r for r in self.results if r.status == "FAIL"]
        warns = [r for r in self.results if r.status == "WARN"]

        if fails and len(fails) > self.detection_threshold * len(self.results):
            logger.warning(f"🚨 Critical issues found: {len(fails)} failures")

        if warns and len(warns) > (self.detection_threshold * len(self.results)):
            logger.warning(f"⚠️  High warning count: {len(warns)} warnings")

        # Execute auto-fix actions for failed checks that can be fixed automatically
        auto_fix_results = []
        for result in self.results:
            if result.status == "FAIL" and result.can_fix and result.fix_action:
                try:
                    if result.fix_action():
                        result.status = "PASS"
                        self._failed_checks -= 1
                        logger.info(f"✅ Auto-fixed: {result.name}")
                        auto_fix_results.append(result)
                except Exception as e:
                    logger.error(f"❌ Failed to auto-fix {result.name}: {e}")

        # Generate repair report
        repair_plan = {
            "critical": [r for r in fails if r.status == "FAIL"],
            "warnings": [r for r in warns if r.status == "WARN"],
            "auto_fixed": auto_fix_results,
            "summary": self.get_summary()
        }

        return repair_plan

    def _check_python_version(self):
        """Check if the Python version meets requirements."""
        version = sys.version_info
        required_major = 3
        required_minor = 10

        status = "PASS" if (version.major == required_major and version.minor >= required_minor) else "FAIL"
        color = "🔴" if status == "FAIL" else "🟢"
        message = f"{color} Python {sys.version.split()[0]} {status} {required_major}.{required_minor}+"

        self._add_result(
            DiagnosticResult(
                id="env_python_version",
                name="Python Version",
                status=status,
                message=message,
                details={"required": f"{required_major}.{required_minor}", "current": str(version)}
            )
        )

    def _check_platform(self):
        """Report current operating system platform."""
        platform_info = f"{platform.system()} {platform.release().lower()} ({platform.machine()})"
        self._add_result(
            DiagnosticResult(
                id="env_platform",
                name="Operating System",
                status="PASS",
                message=platform_info
            )
        )

    def _check_disk_space(self):
        """Check available disk space for run directory."""
        try:
            if sys.platform == 'win32':
                import ctypes
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(str(self.project_root)), None, None, ctypes.pointer(free_bytes))
                available_bytes = free_bytes.value
            else:
                stat = os.statvfs(str(self.project_root))
                block_size = stat.f_frsize
                available_bytes = stat.f_bavail * block_size

            needed_bytes = 500 * 1024 * 1024  # 500MB minimum
            status = "PASS" if available_bytes >= needed_bytes else "WARN"
            message = "Sufficient disk space" if status == "PASS" else "Critical low disk space"

            self._add_result(
                DiagnosticResult(
                    id="disk_space",
                    name="Disk Space",
                    status=status,
                    message=message,
                    details={
                        "available_gb": f"{available_bytes / (1024**3):.1f}GB",
                        "required_gb": f"{needed_bytes / (1024**3):.0f}GB"
                    }
                )
            )
        except Exception as e:
            self._add_result(
                DiagnosticResult(
                    id="disk_space",
                    name="Disk Space",
                    status="WARN",
                    message=f"Error checking disk space: {e!s}",
                    details={"error": str(e)}
                )
            )

    def _check_memory(self):
        """Check available memory for run operations."""
        import psutil
        try:
            memory = psutil.virtual_memory()
            available_pct = (memory.available / memory.total) * 100
            status = "PASS" if available_pct > 15 else "WARN"
            message = f"{available_pct:.1f}% memory available"
            color = "🟢" if status == "PASS" else "🟡"

            self._add_result(
                DiagnosticResult(
                    id="memory_availability",
                    name="Memory Availability",
                    status=status,
                    message=f"{color} {message}",
                    details={"available_percent": f"{available_pct:.1f}"}
                )
            )
        except ImportError:
            self._add_result(
                DiagnosticResult(
                    id="memory_availability",
                    name="Memory Availability",
                    status="WARN",
                    message="Module psutil not available - cannot verify memory",
                )
            )

    def _check_dot_env(self):
        """Check for existence of .env file."""
        env_path = self.project_root / ".env"
        exists = env_path.exists()

        self._add_result(
            DiagnosticResult(
                id="cfg_dot_env",
                name="Environment File (.env)",
                status="PASS" if exists else "WARN",
                message=".env file exists" if exists else "Recommended: .env file missing for secrets",
                can_fix=not exists,  # Can fix by creating it
                details={"path": str(env_path)}
            )
        )

    def _check_config_json(self):
        """Check for main configuration files."""
        config_path = self.project_root / ".clawd" / "settings.json"
        exists = config_path.exists()

        self._add_result(
            DiagnosticResult(
                id="cfg_settings_json",
                name="Core Settings",
                status="PASS" if exists else "FAIL",
                message="Settings file found" if exists else "Settings file missing at .clawd/settings.json",
                details={"path": str(config_path)}
            )
        )

    def _check_budget_guard(self):
        """Check if Budget Guard integration is active."""
        budget_guard_path = self.project_root / "src" / "tools_budget" / "guard.py"
        exists = budget_guard_path.exists()

        self._add_result(
            DiagnosticResult(
                id="budget_guard",
                name="Budget Guard Integration",
                status="PASS" if exists else "WARN",
                message="Budget Guard active" if exists else "Consider enabling Budget Guard for resource safety",
                details={"path": str(budget_guard_path)}
            )
        )

    def _check_key_dependencies(self):
        """Check if key Python dependencies are available."""
        dependencies = ['openai', 'pydantic', 'jsonschema']
        missing = []

        for dep in dependencies:
            try:
                __import__(dep)
            except ImportError:
                missing.append(dep)

        status = "FAIL" if missing else "PASS"
        message = "Missing dependencies: " + ", ".join(missing) if missing else "All key dependencies available"

        self._add_result(
            DiagnosticResult(
                id="dep_key_packages",
                name="Key Dependencies",
                status=status,
                message=message
            )
        )

    def _check_installed_binaries(self):
        """Check for required binaries."""
        required_binaries = ['sg', 'ast-grep']
        missing = []

        sg_bin = self._find_sg_binary()
        if not sg_bin.startswith("npx") and not self._is_command_available('sg'):
            missing.append("sg/ast-grep")

        self._add_result(
            DiagnosticResult(
                id="binaries_required",
                name="Required Binaries",
                status="FAIL" if missing else "PASS",
                message=f"Missing binaries: {', '.join(missing)}" if missing else "Required tools available",
                details={"missing_binaries": missing}
            )
        )

    def _find_sg_binary(self) -> str:
        """Find available ast-grep binary."""
        for bin_name in ['sg', 'ast-grep']:
            if self._is_command_available(bin_name):
                return bin_name
        return "npx @ast-grep/cli"

    def _is_command_available(self, cmd: str) -> bool:
        """Check if a command is available in PATH."""
        import shutil
        return shutil.which(cmd) is not None

    def _check_integration_hooks(self):
        """Check for required integration hooks."""
        hook_paths = [
            "hooks/post_authoring",
            "hooks/post_tool_use",
            "hooks/stop"
        ]
        missing = [h for h in hook_paths if not (self.project_root / h).exists()]

        status = "FAIL" if missing else "PASS"
        message = "Missing hooks: " + ", ".join(missing) if missing else "All required hooks present"

        self._add_result(
            DiagnosticResult(
                id="hooks_integration",
                name="Integration Hooks",
                status=status,
                message=message
            )
        )

    def _check_task_load(self):
        """Check task management system health."""
        task_manager_path = self.project_root / "src" / "workflow" / "engine.py"
        exists = task_manager_path.exists()

        self._add_result(
            DiagnosticResult(
                id="task_manager",
                name="Task Management",
                status="PASS" if exists else "WARN",
                message="Task manager available" if exists else "Task management system may be incomplete",
                details={"path": str(task_manager_path)}
            )
        )

    def _check_freshness_state(self):
        """Check freshness state tracking system."""
        freshness_path = self.project_root / "src" / "core" / "durable" / "surfaces" / "freshness_state.py"
        exists = freshness_path.exists()

        self._add_result(
            DiagnosticResult(
                id="freshness_state",
                name="Freshness State Tracking",
                status="PASS" if exists else "WARN",
                message="Freshness state tracking available" if exists else "Consider implementing freshness tracking",
                details={"path": str(freshness_path)}
            )
        )

    def _check_orchestrator_health(self):
        """Check orchestrator surface health."""
        orchestrator_path = self.project_root / "src" / "core" / "durable" / "surfaces" / "orchestrator.py"
        exists = orchestrator_path.exists()

        self._add_result(
            DiagnosticResult(
                id="orchestrator_surface",
                name="Orchestrator Surface",
                status="PASS" if exists else "WARN",
                message="Orchestrator surface available" if exists else "Missing orchestrator coordination layer",
                details={"path": str(orchestrator_path)}
            )
        )

    def _check_status_summary(self):
        """Check status summary surface."""
        status_summary_path = self.project_root / "src" / "core" / "durable" / "surfaces" / "status_summary.py"
        exists = status_summary_path.exists()

        self._add_result(
            DiagnosticResult(
                id="status_summary",
                name="Status Summary Surface",
                status="PASS" if exists else "WARN",
                message="Status summary available" if exists else "Consider implementing status summary tracking",
                details={"path": str(status_summary_path)}
            )
        )

    def get_summary(self) -> str:
        """Generate a human-readable summary of all results."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        warns = sum(1 for r in self.results if r.status == "WARN")

        summary_parts = [
            "🔍 Project Doctor - System Health Summary",
            f"Status: {passed}/{total} passed, {failed} failed, {warns} warning(s)",
            ""
        ]

        for result in self.results:
            status_icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(result.status, "?")
            summary_parts.append(f"{status_icon} {result.name}: {result.message}")

        if failed > 0:
            summary_parts.append("")
            summary_parts.append("🚨 Critical issues identified:")
            for result in self.results:
                if result.status == "FAIL":
                    summary_parts.append(f"   - {result.name}: {result.message}")

        if warns > 0:
            summary_parts.append("")
            summary_parts.append("⚠️  Recommended improvements:")
            for result in self.results:
                if result.status == "WARN":
                    summary_parts.append(f"   - {result.name}: {result.message}")

        return "\n".join(summary_parts)

    def _add_result(self, diagnostic_result: DiagnosticResult):
        """Add diagnostic result to the results list."""
        self.results.append(diagnostic_result)

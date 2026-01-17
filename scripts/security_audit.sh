#!/bin/bash
# Valdrix Security Audit Automation Script
# Runs SAST, Dependency Scanning, and Secret Checks

# set -e removed to ensure all tools run for a complete audit report

echo "--- Starting Valdrix Security Audit ---"

# 1. Python SAST (Bandit)
echo "Running Bandit SAST..."
uv run bandit -r app/ -ll

# 2. Dependency Audit (pip-audit)
echo "Running Python Dependency Audit..."
uv run pip-audit

# 3. Secret Scanning (manual check for illustrative purposes)
echo "Checking for potential secret leaks..."
grep -rE "(password|secret|key|token|auth|pwd)\s*=\s*['\"][^'\"]+['\"]" app/ || echo "No obvious hardcoded secrets found."

# 4. Frontend Audit
if [ -d "dashboard" ]; then
    echo "Running Frontend Dependency Audit..."
    cd dashboard && pnpm audit && cd ..
fi

echo "--- Audit Complete ---"

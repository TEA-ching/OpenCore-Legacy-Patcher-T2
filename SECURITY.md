# Security Policy

## Fork and project naming (doesn't apply to forks forked directly through the GitHub interface)
Forks when naming their projects, they shouldn't put misleading names such as OCLP-T2, OpenCоrе-Legacy-Patcher-T2 (with cyrillic o and e) or OpenCore-Legacy-Patcher-2-2. This is considered typosquatting. If typosquatted, one of the following actions may take place:
1. Scan the fork for malware by human
2. If none is found, the developer of the main project (Albert Müller) may open up an issue requesting to rename the project
3. If the project is confirmed malicious, the main developer (Albert Müller) may report directly to GitHub

This applies only to forks uploading their forks as projects instead of clicking the Fork button. When clicking the Fork button, by default the name is OpenCore Legacy Patcher T2 and these are less visible in the internet and harder for attacks to even pull off.

## Up to date Versions

Ensure you are running one of the latest up-to-date versions:

| Version | Latest version          |
| ------- | ------------------ |
| 4.0.0 | :white_check_mark: |

## Reporting a Vulnerability

We strongly encourage using **Private Vulnerability Reporting** to disclose security issues to maintainers securely and privately.

### How to report:
1. Navigate to the **Security** tab of the repository.
2. Click the **Report a vulnerability** button.
3. Provide all necessary details and a Safe Proof of Concept (PoC) that does not contain or distribute real malware.

### Out-of-Scope Reports:
**Do not** report disabling SIP (System Integrity Protection) or AMFI (Apple Mobile File Integrity) as vulnerabilities. These are necessary components for bypassing minimum system requirements and will be dismissed.

Note:
If it is a fork of this project, then enabling the Report a vulnerability button is up to the maintainer of the fork. In case they don't enable this button, open an Issue with a [Vulnerability] tag.

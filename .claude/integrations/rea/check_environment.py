#!/usr/bin/env python3
"""Read-only PATH and runtime checks for optional REA integration."""
import json
import re
import shutil
import subprocess


def version_of(path, args):
    if not path:
        return None
    try:
        result = subprocess.run([path, *args], capture_output=True, text=True, timeout=8)
        return {'exit_code': result.returncode,
                'text': (result.stdout or result.stderr).strip()[:1000]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error': str(exc)}


def supported_node(text):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', text.strip())
    if not match:
        return None
    major, minor, patch = map(int, match.groups())
    return ((major == 22 and minor >= 19)
            or (major == 24 and minor >= 11)
            or major >= 26)


def main():
    paths = {name: shutil.which(name) for name in ('node', 'npm', 'claude', 'rea', 'ps')}
    node = version_of(paths['node'], ['--version'])
    npm = version_of(paths['npm'], ['--version'])
    ps = version_of(paths['ps'], ['--version'])
    valid_node = supported_node(node.get('text', '')) if node and node.get('exit_code') == 0 else None
    print(json.dumps({
        'paths': paths,
        'versions': {'node': node, 'npm': npm, 'ps': ps},
        'node_requirement_at_sync': '^22.19.0 || ^24.11.0 || >=26.0.0',
        'node_version_supported': valid_node,
        'runtime_prerequisites_found': bool(valid_node and npm and npm.get('exit_code') == 0),
        'procps_detected': bool(ps and 'procps' in ps.get('text', '').lower()),
        'mcp_connection': 'not inspected; verify actual tools in the agent session',
        'analysis_engines': 'not inspected; select provider only for tasks requiring it',
        'mutations': 'none; no package download, registration or target execution',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

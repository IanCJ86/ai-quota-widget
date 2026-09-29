"""Stable per-user state outside MSIX's virtualized AppData tree.

Discovery is read-only. Only the owning GUI (or explicit installer migration)
creates the shared directory; a diagnostic command must never migrate data.
"""
import os
from pathlib import Path
import shutil
import sys
import tempfile

STATE_FILES = ('config.json', 'settings.json', 'glm-key.dpapi', 'deepseek-key.dpapi',
               'last-good.json', 'deepseek-spend.json', 'harness-totals.json',
               'query-history.json')


def data_locations(source, environ=None, frozen=None):
    env = os.environ if environ is None else environ
    if env.get('AI_QUOTA_WIDGET_DATA_DIR'):
        return Path(env['AI_QUOTA_WIDGET_DATA_DIR']), None
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if not frozen and 'site-packages' not in str(source):
        return Path(source), None
    profile = Path(env.get('USERPROFILE') or os.path.expanduser('~'))
    return profile / '.ai-quota-widget', Path(env.get('LOCALAPPDATA') or profile / 'AppData/Local') / 'AIQuotaWidget'


def resolve_data_dir(source):
    target, legacy = data_locations(source)
    if not target.exists() and legacy and legacy.is_dir():
        return str(legacy)  # read-only CLI compatibility before first GUI launch
    return str(target)


def _reject_links(path):
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or
                getattr(part.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
            raise OSError('StatePathIsReparsePoint')


def migrate_data(target, legacy=None):
    """Copy then atomically publish once; never overwrite an existing target.

    No merging of credentials or different account histories. The caller must
    own the GUI instance mutex. Originals are deliberately kept for recovery.
    """
    target = Path(target)
    _reject_links(target)
    if target.exists():
        if not target.is_dir():
            raise OSError('StatePathIsNotDirectory')
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.aiquota-migrate-', dir=target.parent))
    try:
        if legacy and Path(legacy).is_dir():
            legacy = Path(legacy)
            _reject_links(legacy)
            for name in STATE_FILES:
                src = legacy / name
                if src.is_symlink():
                    raise OSError('StateFileIsLink')
                if src.exists():
                    _reject_links(src)
                    if not src.is_file():
                        raise OSError('StateFileIsNotRegular')
                    shutil.copy2(src, stage / name)
                    if src.read_bytes() != (stage / name).read_bytes():
                        raise OSError('StateMigrationVerificationFailed')
        stage.rename(target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)  # only our freshly created staging directory
    return target

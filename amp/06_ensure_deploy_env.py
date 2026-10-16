"""AMP: ``.solomon/deploy.env`` が無ければ example から生成する。

再 Deploy 後もユーザーが編集した ``.solomon/deploy.env`` は上書きしない。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from solomon.infra.deploy_env import project_dir


def main() -> int:
    root = project_dir()
    target = root / ".solomon" / "deploy.env"
    example = root / "deploy" / "deploy.env.example"

    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        print(f"[amp:06] keep existing {target}", flush=True)
        return 0

    if not example.is_file():
        print(f"[amp:06] example missing: {example}", flush=True)
        return 0

    shutil.copyfile(example, target)
    print(
        f"[amp:06] created {target} from example — "
        "edit secrets in .solomon/secrets.env if needed, then Restart Solomon Application",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

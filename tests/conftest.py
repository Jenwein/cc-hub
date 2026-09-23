# -*- coding: utf-8 -*-
from pathlib import Path

import pytest


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    from cc_hub.commands.init import init_hub

    target = tmp_path / "hub"
    init_hub(target, git=False)
    return target

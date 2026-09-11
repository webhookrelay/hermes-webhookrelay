from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_git_install_layout_has_root_entrypoint_and_manifest():
    assert (ROOT / "__init__.py").is_file()
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text())

    assert manifest["name"] == "webhookrelay"
    assert manifest["kind"] == "platform"
    assert set(manifest["provides_tools"]) == {
        "webhookrelay_queue_status",
        "webhookrelay_list_failed_events",
        "webhookrelay_get_event",
    }

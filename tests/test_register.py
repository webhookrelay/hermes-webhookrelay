from pathlib import Path

import webhookrelay_hermes


class Context:
    def __init__(self):
        self.platforms = []
        self.cli = []
        self.tools = []
        self.skills = []

    def register_platform(self, **kwargs):
        self.platforms.append(kwargs)

    def register_cli_command(self, **kwargs):
        self.cli.append(kwargs)

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_skill(self, **kwargs):
        assert isinstance(kwargs["path"], Path) and kwargs["path"].exists()
        self.skills.append(kwargs)


def test_registers_all_surfaces():
    ctx = Context()
    webhookrelay_hermes.register(ctx)
    assert [x["name"] for x in ctx.platforms] == ["webhookrelay"]
    assert [x["name"] for x in ctx.cli] == ["webhookrelay"]
    assert {x["name"] for x in ctx.tools} == {
        "webhookrelay_queue_status",
        "webhookrelay_list_failed_events",
        "webhookrelay_get_event",
    }
    assert [x["name"] for x in ctx.skills] == ["triage-webhookrelay-events"]
    assert "untrusted" in ctx.platforms[0]["platform_hint"].lower()

from bot.utils.bot_commands import owner_bot_commands, private_bot_commands


def test_private_commands_do_not_include_claim_owner() -> None:
    commands = {command.command for command in private_bot_commands()}

    assert "claim_owner" not in commands


def test_owner_commands_include_stats() -> None:
    commands = {command.command for command in owner_bot_commands()}

    assert "stats" in commands

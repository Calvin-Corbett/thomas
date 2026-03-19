try:
    from thomas.cli.heartbeat_cmd import heartbeat_command

    cli.add_command(heartbeat_command)
except Exception as e:
    log.debug("Failed to register heartbeat command: %s", e)

try:
    from thomas.cli.commands.investigate import register_investigate_commands

    register_investigate_commands(cli)
except Exception as e:
    log.debug("Failed to register investigate commands: %s", e)


if __name__ == "__main__":
    main()
